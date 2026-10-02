"""Regression coverage for retained bytes, retry safety, and typed observations."""
import json
import unittest
from pathlib import Path
from unittest import mock

import test_collect_delivery_v2 as fixture

c = fixture.c


class ArchiveTests(unittest.TestCase):
    setUp = fixture.NamedDeliveryTests.setUp
    write = fixture.NamedDeliveryTests.write
    collect = fixture.NamedDeliveryTests.collect
    failure = fixture.NamedDeliveryTests.failure

    @property
    def archive(self):
        return Path(str(self.receipt) + '.archive')

    def test_default_archive_retains_original_bytes_after_source_changes(self):
        result = self.collect()
        self.assertEqual(result['archive_action'], 'CREATED')
        self.assertEqual(result['archive_directory'], str(self.archive))
        original = (self.archive / self.session['report_file']).read_bytes()
        (self.root / self.session['report_file']).write_bytes(b'# r1\nCHANGED\nEND-R1\n')
        self.failure('RECEIPT_CONFLICT')
        self.assertEqual((self.archive / self.session['report_file']).read_bytes(), original)
        self.assertEqual(original, self.report)

    def test_archive_retry_preserves_original_receipts_and_mtime(self):
        self.collect()
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.archive.iterdir()}
        result = self.collect()
        self.assertEqual(result['archive_action'], 'RECOVERED_IDENTICAL')
        self.assertEqual(before, {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
                                  for p in self.archive.iterdir()})

    def test_partial_archive_is_never_filled_or_committed(self):
        self.archive.mkdir()
        original = self.archive / self.session['report_file']
        original.write_bytes(b'partial')
        self.failure('PARTIAL_SNAPSHOT')
        self.assertEqual(original.read_bytes(), b'partial')
        self.assertFalse(self.receipt.exists())
        self.assertEqual(len(list(self.archive.iterdir())), 1)

    def test_crash_after_archive_before_external_receipt_can_retry(self):
        real = c.save_receipt
        def fail_commit(*args, **kwargs):
            if kwargs.get('check_only'):
                return real(*args, **kwargs)
            raise OSError('simulated process failure')
        with mock.patch.object(c, 'save_receipt', side_effect=fail_commit):
            with self.assertRaises(OSError):
                self.collect()
        self.assertTrue((self.archive / '.archive-receipt.json').is_file())
        self.assertFalse(self.receipt.exists())
        self.assertEqual(self.collect()['archive_action'], 'RECOVERED_IDENTICAL')

    def test_existing_legacy_receipt_can_gain_archive_without_rewriting(self):
        files = c.read_named(self.root, c.delivery_names(self.session))
        c.save_receipt(files, self.session, self.receipt)
        original = self.receipt.read_bytes()
        self.assertEqual(self.collect()['archive_action'], 'CREATED')
        self.assertEqual(original, self.receipt.read_bytes())

    def test_custom_archive_and_controller_overlap(self):
        for target in (self.root, self.session_path, self.receipt,
                       self.root / self.session['report_file']):
            with self.subTest(target=target):
                with self.assertRaises(c.DeliveryError) as caught:
                    c.collect(self.session_path, stable_seconds=0,
                              receipt_file=self.receipt, archive_dir=target)
                self.assertEqual(caught.exception.code, 'ARCHIVE_PATH_OVERLAP')
        custom = self.root / 'saved'
        result = c.collect(self.session_path, stable_seconds=0,
                           receipt_file=self.receipt, archive_dir=custom)
        self.assertEqual(result['archive_directory'], str(custom))
        self.assertFalse(self.archive.exists())

    def test_symlink_archive_rejected(self):
        target = self.root / 'outside'
        target.mkdir()
        self.archive.symlink_to(target, target_is_directory=True)
        self.failure('LINK_OR_REPARSE_REFUSED')
        self.assertEqual(list(target.iterdir()), [])

    def test_string_observation_cannot_become_verified_by_truthiness(self):
        self.write(self.session_path, {**self.session, 'input_access_verified': 'partial_native_read_log'})
        self.failure('INVALID_SESSION_SCHEMA')
        self.assertFalse(self.archive.exists())
        self.write(self.session_path, {**self.session, 'input_access_verified': False,
                                      'input_access_status': 'partial'})
        self.assertEqual(self.collect()['status'], 'PASS')  # protocol only, still not full access

    def test_ui_conflict_blocks_collection_even_when_stopped_claimed(self):
        self.write(self.session_path, {**self.session, 'ui_evidence_conflict': True})
        self.failure('UI_EVIDENCE_CONFLICT')
        self.assertFalse(self.archive.exists())

    def test_current_state_must_match_collector_mirror(self):
        current = {k: self.session[k] for k in
                   ('dispatch_state', 'generation_stopped', 'unresolved_approval')}
        current['generation_stopped'] = False
        self.write(self.session_path, {**self.session,
                   'controller_state': {'version': 1, 'current': current, 'history': []}})
        self.failure('STATE_MIRROR_MISMATCH')

    def test_managed_sent_requires_observed_submission_and_locator(self):
        for observed, locator in ((False, 'conversation-1'), (True, ''), (True, None)):
            with self.subTest(observed=observed, locator=locator):
                session = {**self.session, 'submission_observed': observed,
                           'conversation_locator': locator}
                current = {k: session[k] for k in ('dispatch_state', 'generation_stopped',
                           'unresolved_approval', 'submission_observed', 'conversation_locator')}
                session['controller_state'] = {'version': 1, 'current': current, 'history': []}
                self.write(self.session_path, session)
                self.failure('SUBMISSION_EVIDENCE_REQUIRED')
                self.assertFalse(self.receipt.exists())
        current.update(submission_observed=True, conversation_locator='conversation-1')
        session.update(submission_observed=True, conversation_locator='conversation-1')
        self.write(self.session_path, session)
        self.assertEqual(self.collect()['status'], 'PASS')

    def test_legacy_explicit_unobserved_submission_is_not_accepted(self):
        self.write(self.session_path, {**self.session, 'submission_observed': False})
        self.failure('SUBMISSION_EVIDENCE_REQUIRED')


if __name__ == '__main__':
    unittest.main()
