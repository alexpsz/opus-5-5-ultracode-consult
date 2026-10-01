"""Shared-directory delivery tests, independent of live model capability."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import collect_delivery as c


class NamedDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # Resolve only our trusted fixture, not adviser-selected file paths.
        self.root = Path(self.temp.name).resolve()
        self.session_path = self.root / 'r1.gemini.session.json'
        self.receipt = self.root / 'r1.gemini.receipt.json'
        self.session = {
            'schema_version': 2, 'request_id': 'r1', 'adviser': 'gemini',
            'input_manifest_sha256': 'a' * 64, 'output_directory': str(self.root),
            'report_file': 'r1.gemini.report.md', 'completion_file': 'r1.gemini.completion.json',
            'findings_file': None, 'sentinel': 'END-R1', 'dispatch_state': 'SENT',
            'generation_stopped': True, 'unresolved_approval': False,
        }
        self.completion = {
            'schema_version': 2, 'request_id': 'r1', 'adviser': 'gemini',
            'input_manifest_sha256': 'a' * 64, 'status': 'complete',
            'report_file': 'r1.gemini.report.md', 'findings_file': None,
        }
        self.report = b'# r1\nIndependent recommendation.\nEND-R1\n'
        (self.root / self.session['report_file']).write_bytes(self.report)
        self.write(self.root / self.session['completion_file'], self.completion)
        self.write(self.session_path, self.session)

    def write(self, path, value):
        path.write_text(json.dumps(value), encoding='utf-8')

    def collect(self):
        return c.collect(self.session_path, stable_seconds=0, receipt_file=self.receipt)

    def failure(self, code):
        with self.assertRaises(c.DeliveryError) as caught:
            self.collect()
        self.assertEqual(caught.exception.code, code)

    def test_shared_directory_only_reads_selected_files(self):
        (self.root / 'other.opus.report.md').write_bytes(b'OTHER PRIVATE REVIEW')
        (self.root / 'packet.md').write_bytes(b'neutral material')
        (self.root / 'subdirectory').mkdir()
        with mock.patch.object(c, 'read_file', wraps=c.read_file) as reads:
            self.assertEqual(self.collect()['file_count'], 2)
        self.assertNotIn('other.opus.report.md', [call.args[0].name for call in reads.call_args_list])
        receipt = json.loads(self.receipt.read_bytes())
        self.assertEqual(receipt['files']['r1.gemini.report.md']['sha256'], hashlib.sha256(self.report).hexdigest())

    def test_identical_retry_does_not_rewrite_receipt(self):
        self.collect()
        original = (self.receipt.read_bytes(), self.receipt.stat().st_mtime_ns)
        self.assertEqual(self.collect()['receipt_action'], 'RECOVERED_IDENTICAL')
        self.assertEqual(original, (self.receipt.read_bytes(), self.receipt.stat().st_mtime_ns))

    def test_missing_completion_and_wrong_identity_are_incomplete(self):
        path = self.root / self.session['completion_file']
        path.unlink()
        self.failure('MISSING_DELIVERABLE')
        self.write(path, {**self.completion, 'adviser': 'opus'})
        self.failure('IDENTITY_MISMATCH')

    def test_named_path_and_controller_overlap_rejected(self):
        for name in ('../other.md', 'c:/other.md', 'report.md:ads', 'sub/report.md', 'CON.md'):
            self.write(self.session_path, {**self.session, 'report_file': name})
            self.failure('INVALID_DELIVERABLE_NAME')
        self.write(self.session_path, {**self.session, 'report_file': self.session_path.name})
        self.failure('CONTROLLER_PATH_OVERLAP')

    def test_source_mutation_rejected_but_other_writer_is_allowed(self):
        with mock.patch.object(c.time, 'sleep', side_effect=lambda _: (self.root / 'other.report.md').write_bytes(b'new')):
            self.assertEqual(self.collect()['status'], 'PASS')
        with mock.patch.object(c.time, 'sleep', side_effect=lambda _: (self.root / self.session['report_file']).write_bytes(self.report.replace(b'Independent', b'Revised'))):
            self.failure('DELIVERY_CHANGED_DURING_STABILITY')

    def test_changed_report_after_receipt_is_rejected(self):
        self.collect()
        (self.root / self.session['report_file']).write_bytes(self.report.replace(b'Independent', b'Changed'))
        self.failure('RECEIPT_CONFLICT')

    def test_missing_sentinel_and_running_ui_state_rejected(self):
        (self.root / self.session['report_file']).write_bytes(self.report + b'continued')
        self.failure('REPORT_SENTINEL_MISSING')
        self.write(self.session_path, {**self.session, 'generation_stopped': False})
        self.failure('GENERATION_NOT_STOPPED')

    def test_optional_findings_and_required_findings(self):
        self.write(self.session_path, {**self.session, 'findings_file': 'r1.gemini.findings.json', 'findings_required': True})
        self.failure('REQUIRED_FINDINGS_MISSING')
        self.write(self.root / self.session['completion_file'], {**self.completion, 'findings_file': 'r1.gemini.findings.json'})
        self.write(self.root / 'r1.gemini.findings.json', {
            'schema_version': 2, 'request_id': 'r1', 'adviser': 'gemini',
            'input_manifest_sha256': 'a'*64, 'recommendation': 'Keep current design.',
            'findings': [], 'evidence_read': ['packet.md'], 'unknowns': [],
        })
        self.assertEqual(self.collect()['file_count'], 3)

    def test_all_identity_fields_must_match(self):
        for field, value in (('request_id', 'different-request'),
                             ('adviser', 'opus'),
                             ('input_manifest_sha256', 'b' * 64)):
            with self.subTest(field=field):
                self.write(self.root / self.session['completion_file'],
                           {**self.completion, field: value})
                self.failure('IDENTITY_MISMATCH')
                self.assertFalse(self.receipt.exists())

    def test_duplicate_and_malformed_completion_never_create_receipt(self):
        path = self.root / self.session['completion_file']
        for data, error in ((b'{"a":1,"a":2}', 'DUPLICATE_JSON_KEY'),
                            (b'{"status":', 'INVALID_JSON'),
                            (b'{"value":Infinity}', 'INVALID_JSON'),
                            (b'\xff', 'INVALID_UTF8')):
            with self.subTest(error=error):
                path.write_bytes(data)
                self.failure(error)
                self.assertFalse(self.receipt.exists())

    def test_case_alias_and_reserved_names_are_rejected(self):
        for name in ('R1.GEMINI.COMPLETION.JSON', 'nul.txt', 'com1.md',
                     'x..report.md', 'report.md.', 'report.md ', '\\outside.md'):
            with self.subTest(name=name):
                self.write(self.session_path, {**self.session, 'report_file': name})
                self.failure('INVALID_DELIVERABLE_NAME')

    def test_receipt_cannot_overwrite_session_or_report(self):
        for path in (self.session_path, self.root / self.session['report_file']):
            with self.subTest(path=path.name):
                before = path.read_bytes()
                self.receipt = path
                self.failure('CONTROLLER_PATH_OVERLAP')
                self.assertEqual(path.read_bytes(), before)

    def test_partial_receipt_stays_untouched(self):
        self.receipt.write_bytes(b'{"interrupted":')
        self.failure('INVALID_JSON')
        self.assertEqual(self.receipt.read_bytes(), b'{"interrupted":')

    def test_report_hardlink_is_rejected(self):
        target = self.root / 'outside.md'
        target.write_bytes(self.report)
        report_path = self.root / self.session['report_file']
        report_path.unlink()
        os.link(target, report_path)
        self.failure('HARDLINK_REFUSED')

    def test_report_symlink_is_rejected(self):
        target = self.root / 'outside.md'
        target.write_bytes(self.report)
        report_path = self.root / self.session['report_file']
        report_path.unlink()
        try:
            report_path.symlink_to(target)
        except OSError:
            self.skipTest('Host does not permit symlink creation')
        self.failure('LINK_OR_REPARSE_REFUSED')

    def test_output_parent_symlink_is_rejected(self):
        actual = self.root / 'actual'
        actual.mkdir()
        alias = self.root / 'alias'
        try:
            alias.symlink_to(actual, target_is_directory=True)
        except OSError:
            self.skipTest('Host does not permit directory symlink creation')
        self.write(self.session_path, {**self.session, 'output_directory': str(alias)})
        self.failure('LINK_OR_REPARSE_REFUSED')

    def test_bool_schema_version_and_unresolved_dispatch_are_rejected(self):
        for field, value, error in (('schema_version', True, 'INVALID_SESSION_SCHEMA'),
                                    ('dispatch_state', 'UNKNOWN', 'NOT_SENT'),
                                    ('unresolved_approval', True, 'UNRESOLVED_APPROVAL')):
            with self.subTest(field=field):
                self.write(self.session_path, {**self.session, field: value})
                self.failure(error)


if __name__ == '__main__':
    unittest.main()
