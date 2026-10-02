import contextlib
import datetime as dt
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent
if SCRIPTS.name == "tests":
    SCRIPTS = SCRIPTS.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import consult_state as helper

NOW = "2026-10-01T11:00:00+00:00"
LATER = "2026-10-01T11:01:00+00:00"


class ConsultStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / "opus.session.json"
        self.base = {
            "schema_version": 2, "request_id": "r1", "adviser": "opus",
            "input_manifest_sha256": "a" * 64, "output_directory": str(self.root),
            "report_file": "opus.report.md", "completion_file": "opus.completion.json",
            "findings_file": None, "sentinel": "SENTINEL", "dispatch_state": "NOT_SENT",
            "generation_stopped": False, "unresolved_approval": False,
        }
        self.write(self.base)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, document):
        self.path.write_text(json.dumps(document), encoding="utf-8")

    def current(self, **changes):
        value = {"phase": "preparing", "dispatch_state": "NOT_SENT",
                 "generation_stopped": False, "unresolved_approval": False,
                 "input_access_verified": False, "input_access_status": "unknown"}
        value.update(changes)
        return value

    def event(self, current=None, **changes):
        value = {"expected_sha256": helper.read_json(self.path)[1], "event_id": "e1",
                 "observed_at": NOW, "current": current or self.current(), "migrate_legacy": True}
        value.update(changes)
        return value

    def inspect(self):
        return helper.inspect(self.path, dt.datetime.fromisoformat(NOW))

    def assert_error(self, code, fn, *args):
        with self.assertRaises(helper.delivery.DeliveryError) as result:
            fn(*args)
        self.assertEqual(result.exception.code, code)

    def test_unknown_never_authorizes_resend_or_regression(self):
        handoff = self.current(phase="manual_handoff", dispatch_state="UNKNOWN",
                               controller_send_attempted=False)
        helper.update(self.path, self.event(handoff))
        self.assertEqual(self.inspect()["action"], "RECOVER_SUBMISSION")
        before = self.path.read_bytes()
        self.assert_error("DISPATCH_REGRESSION", helper.update, self.path,
                          self.event(event_id="e2", observed_at=LATER))
        self.assertEqual(self.path.read_bytes(), before)

    def test_handoff_requires_unknown_and_no_controller_send(self):
        for changes in ({"dispatch_state": "NOT_SENT", "controller_send_attempted": False},
                        {"dispatch_state": "UNKNOWN", "controller_send_attempted": True},
                        {"dispatch_state": "UNKNOWN"}):
            self.assert_error("INVALID_MANUAL_HANDOFF", helper.update, self.path,
                              self.event(self.current(phase="manual_handoff", **changes)))

    def test_current_replacement_moves_old_blocker_to_history(self):
        self.base["blocker"] = "old native error"
        self.base["ui_observation"] = {"blocker": "stale nested blocker"}
        self.write(self.base)
        helper.update(self.path, self.event())
        saved, _ = helper.read_json(self.path)
        self.assertNotIn("blocker", saved)
        self.assertNotIn("ui_observation", saved)
        self.assertNotIn("blocker", saved["controller_state"]["current"])
        self.assertEqual(saved["controller_state"]["history"][0]["blocker"], "old native error")
        first = self.current(blocker="new transient error", recovery_count=1)
        helper.update(self.path, self.event(first, event_id="e2", observed_at=LATER))
        helper.update(self.path, self.event(self.current(recovery_count=1), event_id="e3", observed_at=LATER))
        saved, _ = helper.read_json(self.path)
        self.assertNotIn("blocker", saved["controller_state"]["current"])
        self.assertEqual(saved["controller_state"]["history"][-1]["blocker"], "new transient error")

    def test_string_partial_is_legacy_then_requires_explicit_migration(self):
        self.base["input_access_verified"] = "partial_native_read_log"
        self.write(self.base)
        before = self.path.read_bytes()
        observed = self.inspect()
        self.assertEqual((observed["legacy"], observed["legacy_input_type"], observed["action"]),
                         (True, "str", "MIGRATE_LEGACY"))
        self.assertEqual(self.path.read_bytes(), before)
        event = self.event(self.current(input_access_status="partial"), migrate_legacy=False)
        self.assert_error("EXPLICIT_MIGRATION_REQUIRED", helper.update, self.path, event)
        event["migrate_legacy"] = True
        helper.update(self.path, event)
        saved, _ = helper.read_json(self.path)
        self.assertIs(saved["input_access_verified"], False)
        self.assertEqual(saved["input_access_status"], "partial")

    def test_rejects_string_booleans_and_conflicting_input_status(self):
        for key in helper.BOOLEANS:
            self.assert_error("BOOLEAN_REQUIRED", helper.update, self.path,
                              self.event(self.current(**{key: "false"})))
        self.assert_error("INPUT_STATUS_CONFLICT", helper.update, self.path,
                          self.event(self.current(input_access_verified=True)))

    def test_sent_needs_observed_submission_and_locator(self):
        for changes in ({}, {"submission_observed": True}):
            self.assert_error("SUBMISSION_EVIDENCE_REQUIRED", helper.update, self.path,
                              self.event(self.current(dispatch_state="SENT", **changes)))
        sent = self.current(dispatch_state="SENT", submission_observed=True,
                            conversation_locator="visible-conversation-1", phase="running")
        helper.update(self.path, self.event(sent))
        self.assertEqual(self.inspect()["dispatch_state"], "SENT")
        self.assert_error("DISPATCH_REGRESSION", helper.update, self.path,
                          self.event(self.current(dispatch_state="UNKNOWN"), event_id="e2"))

    def test_ui_conflict_prevents_stopped_generation(self):
        self.assert_error("UI_EVIDENCE_CONFLICT", helper.update, self.path,
                          self.event(self.current(ui_evidence_conflict=True, generation_stopped=True)))
        helper.update(self.path, self.event(self.current(ui_evidence_conflict=True)))
        self.assertEqual(self.inspect()["action"], "RESOLVE_UI_CONFLICT")

    def test_evidence_cannot_cross_adviser_or_session(self):
        good = {"adviser": "opus", "session": str(self.path), "observed_at": NOW, "source": "native AX event 1"}
        for changed in ({"adviser": "gemini"}, {"session": str(self.root / "other.json")}):
            self.assert_error("EVIDENCE_PROVENANCE_MISMATCH", helper.update, self.path,
                              self.event(self.current(evidence=[{**good, **changed}])))
        helper.update(self.path, self.event(self.current(evidence=[good])))

    def test_two_advisers_are_inspected_separately(self):
        helper.update(self.path, self.event(self.current(dispatch_state="UNKNOWN")))
        second = self.root / "gemini.session.json"
        second.write_text(json.dumps({**self.base, "adviser": "gemini", "completion_file": "gemini.completion.json"}))
        event = self.event(self.current(next_check_at=LATER))
        event["expected_sha256"] = helper.read_json(second)[1]
        helper.update(second, event)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = helper.main(["inspect", "--session", str(self.path), "--session", str(second), "--now", NOW])
        rows = json.loads(output.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual([(r["adviser"], r["action"]) for r in rows],
                         [("opus", "RECOVER_SUBMISSION"), ("gemini", "WAIT")])

    def test_due_poll_never_reads_report_or_completion_contents(self):
        sent = self.current(dispatch_state="SENT", submission_observed=True,
                            conversation_locator="native-1", phase="running", next_check_at=LATER)
        helper.update(self.path, self.event(sent))
        (self.root / "opus.report.md").write_text("PRIVATE REPORT")
        (self.root / "opus.completion.json").write_text("not even JSON")
        with mock.patch.object(helper.delivery, "read_file", wraps=helper.delivery.read_file) as reads:
            self.assertEqual(self.inspect()["action"], "WAIT")
            later = helper.inspect(self.path, dt.datetime.fromisoformat(LATER))
        self.assertEqual([call.args[0] for call in reads.call_args_list], [self.path, self.path])
        self.assertEqual(later["action"], "CHECK_UI_THEN_COLLECT")
        self.assertEqual(later["completion_metadata"]["size"], 13)
        self.assertNotIn("PRIVATE", json.dumps(later))

    def test_batch_keeps_healthy_adviser_when_other_session_corrupt(self):
        helper.update(self.path, self.event(self.current(dispatch_state="UNKNOWN")))
        broken = self.root / "gemini.session.json"
        broken.write_text("broken JSON")
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = helper.main(["inspect", "--session", str(broken), "--session", str(self.path), "--now", NOW])
        rows = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(rows[0], {"session": str(broken), "error": "INVALID_JSON"})
        self.assertEqual(rows[1]["action"], "RECOVER_SUBMISSION")

    def test_stale_top_level_mirror_cannot_survive_current_replacement(self):
        helper.update(self.path, self.event())
        saved, _ = helper.read_json(self.path)
        saved["ui_evidence_conflict"] = True
        self.write(saved)
        self.assert_error("MIRROR_MISMATCH", self.inspect)

    def test_cas_mismatch_preserves_concurrent_writer_bytes(self):
        event = self.event()
        self.write({**self.base, "blocker": "new writer"})
        before = self.path.read_bytes()
        self.assert_error("CAS_MISMATCH", helper.update, self.path, event)
        self.assertEqual(before, self.path.read_bytes())
        self.assertFalse(self.path.with_name(self.path.name + ".lock").exists())

    def test_late_cas_mismatch_does_not_replace_other_writer(self):
        event = self.event()
        original = helper.read_json
        counter = 0
        def concurrent_read(path):
            nonlocal counter
            counter += 1
            if counter == 2:
                self.write({**self.base, "blocker": "late writer"})
            return original(path)
        with mock.patch.object(helper, "read_json", side_effect=concurrent_read):
            self.assert_error("CAS_MISMATCH", helper.update, self.path, event)
        self.assertEqual(helper.read_json(self.path)[0]["blocker"], "late writer")
        self.assertEqual(list(self.root.glob(".opus.session.json.*")), [])

    def test_atomic_replace_failure_preserves_original(self):
        before = self.path.read_bytes()
        with mock.patch.object(helper.os, "replace", side_effect=OSError("simulated disk failure")):
            with self.assertRaises(OSError):
                helper.update(self.path, self.event())
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.root.glob(".opus.session.json.*")), [])
        self.assertFalse(self.path.with_name(self.path.name + ".lock").exists())

    def test_exclusive_lock_never_overwrites_another_owner(self):
        lock = self.path.with_name(self.path.name + ".lock")
        lock.write_text("owner")
        self.assert_error("SESSION_LOCKED", helper.update, self.path, self.event())
        self.assertEqual(lock.read_text(), "owner")

    def test_relative_alias_symlink_hardlink_and_nonfile_refused(self):
        self.assert_error("ABSOLUTE_PATH_REQUIRED", helper.path_arg, "local.json")
        self.assert_error("CANONICAL_PATH_REQUIRED", helper.path_arg, str(self.root) + "/./opus.session.json")
        link = self.root / "link.json"
        link.symlink_to(self.path)
        self.assert_error("LINK_OR_REPARSE_REFUSED", helper.path_arg, str(link))
        hardlink = self.root / "hardlink.json"
        os.link(self.path, hardlink)
        self.assert_error("HARDLINK_REFUSED", helper.read_json, hardlink)
        self.assert_error("NON_FILE_REFUSED", helper.read_json, self.root)

    def test_history_bounded_and_mirrors_collector_compatible(self):
        helper.update(self.path, self.event())
        for index in range(30):
            helper.update(self.path, self.event(event_id="next" + str(index), observed_at=LATER))
        saved, _ = helper.read_json(self.path)
        self.assertEqual(len(saved["controller_state"]["history"]), 25)
        self.assertEqual(saved["schema_version"], 2)
        self.assertEqual(helper.delivery.delivery_names(saved)["report"], "opus.report.md")
        saved["generation_stopped"] = True
        self.write(saved)
        self.assert_error("MIRROR_MISMATCH", self.inspect)

    def test_invalid_completion_path_never_read(self):
        self.base["completion_file"] = "../private.json"
        self.write(self.base)
        self.assert_error("INVALID_DELIVERABLE_NAME", self.inspect)

    def test_duplicate_json_and_nonfinite_json_rejected(self):
        for text in ('{"adviser":"opus","adviser":"gemini"}', '{"number":NaN}'):
            self.path.write_text(text)
            with self.assertRaises(helper.delivery.DeliveryError):
                helper.read_json(self.path)

    def test_update_cli_never_prints_private_evidence(self):
        evidence = [{"adviser": "opus", "session": str(self.path), "observed_at": NOW, "source": "PRIVATE NATIVE CONTENT"}]
        event_file = self.root / "event.json"
        event_file.write_text(json.dumps(self.event(self.current(evidence=evidence))))
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = helper.main(["update", "--session", str(self.path), "--event-file", str(event_file)])
        self.assertEqual(code, 0)
        self.assertNotIn("PRIVATE", output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["phase"], "preparing")


if __name__ == "__main__":
    unittest.main()
