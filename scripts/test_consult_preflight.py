import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import consult_preflight as p


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.home = self.root / 'home'; self.home.mkdir()
        self.project = self.root / 'project'; self.project.mkdir()
        self.exe = self.root / 'cli'; self.exe.write_text('fixture')
        self.prompt = self.project / 'prompt.txt'; self.prompt.write_text('Review inline evidence.')
        self.settings = self.home / '.gemini/antigravity-cli/settings.json'
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text(json.dumps({'permissions': {'allow': ['read_url(*)']}}))
        self.home_patch = patch.object(Path, 'home', return_value=self.home)
        self.home_patch.start(); self.addCleanup(self.home_patch.stop)
        self.host_patch = patch.object(p, 'check_host_context', return_value={'ok': True, 'auth_tested': False})
        self.host_mock = self.host_patch.start(); self.addCleanup(self.host_patch.stop)

    def check(self, adviser='gemini', **kwargs):
        return p.check_run(adviser=adviser, executable=self.exe, project=self.project,
                           prompt_file=self.prompt, prompt=self.prompt.read_bytes(), **kwargs)

    def manifest(self, path):
        data = {'root': str(self.project), 'inputs': [
            {'absolute_path': str(path), 'bytes': path.stat().st_size,
             'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'role': 'screenshot'}]}
        manifest = self.project / 'manifest.json'; manifest.write_text(json.dumps(data))
        self.prompt.write_text('INPUT_MANIFEST: ' + str(manifest) + '\nINPUT_MANIFEST_SHA256: ' +
                               hashlib.sha256(manifest.read_bytes()).hexdigest() + '\nReview.')
        return manifest

    def test_host_denial_blocks_before_auth_or_dispatch(self):
        self.host_mock.return_value = {'ok': False, 'error_code': 'HOST_CONTEXT_REQUIRED', 'failed_check': 'loopback_bind'}
        self.assertEqual(self.check()['error_code'], 'HOST_CONTEXT_REQUIRED')

    def test_host_probe_closes_socket_and_cleans_tempfile(self):
        self.host_patch.stop()
        with patch.object(p.socket, 'socket') as mocked:
            result = p.check_host_context()
            mocked.return_value.__enter__.return_value.bind.assert_called_once_with(('127.0.0.1', 0))
            mocked.return_value.__exit__.assert_called_once()
        self.assertTrue(result['ok'])
        self.assertFalse(result['sandbox_escape_verified'])
        self.assertFalse(result['auth_tested'])
        self.assertEqual(list(p.cache_root().glob('.preflight-*')), [])

    def test_host_probe_reports_bind_permission_denial(self):
        self.host_patch.stop()
        with patch.object(p.socket, 'socket', side_effect=PermissionError('blocked')):
            result = p.check_host_context()
        self.assertEqual(result['error_code'], 'HOST_CONTEXT_REQUIRED')
        self.assertEqual(result['failed_check'], 'loopback_bind')

    def test_default_network_enabled_both(self):
        self.assertTrue(self.check()['ok'])
        self.assertEqual(self.check('opus')['checks']['network']['default'], '--allowedTools WebSearch WebFetch')

    def test_missing_global_rule_blocks_without_editing(self):
        raw = b'{"permissions":{"allow":["read_file(assets)"]},"unrelated":true}'
        self.settings.write_bytes(raw)
        self.assertEqual(self.check()['error_code'], 'WEB_DEFAULT_MISSING')
        self.assertEqual(self.settings.read_bytes(), raw)

    def test_explicit_global_deny_preserved(self):
        self.settings.write_text(json.dumps({'permissions': {'allow': ['read_url(*)'], 'deny': ['read_url(*)']}}))
        self.assertEqual(self.check()['error_code'], 'WEB_POLICY_BLOCKED')

    def test_domain_rule_does_not_disable_all_other_domains(self):
        self.settings.write_text(json.dumps({'permissions': {'allow': ['read_url(*)'], 'ask': ['read_url(private.test)']}}))
        result = self.check()
        self.assertTrue(result['ok'])
        self.assertIn('DOMAIN_SPECIFIC_WEB_RULES_PRESERVED', result['warnings'])

    def test_claude_project_deny_detected(self):
        settings = self.project / '.claude/settings.local.json'; settings.parent.mkdir()
        settings.write_text('{"permissions":{"deny":["WebSearch"]}}')
        self.assertEqual(self.check('opus')['error_code'], 'WEB_POLICY_BLOCKED')

    def test_external_screenshot_blocks_before_submission(self):
        image = self.root / 'external.png'; image.write_bytes(b'unchanged image')
        self.manifest(image)
        result = self.check()
        self.assertEqual(result['error_code'], 'INPUTS_OUTSIDE_PROJECT_NEED_STAGING')
        self.assertEqual(result['input_manifest']['outside_project'], [str(image)])

    def test_authorized_exact_external_grant(self):
        image = self.root / 'external.png'; image.write_bytes(b'unchanged image')
        self.manifest(image)
        self.settings.write_text(json.dumps({'permissions': {'allow': ['read_url(*)', 'read_file(' + str(image) + ')']}}))
        self.assertTrue(self.check()['ok'])

    def test_external_deny_overrides_read_grant(self):
        image = self.root / 'external.png'; image.write_bytes(b'unchanged image')
        self.manifest(image)
        self.settings.write_text(json.dumps({'permissions': {'allow': ['read_url(*)', 'read_file(*)'],
                                                            'deny': ['read_file(' + str(image) + ')']}}))
        self.assertEqual(self.check()['error_code'], 'INPUT_POLICY_BLOCKED')

    def test_project_input_verified_without_new_permission(self):
        image = self.project / 'image.png'; image.write_bytes(b'actual image')
        self.manifest(image)
        self.assertTrue(self.check()['ok'])
        image.write_bytes(b'changed image')
        self.assertEqual(self.check()['error_code'], 'INPUT_HASH_OR_SIZE_MISMATCH')

    def test_manifest_tamper(self):
        image = self.project / 'image.png'; image.write_bytes(b'image')
        manifest = self.manifest(image)
        manifest.write_text(manifest.read_text() + '\n')
        self.assertEqual(self.check()['error_code'], 'INPUT_MANIFEST_HASH_MISMATCH')

    def test_controller_only_external_manifest_is_not_adviser_input(self):
        image = self.project / 'image.png'; image.write_bytes(b'image')
        original = self.manifest(image)
        external = self.root / 'controller-manifest.json'; external.write_bytes(original.read_bytes())
        self.prompt.write_text('Review inline and declared project evidence.')
        self.assertTrue(self.check(input_manifest=str(external))['ok'])

    def test_manifest_path_type_error_is_structured(self):
        image = self.project / 'image.png'; image.write_bytes(b'image')
        manifest = self.manifest(image)
        data = json.loads(manifest.read_text()); data['inputs'][0]['project_relative_path'] = 42
        manifest.write_text(json.dumps(data)); self.prompt.write_text('Review inline.')
        self.assertEqual(self.check(input_manifest=str(manifest))['error_code'], 'INVALID_RELATIVE_INPUT')

    def test_project_file_explicit_deny_stays_blocked(self):
        image = self.project / 'image.png'; image.write_bytes(b'image')
        self.manifest(image)
        self.settings.write_text(json.dumps({'permissions': {'allow': ['read_url(*)'],
                                                            'deny': ['read_file(image.png)']}}))
        self.assertEqual(self.check()['error_code'], 'INPUT_POLICY_BLOCKED')

    def test_manifest_ambiguity(self):
        self.prompt.write_text('INPUT_MANIFEST: /one\nINPUT_MANIFEST: /two\n')
        self.assertEqual(self.check()['error_code'], 'AMBIGUOUS_DISPATCH_HEADER')

    def test_crlf_manifest_retains_external_access_and_deny_checks(self):
        image = self.root / 'external.png'; image.write_bytes(b'unchanged image')
        self.manifest(image)
        self.prompt.write_bytes(self.prompt.read_text().replace('\n', '\r\n').encode('utf-8'))
        before = self.prompt.read_bytes()
        result = self.check()
        self.assertEqual(result['error_code'], 'INPUTS_OUTSIDE_PROJECT_NEED_STAGING')
        self.assertEqual(result['input_manifest']['outside_project'], [str(image)])
        self.settings.write_text(json.dumps({'permissions': {'allow': ['read_url(*)', 'read_file(*)'],
                                                            'deny': ['read_file(' + str(image) + ')']}}))
        self.assertEqual(self.check()['error_code'], 'INPUT_POLICY_BLOCKED')
        self.assertEqual(self.prompt.read_bytes(), before)

    def test_crlf_manifest_still_checks_manifest_and_input_bytes(self):
        image = self.project / 'image.png'; image.write_bytes(b'actual image\r\n')
        manifest = self.manifest(image)
        self.prompt.write_bytes(self.prompt.read_text().replace('\n', '\r\n').encode('utf-8'))
        result = self.check()
        self.assertTrue(result['ok'])
        self.assertEqual(result['input_manifest']['status'], 'HASHES_VERIFIED_ACCESS_UNVERIFIED')
        image.write_bytes(b'actual image\n')
        self.assertEqual(self.check()['error_code'], 'INPUT_HASH_OR_SIZE_MISMATCH')
        manifest.write_bytes(manifest.read_bytes() + b'\r\n')
        self.assertEqual(self.check()['error_code'], 'INPUT_MANIFEST_HASH_MISMATCH')

    def test_crlf_packet_hash_uses_original_bytes(self):
        packet = self.project / 'packet.txt'; packet.write_bytes(b'evidence\r\nsecond line\r\n')
        self.prompt.write_bytes(('PACKET: ' + str(packet) + '\r\nPACKET_SHA256: ' +
                                 hashlib.sha256(packet.read_bytes()).hexdigest() + '\r\nReview.').encode('utf-8'))
        result = self.check()
        self.assertTrue(result['ok'])
        self.assertEqual(result['input_manifest']['packet']['bytes'], len(packet.read_bytes()))
        packet.write_bytes(packet.read_bytes().replace(b'\r\n', b'\n'))
        self.assertEqual(self.check()['error_code'], 'PACKET_HASH_MISMATCH')

    def test_crlf_duplicate_and_empty_headers_fail_without_consuming_next_line(self):
        self.prompt.write_bytes(b'INPUT_MANIFEST: /one\r\nINPUT_MANIFEST: /two\r\n')
        self.assertEqual(self.check()['error_code'], 'AMBIGUOUS_DISPATCH_HEADER')
        for ending in (b'\n', b'\r\n'):
            for name in (b'PACKET', b'PACKET_SHA256', b'INPUT_MANIFEST', b'INPUT_MANIFEST_SHA256'):
                with self.subTest(ending=ending, name=name):
                    self.prompt.write_bytes(name + b': \t' + ending + b'Next-line is not a header value.')
                    self.assertEqual(self.check()['error_code'], 'INVALID_DISPATCH_HEADER')

    def test_symlink_settings_rejected(self):
        raw = self.settings.read_bytes(); self.settings.unlink()
        target = self.root / 'target'; target.write_bytes(raw)
        self.settings.symlink_to(target)
        self.assertFalse(self.check()['ok'])

    def test_cache_invalidation_and_no_auth_claim(self):
        checked = self.check()
        receipt = {'preflight': checked, 'request_id': 'one', 'adviser': 'gemini',
                   'native_final_observed': True, 'session_ids': ['native'], 'delivery_status': 'COMPLETE'}
        self.assertEqual(p.record_outcome(receipt)['status'], 'RECORDED')
        cached = self.check()
        self.assertEqual(cached['cache']['status'], 'HIT')
        self.assertEqual(cached['cache']['auth_current'], 'UNVERIFIED')
        self.settings.write_text(json.dumps(json.loads(self.settings.read_text()), indent=4))
        self.assertEqual(self.check()['cache']['status'], 'HIT')
        self.exe.write_text('updated executable')
        self.assertEqual(self.check()['cache']['status'], 'MISS')

    def test_no_credentials_saved_to_cache(self):
        receipt = {'preflight': self.check(), 'native_final_observed': True, 'session_ids': ['s'],
                   'argv': ['private'], 'auth_token': 'secret-never-cache', 'stderr': 'secret-never-cache'}
        cached = p.record_outcome(receipt)
        raw = Path(cached['path']).read_text()
        self.assertNotIn('secret-never-cache', raw)
        self.assertNotIn('argv', raw)

    def test_cache_symlink_cannot_overwrite_target(self):
        checked = self.check(); root = p.cache_root(); root.mkdir(parents=True)
        target = self.root / 'target'; target.write_bytes(b'keep')
        (root / (checked['cache_key'] + '.json')).symlink_to(target)
        result = p.record_outcome({'preflight': checked, 'native_final_observed': True, 'session_ids': ['x']})
        self.assertEqual(result['status'], 'CACHE_UNWRITABLE')
        self.assertEqual(target.read_bytes(), b'keep')

    def test_failure_classification_and_successful_auth_warning(self):
        self.assertEqual(p.classify_failure(b'listen EPERM localhost', {}), 'HOST_CONTEXT_REQUIRED')
        self.assertEqual(p.classify_failure(b'Please log in', {}), 'AUTH_REQUIRED')
        self.assertEqual(p.classify_failure(b'Please sign in to view available models. Launch the CLI without arguments to sign in.', {}), 'AUTH_REQUIRED')
        self.assertEqual(p.classify_failure(b'Model not found', {}), 'MODEL_UNAVAILABLE')
        self.assertIsNone(p.classify_failure(b'Please log in', {'receipt': {'native_final_success': True}}))
        self.assertIsNone(p.classify_failure(b'', {'events': [{'type':'assistant','text':'please log in'}]}))


if __name__ == '__main__':
    unittest.main()
