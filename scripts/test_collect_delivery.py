"""Failure-oriented local tests; no application or external-model claim."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import collect_delivery as collector


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temporary.cleanup)
        # macOS may expose its system temp directory through /var -> /private/var.
        # Canonicalize this controller-created fixture before constructing paths;
        # actual untrusted delivery links must still be rejected by the collector.
        self.root = Path(self.temporary.name).resolve()
        self.output = self.root / "adviser"
        self.output.mkdir()
        self.session_file = self.root / "session.json"
        self.snapshot = self.root / "frozen"
        self.session = {
            "schema_version": 1, "request_id": "REQ-TEST-001", "adviser": "opus",
            "input_manifest_sha256": "a" * 64, "output_directory": str(self.output),
            "sentinel": "END-REQ-TEST-001", "dispatch_state": "SENT",
            "generation_stopped": True, "unresolved_approval": False,
        }
        self.completion = {
            "schema_version": 1, "request_id": self.session["request_id"], "adviser": "opus",
            "input_manifest_sha256": "a" * 64, "status": "complete",
            "report_file": "report.md", "findings_file": "findings.json",
        }
        self.findings = {
            "schema_version": 1, "request_id": self.session["request_id"], "adviser": "opus",
            "input_manifest_sha256": "a" * 64, "recommendation": "Inspect the stated behavior.",
            "findings": [], "evidence_read": [], "unknowns": ["Runtime behavior untested."],
        }
        self.report = b"# REQ-TEST-001\nA complete adviser report.\nEND-REQ-TEST-001\n"
        self.write_json(self.session_file, self.session)
        self.write_json(self.output / "completion.json", self.completion)
        self.write_json(self.output / "findings.json", self.findings)
        (self.output / "report.md").write_bytes(self.report)

    def write_json(self, path, data):
        path.write_text(json.dumps(data), encoding="utf-8")

    def collect(self):
        return collector.collect(self.session_file, self.snapshot, stable_seconds=0)

    def failure(self, code=None):
        with self.assertRaises(collector.DeliveryError) as caught:
            self.collect()
        if code:
            self.assertEqual(caught.exception.code, code)
        self.assertFalse(self.snapshot.exists())

    def test_freezes_exact_bytes_and_locally_hashes_all_files(self):
        result = self.collect()
        self.assertEqual(result["snapshot_action"], "CREATED")
        self.assertEqual((self.snapshot / "report.md").read_bytes(), self.report)
        receipt = json.loads((self.snapshot / "receipt.json").read_bytes())
        self.assertEqual(receipt["evidence_status"], "adviser_claims_unverified")
        for name, details in receipt["files"].items():
            source = (self.output / name).read_bytes()
            self.assertEqual(details["sha256"], collector.hashlib.sha256(source).hexdigest())
            self.assertEqual(details["bytes"], len(source))

    def test_identical_repeat_is_idempotent_without_rewriting_receipt(self):
        self.collect()
        initial = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.snapshot.iterdir()}
        self.assertEqual(self.collect()["snapshot_action"], "RECOVERED_IDENTICAL")
        self.assertEqual(initial, {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
                                   for p in self.snapshot.iterdir()})

    def test_revised_answer_cannot_overwrite_original(self):
        self.collect()
        original = {p.name: p.read_bytes() for p in self.snapshot.iterdir()}
        (self.output / "report.md").write_bytes(self.report.replace(b"complete", b"revised"))
        with self.assertRaises(collector.DeliveryError) as caught:
            self.collect()
        self.assertEqual(caught.exception.code, "SNAPSHOT_CONFLICT")
        self.assertEqual(original, {p.name: p.read_bytes() for p in self.snapshot.iterdir()})

    def test_partial_snapshot_remains_explicit_and_untouched(self):
        self.snapshot.mkdir()
        (self.snapshot / "report.md").write_bytes(b"interrupted")
        with self.assertRaises(collector.DeliveryError) as caught:
            self.collect()
        self.assertEqual(caught.exception.code, "PARTIAL_SNAPSHOT")
        self.assertEqual(list(self.snapshot.iterdir()), [self.snapshot / "report.md"])
        self.assertEqual((self.snapshot / "report.md").read_bytes(), b"interrupted")

    def test_old_request_cross_adviser_and_digest_mismatch(self):
        for field, value in (("request_id", "OLD-REQUEST"), ("adviser", "gemini"),
                             ("input_manifest_sha256", "b" * 64)):
            with self.subTest(field=field):
                invalid = {**self.completion, field: value}
                self.write_json(self.output / "completion.json", invalid)
                self.failure("IDENTITY_MISMATCH")

    def test_findings_identity_must_match_independently(self):
        self.findings["adviser"] = "gemini"
        self.write_json(self.output / "findings.json", self.findings)
        self.failure("IDENTITY_MISMATCH")

    def test_completion_without_report_is_not_success(self):
        (self.output / "report.md").unlink()
        self.failure("MISSING_DELIVERABLE")

    def test_invalid_json_duplicate_keys_and_nonstandard_constants(self):
        for data, code in ((b'{"broken":', "INVALID_JSON"),
                           (b'{"request_id":"a","request_id":"b"}', "DUPLICATE_JSON_KEY"),
                           (b'{"value":NaN}', "INVALID_JSON"),
                           (b'\xff', "INVALID_UTF8")):
            with self.subTest(data=data):
                (self.output / "completion.json").write_bytes(data)
                self.failure(code)

    def test_nested_duplicate_key_is_not_accepted(self):
        (self.output / "findings.json").write_bytes(b'{"findings":[{"id":"a","id":"b"}]}')
        self.failure("DUPLICATE_JSON_KEY")

    def test_dispatch_generation_and_approval_gates(self):
        for field, value, code in (("dispatch_state", "UNKNOWN", "NOT_SENT"),
                                   ("generation_stopped", False, "GENERATION_NOT_STOPPED"),
                                   ("unresolved_approval", True, "UNRESOLVED_APPROVAL")):
            with self.subTest(field=field):
                self.write_json(self.session_file, {**self.session, field: value})
                self.failure(code)

    def test_bytes_changed_during_stability_are_not_frozen(self):
        def revise(_):
            (self.output / "report.md").write_bytes(self.report.replace(b"complete", b"modified"))
        with mock.patch.object(collector.time, "sleep", side_effect=revise):
            self.failure("DELIVERY_CHANGED_DURING_STABILITY")

    def test_file_set_changed_during_stability_is_rejected(self):
        def revise(_):
            (self.output / "findings.json").unlink()
        with mock.patch.object(collector.time, "sleep", side_effect=revise):
            self.failure("DELIVERY_CHANGED_DURING_STABILITY")

    def test_file_mutated_while_descriptor_is_open_is_rejected(self):
        original_read = collector.os.read
        changed = False
        def mutate(fd, size):
            nonlocal changed
            data = original_read(fd, size)
            if not changed and b"A complete adviser report" in data:
                changed = True
                (self.output / "report.md").write_bytes(self.report + b"unfinished")
            return data
        with mock.patch.object(collector.os, "read", side_effect=mutate):
            self.failure("FILE_CHANGED")

    def test_changed_controller_state_during_stability_is_rejected(self):
        def revise(_):
            self.write_json(self.session_file, {**self.session, "generation_stopped": False})
        with mock.patch.object(collector.time, "sleep", side_effect=revise):
            self.failure("SESSION_CHANGED")

    def test_path_injection_cannot_choose_a_source_file(self):
        for name in ("../outside.md", "C:\\private\\source.md", "report.md:secret", "nested/report.md"):
            with self.subTest(name=name):
                self.write_json(self.output / "completion.json", {**self.completion, "report_file": name})
                self.failure("INVALID_DELIVERABLE_NAME")

    def test_unexpected_file_and_directory_are_not_recursively_collected(self):
        (self.output / "extra.txt").write_bytes(b"unexpected")
        self.failure("UNEXPECTED_FILE_SET")
        (self.output / "extra.txt").unlink()
        (self.output / "nested").mkdir()
        self.failure("UNEXPECTED_FILE_SET")

    def test_hardlinked_deliverable_is_refused(self):
        outside = self.root / "outside.md"
        outside.write_bytes(self.report)
        (self.output / "report.md").unlink()
        os.link(outside, self.output / "report.md")
        self.failure("HARDLINK_REFUSED")

    def test_symlink_deliverable_is_refused_when_creation_supported(self):
        outside = self.root / "outside.md"
        outside.write_bytes(self.report)
        (self.output / "report.md").unlink()
        try:
            (self.output / "report.md").symlink_to(outside)
        except OSError:
            self.skipTest("Host does not permit symlink creation")
        self.failure("LINK_OR_REPARSE_REFUSED")

    def test_oversize_report_is_refused(self):
        (self.output / "report.md").write_bytes(b"x" * (collector.MAX_BYTES + 1))
        self.failure("OVERSIZE_FILE")

    def test_request_marker_final_sentinel_and_utf8_are_required(self):
        for data, code in ((b"wrong request\nEND-OTHER\n", "REPORT_REQUEST_MISSING"),
                           (self.report + b"unfinished", "REPORT_SENTINEL_MISSING"),
                           (self.report.rstrip(b"\n") + b" \n\n", "REPORT_SENTINEL_MISSING"),
                           (self.report + b" \n", "REPORT_SENTINEL_MISSING"),
                           (self.report + b"\xff", "INVALID_UTF8")):
            with self.subTest(code=code):
                (self.output / "report.md").write_bytes(data)
                self.failure(code)

    def test_two_trailing_empty_lines_preserve_exact_sentinel(self):
        data = self.report + b"\n\n"
        (self.output / "report.md").write_bytes(data)
        self.assertEqual(self.collect()["status"], "PASS")
        self.assertEqual((self.snapshot / "report.md").read_bytes(), data)

    def test_evidence_and_unknown_members_must_be_strings(self):
        for field in ("evidence_read", "unknowns"):
            for member in ({"claim": "Not a string"}, 17, None, True, ["nested"]):
                with self.subTest(field=field, member=member):
                    self.write_json(self.output / "findings.json", {**self.findings, field: [member]})
                    self.failure("INVALID_FINDINGS_SCHEMA")

    def test_report_only_delivery_is_valid(self):
        self.completion["findings_file"] = None
        self.write_json(self.output / "completion.json", self.completion)
        (self.output / "findings.json").unlink()
        self.assertEqual(self.collect()["file_count"], 2)

    def test_adviser_cannot_drop_controller_required_findings(self):
        self.write_json(self.session_file, {**self.session, "findings_required": True})
        self.completion["findings_file"] = None
        self.write_json(self.output / "completion.json", self.completion)
        (self.output / "findings.json").unlink()
        self.failure("REQUIRED_FINDINGS_MISSING")

    def test_findings_requirement_is_a_boolean(self):
        self.write_json(self.session_file, {**self.session, "findings_required": "false"})
        self.failure("INVALID_SESSION_SCHEMA")

    def test_noncode_findings_need_no_fabricated_location(self):
        self.findings["findings"] = [{
            "id": "F1", "severity": "medium", "claim": "Scope is ambiguous.",
            "file": None, "line": None, "trigger": "Request omits audience.",
            "evidence_kind": "adviser_inference", "counterevidence": "",
            "suggested_check": "Inspect the intended audience.",
        }]
        self.write_json(self.output / "findings.json", self.findings)
        self.assertEqual(self.collect()["status"], "PASS")

    def test_findings_malformed_locations_and_duplicate_ids_are_rejected(self):
        base = {"id": "F1", "severity": "high", "claim": "Candidate bug", "file": "app.py",
                "line": 1, "trigger": "Empty input", "evidence_kind": "adviser_claim",
                "counterevidence": "Untested", "suggested_check": "Run targeted test"}
        for finding in ({**base, "line": True}, {**base, "line": -1}, {**base, "file": None},
                        {**base, "severity": "verified"}):
            with self.subTest(finding=finding):
                self.write_json(self.output / "findings.json", {**self.findings, "findings": [finding]})
                self.failure("INVALID_FINDING_SCHEMA")
        self.write_json(self.output / "findings.json", {**self.findings, "findings": [base, base]})
        self.failure("DUPLICATE_FINDING_ID")

    def test_session_and_snapshot_must_stay_outside_adviser_output(self):
        self.session_file = self.output / "session.json"
        self.write_json(self.session_file, self.session)
        self.failure("SESSION_INSIDE_ADVISER_OUTPUT")
        self.session_file.unlink()
        self.session_file = self.root / "session.json"
        self.snapshot = self.output / "frozen"
        self.failure("SNAPSHOT_OVERLAPS_ADVISER_OUTPUT")

    def test_windows_trailing_dot_and_space_alias_cannot_bypass_overlap(self):
        for suffix in (".", " ", ". "):
            with self.subTest(suffix=suffix):
                self.snapshot = Path(str(self.output) + suffix) / "frozen"
                self.failure("AMBIGUOUS_WINDOWS_PATH")
                self.assertFalse((self.output / "frozen").exists())

    def test_bound_stability_interval(self):
        for seconds in (-1, 10.1, float("nan"), float("inf"), True):
            with self.subTest(seconds=seconds), self.assertRaises(collector.DeliveryError) as caught:
                collector.collect(self.session_file, self.snapshot, seconds)
            self.assertEqual(caught.exception.code, "INVALID_STABILITY_INTERVAL")

    def test_cli_failure_does_not_echo_sensitive_content(self):
        (self.output / "completion.json").write_bytes(b"CONFIDENTIAL_INVALID_PAYLOAD")
        with mock.patch("sys.stdout") as stdout:
            result = collector.main(["--session", str(self.session_file), "--snapshot-dir",
                                     str(self.snapshot), "--stable-seconds", "0"])
        self.assertEqual(result, 2)
        emitted = "".join(call.args[0] for call in stdout.write.call_args_list)
        self.assertNotIn("CONFIDENTIAL", emitted)
        self.assertEqual(json.loads(emitted)["code"], "INVALID_JSON")


if __name__ == "__main__":
    unittest.main()
