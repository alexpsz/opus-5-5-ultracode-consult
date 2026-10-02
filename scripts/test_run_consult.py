import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import hashlib
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent
if SCRIPTS.name == "tests":
    SCRIPTS = SCRIPTS.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import run_consult as runner


# Sanitized replay of the Claude Code 2.1.286 authentication-failure shape.
# All identifiers and timestamps are synthetic; private source locators are excluded.
OPUS_AUTH_ERROR_SANITIZED_REPLAY = json.loads('[{"type": "system", "subtype": "init", "model": "claude-opus-5-5", "session_id": "33333333-3333-4333-8333-333333333333"}, {"type": "assistant", "message": {"diagnostics": null, "id": "44444444-4444-4444-8444-444444444444", "container": null, "model": "<synthetic>", "role": "assistant", "stop_details": null, "stop_reason": "stop_sequence", "stop_sequence": "", "type": "message", "usage": {"output_tokens_details": null, "input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "server_tool_use": {"web_search_requests": 0, "web_fetch_requests": 0}, "service_tier": null, "cache_creation": {"ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": 0}, "inference_geo": null, "iterations": null, "speed": null, "fallback_credit": null}, "content": [{"type": "text", "text": "Not logged in · Please run /login"}], "context_management": null}, "parent_tool_use_id": null, "session_id": "33333333-3333-4333-8333-333333333333", "uuid": "55555555-5555-4555-8555-555555555555", "timestamp": "2000-01-01T00:00:00.000Z", "error": "authentication_failed", "is_api_error_message": true}, {"duration_api_ms": 0, "stop_reason": "stop_sequence", "session_id": "33333333-3333-4333-8333-333333333333", "total_cost_usd": 0, "usage": {"output_tokens_details": {"thinking_tokens": 0}, "input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 0, "server_tool_use": {"web_search_requests": 0, "web_fetch_requests": 0}, "service_tier": "standard", "cache_creation": {"ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": 0}, "inference_geo": "", "iterations": [], "speed": "standard", "fallback_credit": null}, "modelUsage": {}, "permission_denials": [], "terminal_reason": "api_error", "fast_mode_state": "off", "fast_mode_disabled_reason": "sdk_opt_in_required", "subagent_stats": {"spawned": 0, "requested": {"background": 0, "foreground": 0, "unset": 0}, "started_in_background": 0, "max_depth": 0, "spawned_by_subagents": 0, "completed": 0, "failed": 0, "killed": {"parent": 0, "user": 0, "system": 0}, "refused": {"depth_limit": 0, "concurrency_limit": 0, "budget": 0}, "by_type": {}}, "is_error": true, "num_turns": 1, "subtype": "success", "api_error_status": null, "result": "Not logged in · Please run /login", "type": "result", "duration_ms": 146, "uuid": "66666666-6666-4666-8666-666666666666", "queued_turn_count": 0, "result_index": 0}]')


def opus_events(answer="Review complete.\nEND_TEST\n", **final_changes):
    final = {"type": "result", "subtype": "success", "is_error": False,
             "result": answer, "session_id": "native-session", "permission_denials": []}
    final.update(final_changes)
    return [{"type": "system", "subtype": "init", "model": "claude-opus-5-5",
             "session_id": "native-session", "skills": ["normal-configured-skill"]},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Partial"}]}}, final]


def gemini_events(answer="Review complete.\nEND_TEST\n", **final_changes):
    final = {"conversation_id": "native-conversation", "status": "SUCCESS", "response": answer}
    final.update(final_changes)
    return [{"event": "init", "conversation_id": "native-conversation",
             "init": {"model": "gemini-3.8-flash-high", "permission_mode": "request-review"}},
            {"event": "step_update", "step_update": {"conversation_id": "native-conversation",
             "step_type": "user_input", "state": "DONE", "step_index": 0}},
            {"event": "step_update", "step_update": {"step_type": "agent_response",
             "state": "DONE", "text_delta": "Partial draft; not final response"}},
            {"event": "result", "result": final}]


class RunConsultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.prompt = self.root / "prompt.txt"
        self.prompt.write_bytes(b"PRIVATE SYNTHETIC QUESTION\n")
        self.executable = self.root / "fixture-cli.exe"
        self.args = argparse.Namespace(adviser="opus", executable=str(self.executable),
            project_root=str(self.root), prompt_file=str(self.prompt), run_dir=str(self.root / "request.opus"),
            request_id="request", model=None, effort=None, sentinel="END_TEST", timeout_seconds=2,
            continue_from=None, input_manifest=None, runtime_profile=None)
        self.profile_check = mock.patch.object(runner.runtime_profile, "check_profile", return_value={
            "ok": True, "error_code": None, "path": str(self.root / "fixture-profile.json"),
            "sha256": "0" * 64, "environment": {}}).start()
        self.profile_environment = mock.patch.object(runner.runtime_profile, "child_environment",
                                                     side_effect=lambda profile: dict(os.environ)).start()
        self.preflight_check = mock.patch.object(runner.preflight, "check_run", return_value={"ok": True}).start()
        self.preflight_cache = mock.patch.object(runner.preflight, "record_outcome", return_value={"status": "fixture"}).start()
        self.preflight_classify = mock.patch.object(runner.preflight, "classify_failure", return_value=None).start()
        # Fixture scripts are test data, not native Windows executables. Launch
        # them using the real Python interpreter while leaving production argv,
        # shell=False, stream IO and the actual child process lifecycle intact.
        real_popen = runner.subprocess.Popen
        def spawn_fixture(argv, **kwargs):
            if Path(argv[0]).resolve() == self.executable:
                return real_popen([sys.executable, "-X", "utf8", *argv], **kwargs)
            return real_popen(argv, **kwargs)
        self.fixture_process = mock.patch.object(runner.subprocess, "Popen", side_effect=spawn_fixture).start()
        self.addCleanup(mock.patch.stopall)
        self.fixture(opus_events())

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self, events, exit_code=0, pause=0, stderr="", raw_tail=""):
        lines = "\n".join(json.dumps(e) for e in events) + ("\n" if events else "") + raw_tail
        source = ("#!" + sys.executable + "\nimport json, pathlib, sys, time\n"
                  "state=json.loads(pathlib.Path(" + repr(str(Path(self.args.run_dir) / "run.json")) + ").read_text())\n"
                  "assert state['dispatch_state']=='UNKNOWN'\n"
                  "pathlib.Path(" + repr(str(self.root / "received-argv.json")) + ").write_text(json.dumps(sys.argv))\n"
                  "incoming=sys.stdin.read()\n"
                  "if '--input-format' in sys.argv:\n"
                  " assert json.loads(incoming)=={'event':'user','message':{'content':'PRIVATE SYNTHETIC QUESTION\\n'}}\n"
                  "else:\n assert incoming == 'PRIVATE SYNTHETIC QUESTION\\n'\n"
                  "sys.stdout.write(" + repr(lines) + "); sys.stdout.flush()\n"
                  "sys.stderr.write(" + repr(stderr) + "); sys.stderr.flush()\n"
                  "time.sleep(" + repr(pause) + ")\nsys.exit(" + str(exit_code) + ")\n")
        self.executable.write_text(source, encoding="utf-8")
        self.executable.chmod(0o700)

    def receipt(self):
        return json.loads((Path(self.args.run_dir) / "run.json").read_text())

    def wait_receipt(self, predicate):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            try:
                current = self.receipt()
                if predicate(current):
                    return current
            except FileNotFoundError:
                pass
            time.sleep(0.03)
        self.fail("Expected live receipt state was not observed")

    def native_events(self, adviser, session):
        events = opus_events() if adviser == "opus" else gemini_events()
        original = "native-session" if adviser == "opus" else "native-conversation"
        return json.loads(json.dumps(events).replace(original, session))

    def make_parent(self, adviser="opus", denied=False):
        self.args.adviser = adviser
        session = "77777777-7777-4777-8777-777777777777"
        events = self.native_events(adviser, session)
        if denied:
            if adviser == "opus":
                events[-1]["permission_denials"] = [{"tool_name": "Read"}]
            else:
                events[-1]["result"]["denied_actions"] = [{"tool": "view_file"}]
        self.fixture(events)
        runner.run(self.args)
        parent = Path(self.args.run_dir) / "run.json"
        self.args.continue_from = str(parent)
        self.args.run_dir = str(self.root / "followup")
        self.args.request_id = "request-followup"
        return parent, session

    def test_live_receipt_waits_for_complete_line_and_updates_before_exit(self):
        self.args.timeout_seconds = 6
        events = opus_events()
        assistant = json.dumps(events[1]).encode()
        partial = len(assistant) // 2
        tool = {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "read-id", "name": "Read", "input": {"file_path": "fixture"}}]}}
        chunks = [(json.dumps(events[0]).encode() + b"\n" + assistant[:partial], 1.3),
                  (assistant[partial:] + b"\n" + json.dumps(tool).encode() + b"\n", 1.3),
                  (json.dumps(events[-1]).encode() + b"\n", 0)]
        source = "#!" + sys.executable + "\nimport sys,time\nsys.stdin.read()\n"
        for chunk, delay in chunks:
            source += "sys.stdout.buffer.write(" + repr(chunk) + ");sys.stdout.flush()\ntime.sleep(" + repr(delay) + ")\n"
        self.executable.write_text(source, encoding="utf-8")
        outcome = []
        def execute():
            try:
                outcome.append(runner.run(self.args))
            except BaseException as error:
                outcome.append(error)
        worker = threading.Thread(target=execute)
        worker.start()
        try:
            initial = self.wait_receipt(lambda r: r.get("event_count") == 1)
            self.assertEqual(initial["dispatch_state"], "UNKNOWN")
            self.assertEqual(initial["phase"], "READY")
            self.assertFalse(initial["submission_observed"])
            self.assertEqual(initial["session_ids"], ["native-session"])
            self.assertEqual(initial["observed_models"], ["claude-opus-5-5"])
            self.assertFalse((Path(self.args.run_dir) / "stdout.raw").read_bytes().endswith(b"\n"))
            active = self.wait_receipt(lambda r: r.get("last_tool", {}).get("name") == "Read")
            self.assertEqual((active["phase"], active["dispatch_state"], active["process_status"]),
                             ("GENERATING", "SENT", "RUNNING"))
            self.assertEqual(active["answer_capture_status"], "NOT_CAPTURED")
            self.assertIsNotNone(active["last_event_at"])
        finally:
            worker.join(timeout=8)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(outcome), 1)
        self.assertIsInstance(outcome[0], dict)
        self.assertEqual(outcome[0]["delivery_status"], "COMPLETE")
        saved = self.receipt()
        self.assertEqual([p["phase"] for p in saved["phase_history"]],
                         ["READY", "SENT", "GENERATING", "DELIVERED"])
        self.assertEqual(saved["answer_capture_status"], "CAPTURED")
        self.assertEqual(saved["acceptance_status"], "PENDING_CONTROLLER_REVIEW")
        self.assertGreater(saved["phase_durations_seconds"]["GENERATING"], 0)

    def test_provenance_and_timeout_are_frozen_with_receipt(self):
        runner.run(self.args)
        saved = self.receipt()
        self.assertEqual(saved["runner_sha256"], hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest())
        self.assertEqual(saved["skill_sha256"], hashlib.sha256((SCRIPTS.parent / "SKILL.md").read_bytes()).hexdigest())
        self.assertEqual(saved["timeout_seconds"], self.args.timeout_seconds)
        self.assertTrue(saved["independent_review"])
        self.assertIsNone(saved["continuation_of"])

    def test_gemini_live_user_ack_then_generation_and_tool_are_distinct(self):
        self.args.adviser = "gemini"
        self.args.timeout_seconds = 8
        events = gemini_events()
        tool = {"event": "step_update", "step_update": {"step_type": "tool", "state": "ACTIVE",
                "step_index": 2, "tool_info": {"tool_name": "view_file"}}}
        chunks = [([events[0]], 1.1), ([events[1]], 1.1), ([events[2], tool], 1.1), ([events[-1]], 0)]
        source = "#!" + sys.executable + "\nimport sys,time\nsys.stdin.read()\n"
        for group, delay in chunks:
            data = "".join(json.dumps(event) + "\n" for event in group)
            source += "sys.stdout.write(" + repr(data) + ");sys.stdout.flush()\ntime.sleep(" + repr(delay) + ")\n"
        self.executable.write_text(source, encoding="utf-8")
        outcome = []
        worker = threading.Thread(target=lambda: outcome.append(runner.run(self.args)))
        worker.start()
        try:
            initial = self.wait_receipt(lambda r: r.get("event_count") == 1)
            self.assertEqual(initial["dispatch_state"], "UNKNOWN")
            acknowledged = self.wait_receipt(lambda r: r.get("phase") == "SENT")
            self.assertEqual(acknowledged["process_status"], "RUNNING")
            active = self.wait_receipt(lambda r: r.get("last_tool", {}).get("name") == "view_file")
            self.assertEqual(active["phase"], "GENERATING")
            self.assertEqual(active["session_ids"], ["native-conversation"])
            self.assertEqual(active["observed_models"], ["gemini-3.8-flash-high"])
        finally:
            worker.join(timeout=10)
        self.assertFalse(worker.is_alive())
        self.assertEqual(outcome[0]["delivery_status"], "COMPLETE")

    def test_truncated_final_line_keeps_sent_but_fails_final_collection(self):
        self.fixture(opus_events()[:-1], raw_tail='{"type":"result",')
        result = runner.run(self.args)
        self.assertEqual((result["dispatch_state"], result["delivery_status"]), ("SENT", "INCOMPLETE"))
        self.assertEqual(result["phase"], "FAILED")
        self.assertEqual(result["answer_capture_status"], "NOT_CAPTURED")
        self.assertFalse((Path(self.args.run_dir) / "answer.md").exists())

    def test_explicit_followup_resumes_same_native_session_and_preserves_parent(self):
        for adviser, flag in (("opus", "--resume"), ("gemini", "--conversation")):
            with self.subTest(adviser=adviser):
                self.args.continue_from = None
                self.args.run_dir = str(self.root / (adviser + ".parent"))
                self.args.request_id = adviser + "-request"
                parent, session = self.make_parent(adviser, denied=True)
                self.args.run_dir = str(self.root / (adviser + ".followup"))
                before = parent.read_bytes()
                self.fixture(self.native_events(adviser, session))
                result = runner.run(self.args)
                saved = self.receipt()
                self.assertEqual(result["delivery_status"], "COMPLETE")
                self.assertFalse(saved["independent_review"])
                self.assertEqual(saved["continuation_of"]["receipt_sha256"], hashlib.sha256(before).hexdigest())
                self.assertEqual(saved["continuation_of"]["request_id"], adviser + "-request")
                self.assertEqual(saved["argv"][saved["argv"].index(flag) + 1], session)
                self.assertEqual(json.loads((self.root / "received-argv.json").read_text()), saved["argv"])
                self.assertEqual(parent.read_bytes(), before)
                if adviser == "opus":
                    self.assertIn("WebSearch", saved["argv"])
                    self.assertIn("WebFetch", saved["argv"])
                for forbidden in ("--tools", "--bare", "--dangerously-skip-permissions"):
                    self.assertNotIn(forbidden, saved["argv"])

    def test_followup_rejects_running_mismatched_or_unidentified_parent_without_spawn(self):
        parent, _ = self.make_parent()
        original = json.loads(parent.read_text())
        cases = [("process_status", "RUNNING"), ("adviser", "gemini"),
                 ("project_root", "/another/project"), ("requested_model", "wrong-model"),
                 ("target_verification", "MISMATCH"), ("dispatch_state", "UNKNOWN"),
                 ("native_final_observed", False), ("session_ids", ["not-a-uuid"]),
                 ("session_ids", original["session_ids"] * 2), ("request_id", self.args.request_id)]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                parent.write_text(json.dumps({**original, key: value}))
                with mock.patch.object(runner.subprocess, "Popen") as popen:
                    with self.assertRaises(runner.delivery.DeliveryError):
                        runner.run(self.args)
                    popen.assert_not_called()
                self.assertFalse(Path(self.args.run_dir).exists())

    def test_followup_native_session_mismatch_is_not_success(self):
        self.make_parent()
        self.fixture(opus_events())
        self.assertEqual(runner.run(self.args)["delivery_status"], "INCOMPLETE")
        self.assertEqual(self.receipt()["error_code"], "CONTINUATION_SESSION_MISMATCH")
        self.assertEqual(self.receipt()["phase"], "FAILED")

    def test_preflight_failure_creates_not_sent_receipt_without_spawn(self):
        self.preflight_check.return_value = {"ok": False, "error_code": "WEB_PERMISSION_REQUIRED"}
        with mock.patch.object(runner.subprocess, "Popen") as popen:
            result = runner.run(self.args)
        popen.assert_not_called()
        self.assertEqual((result["dispatch_state"], result["phase"]), ("NOT_SENT", "FAILED"))
        self.assertEqual(self.receipt()["preflight"]["error_code"], "WEB_PERMISSION_REQUIRED")
        self.assertFalse((Path(self.args.run_dir) / "stdout.raw").exists())

    def test_runtime_profile_failure_is_not_sent_and_skips_other_preflight(self):
        self.profile_check.return_value = {"ok": False, "error_code": "ENV_PROFILE_CONFLICT",
            "path": str(self.root / "runtime.json"), "conflict_variables": ["ANTHROPIC_API_KEY"]}
        with mock.patch.object(runner.subprocess, "Popen") as popen:
            result = runner.run(self.args)
        popen.assert_not_called()
        self.preflight_check.assert_not_called()
        self.assertEqual((result["phase"], result["dispatch_state"]), ("FAILED", "NOT_SENT"))
        self.assertEqual(result["error_code"], "ENV_PROFILE_CONFLICT")
        self.assertEqual(self.receipt()["runtime_profile"]["conflict_variables"], ["ANTHROPIC_API_KEY"])

    def test_profile_fingerprint_is_part_of_capability_cache_key(self):
        old_key = "a" * 64
        self.preflight_check.return_value = {"ok": True, "cache_key": old_key, "cache": {"status": "HIT"}}
        with mock.patch.object(runner.preflight, "read_cache", return_value={"status": "MISS"}) as cache:
            runner.run(self.args)
        expected = hashlib.sha256((old_key + ":" + "0" * 64).encode()).hexdigest()
        cache.assert_called_once_with(expected)
        self.assertEqual(self.receipt()["preflight"]["cache_key"], expected)
        self.assertEqual(self.receipt()["preflight"]["cache"]["status"], "MISS")

    def test_followup_profile_drift_is_not_sent_but_legacy_parent_is_supported(self):
        parent, session = self.make_parent()
        self.profile_check.return_value = {**self.profile_check.return_value, "sha256": "1" * 64}
        with mock.patch.object(runner.subprocess, "Popen") as popen:
            result = runner.run(self.args)
        popen.assert_not_called()
        self.assertEqual(result["error_code"], "PARENT_RUNTIME_PROFILE_MISMATCH")
        self.assertEqual(result["dispatch_state"], "NOT_SENT")
        legacy = json.loads(parent.read_text())
        del legacy["runtime_profile"]
        parent.write_text(json.dumps(legacy))
        self.args.run_dir = str(self.root / "legacy-followup")
        self.args.request_id = "legacy-followup"
        self.fixture(self.native_events("opus", session))
        self.assertEqual(runner.run(self.args)["delivery_status"], "COMPLETE")

    def test_fixed_environment_is_passed_to_real_fixture_process_without_losing_harness(self):
        child = dict(os.environ) | {"PATH": "/usr/bin:/bin", "NORMAL_MCP_FIXTURE": "preserved",
                                   "CLAUDE_CONFIG_DIR": "fixture-config"}
        self.profile_environment.side_effect = None
        self.profile_environment.return_value = child
        source = self.executable.read_text(encoding="utf-8")
        source = source.replace("incoming=sys.stdin.read()", "import os\nassert os.environ['PATH']=='/usr/bin:/bin'\n"
            "assert os.environ['NORMAL_MCP_FIXTURE']=='preserved'\nassert os.environ['CLAUDE_CONFIG_DIR']=='fixture-config'\n"
            "incoming=sys.stdin.read()")
        self.executable.write_text(source, encoding="utf-8")
        self.assertEqual(runner.run(self.args)["delivery_status"], "COMPLETE")

    def test_sanitized_claude_auth_failure_is_unknown_not_a_model_response(self):
        self.fixture(OPUS_AUTH_ERROR_SANITIZED_REPLAY, exit_code=1)
        result = runner.run(self.args)
        saved = self.receipt()
        self.assertEqual((result["dispatch_state"], result["process_status"], result["delivery_status"]),
                         ("UNKNOWN", "ERROR", "INCOMPLETE"))
        self.assertEqual(result["phase"], "WAITING_FOR_AUTH")
        self.assertEqual(saved["failure_classification"], "AUTH_REQUIRED")
        self.assertTrue(saved["auth_required_observed"])
        self.assertFalse(saved["submission_observed"])
        self.assertTrue(saved["native_error"])
        self.assertFalse(saved["native_final_success"])
        self.assertEqual(saved["observed_models"], ["claude-opus-5-5"])
        self.assertEqual(saved["model_evidence"], [{"source": "init.model", "model": "claude-opus-5-5"}])
        self.assertEqual(saved["target_verification"], "CONFIGURED")
        self.assertNotIn("first_submission_seconds", saved)
        self.assertNotIn("first_generation_seconds", saved)
        self.assertNotIn("SENT", [item["phase"] for item in saved["phase_history"]])
        self.assertEqual((Path(self.args.run_dir) / "answer.md").read_text(),
                         "Not logged in · Please run /login")
        self.assertEqual(saved["acceptance_status"], "PENDING_CONTROLLER_REVIEW")
        with mock.patch.object(runner.subprocess, "Popen") as popen:
            with self.assertRaises(runner.delivery.DeliveryError):
                runner.run(self.args)
            popen.assert_not_called()

    def test_synthetic_or_api_error_assistant_is_not_submission_evidence(self):
        for fields in ({"is_api_error_message": True, "message": {"model": "claude-opus-5-5"}},
                       {"message": {"model": "<synthetic>"}}):
            with self.subTest(fields=fields):
                parsed = runner.decode_result("opus", [{"type": "assistant", **fields}])
                self.assertFalse(parsed["submission_observed"])
                self.assertEqual(parsed["observed_models"], [])
                self.assertEqual(parsed["model_evidence"], [])

    def test_auth_required_is_reported_without_login_or_resend(self):
        self.fixture([{"type": "error", "error": {"code": "AUTH_REQUIRED"}}], exit_code=1)
        self.assertEqual(runner.run(self.args)["phase"], "WAITING_FOR_AUTH")
        self.assertEqual(self.receipt()["dispatch_state"], "UNKNOWN")
        self.assertEqual(self.receipt()["failure_classification"], "AUTH_REQUIRED")
        with mock.patch.object(runner.subprocess, "Popen") as popen:
            with self.assertRaises(runner.delivery.DeliveryError):
                runner.run(self.args)
            popen.assert_not_called()

    def test_success_freezes_prompt_and_native_answer_with_normal_harness(self):
        result = runner.run(self.args)
        saved = self.receipt()
        self.assertEqual(result["delivery_status"], "COMPLETE")
        self.assertEqual(result["dispatch_state"], "SENT")
        self.assertEqual(saved["target_verification"], "CONFIGURED")
        self.assertIsNone(saved["effective_effort"])
        self.assertIsNone(saved["actual_workflow"])
        self.assertEqual(saved["session_ids"], ["native-session"])
        self.assertEqual((Path(self.args.run_dir) / "prompt.txt").read_bytes(), self.prompt.read_bytes())
        self.assertEqual((Path(self.args.run_dir) / "answer.md").read_text(), "Review complete.\nEND_TEST\n")
        for forbidden in ("--tools", "--bare", "--dangerously-skip-permissions", "--resume"):
            self.assertNotIn(forbidden, saved["argv"])
        self.assertIn("--permission-mode", saved["argv"])

    def test_default_web_preapproval_reaches_process_without_narrowing_harness(self):
        events = opus_events()
        events[0].update(tools=["Read", "Bash", "Agent", "Skill", "WebSearch", "WebFetch"],
                         plugins=[{"name": "configured-plugin"}],
                         mcp_servers=[{"name": "configured-server", "status": "connected"}])
        self.fixture(events)
        self.assertEqual(runner.run(self.args)["delivery_status"], "COMPLETE")
        argv = json.loads((self.root / "received-argv.json").read_text())
        self.assertEqual(argv, self.receipt()["argv"])
        self.assertEqual(argv[argv.index("--allowedTools") + 1:], ["WebSearch", "WebFetch"])
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk")
        for forbidden in ("--tools", "--bare", "--safe-mode", "--setting-sources",
                          "--dangerously-skip-permissions", "--allow-dangerously-skip-permissions",
                          "--strict-mcp-config", "--system-prompt"):
            self.assertNotIn(forbidden, argv)
        raw = runner.parse_events((Path(self.args.run_dir) / "stdout.raw").read_bytes())
        for key in ("tools", "skills", "plugins", "mcp_servers"):
            self.assertEqual(raw[0][key], events[0][key])

    def test_preapproved_web_tool_denials_still_reject_successful_final(self):
        for tool in ("WebSearch", "WebFetch"):
            with self.subTest(tool=tool):
                self.args.run_dir = str(self.root / ("denied." + tool))
                self.fixture(opus_events(answer="All network checks succeeded.\nEND_TEST\n",
                                         permission_denials=[{"tool_name": tool}]))
                result = runner.run(self.args)
                saved = self.receipt()
                self.assertEqual(result["delivery_status"], "INCOMPLETE")
                self.assertEqual(result["answer_capture_status"], "CAPTURED")
                self.assertEqual(result["acceptance_status"], "PENDING_CONTROLLER_REVIEW")
                self.assertEqual(result["phase"], "FAILED")
                self.assertEqual(result["dispatch_state"], "SENT")
                self.assertEqual(saved["returncode"], 0)
                self.assertTrue(saved["native_final_success"])
                self.assertTrue(saved["sentinel_verified"])
                self.assertTrue(saved["native_denial"])
                self.assertIn(tool, saved["argv"])

    def test_duplicate_run_never_spawns_again(self):
        runner.run(self.args)
        with mock.patch.object(runner.subprocess, "Popen") as popen:
            with self.assertRaises(runner.delivery.DeliveryError) as error:
                runner.run(self.args)
        self.assertEqual(error.exception.code, "RUN_ALREADY_EXISTS_DO_NOT_RESEND")
        popen.assert_not_called()

    def test_nonzero_even_with_success_event_is_not_complete(self):
        self.fixture(opus_events(), exit_code=3)
        self.assertEqual(runner.run(self.args)["delivery_status"], "INCOMPLETE")
        self.assertEqual(self.receipt()["returncode"], 3)

    def test_zero_exit_without_native_final_is_not_delivery(self):
        self.fixture(opus_events()[:-1])
        result = runner.run(self.args)
        self.assertEqual((result["dispatch_state"], result["delivery_status"]), ("SENT", "INCOMPLETE"))
        self.assertFalse((Path(self.args.run_dir) / "answer.md").exists())

    def test_timeout_terminates_only_owned_process_and_keeps_unknown(self):
        self.fixture([], pause=60)
        self.args.timeout_seconds = 0.08
        result = runner.run(self.args)
        self.assertEqual(result["process_status"], "TIMEOUT")
        self.assertEqual(result["dispatch_state"], "UNKNOWN")
        self.assertTrue(self.receipt()["termination_confirmed"])
        self.assertLess(result["elapsed_seconds"], 7)

    def test_structured_output_is_not_substituted_for_original_text(self):
        self.fixture(opus_events(answer="", structured_output={"answer": "Fabricated export\nEND_TEST"}))
        result = runner.run(self.args)
        self.assertEqual(result["delivery_status"], "INCOMPLETE")
        self.assertTrue(self.receipt()["structured_output_only"])
        self.assertFalse((Path(self.args.run_dir) / "answer.md").exists())

    def test_native_denial_or_error_prevents_complete(self):
        for key, value in (("permission_denials", [{"tool_name": "Bash"}]), ("is_error", True)):
            parsed = runner.decode_result("opus", opus_events(**{key: value}))
            self.assertTrue(parsed["native_denial"] or parsed["native_error"])
        self.fixture(opus_events(permission_denials=[{"tool_name": "Read"}]))
        self.assertEqual(runner.run(self.args)["delivery_status"], "INCOMPLETE")

    def test_model_self_report_cannot_change_native_selected_model(self):
        events = opus_events(answer="I used exact Opus with Ultracode.\nEND_TEST")
        events[0]["model"] = "different-model"
        self.fixture(events)
        runner.run(self.args)
        self.assertEqual(self.receipt()["target_verification"], "MISMATCH")
        self.assertEqual(self.receipt()["observed_models"], ["different-model"])

    def test_xhigh_does_not_prove_ultracode_workflow(self):
        events = opus_events()
        events[0]["effort"] = "xhigh"
        self.fixture(events)
        runner.run(self.args)
        self.assertEqual(self.receipt()["target_verification"], "CONFIGURED")
        self.assertIsNone(self.receipt()["actual_workflow"])

    def test_native_workflow_and_effort_can_verify_configured_target(self):
        events = opus_events()
        events[0].update(effort="xhigh", workflow="ultracode")
        self.fixture(events)
        runner.run(self.args)
        self.assertEqual(self.receipt()["target_verification"], "VERIFIED_NATIVE_METADATA")

    def test_sentinel_must_be_final_nonempty_exact_line(self):
        self.fixture(opus_events(answer="END_TEST\nExtra text"))
        self.assertEqual(runner.run(self.args)["delivery_status"], "INCOMPLETE")
        self.assertFalse(self.receipt()["sentinel_verified"])
        self.assertEqual(self.receipt()["answer_capture_status"], "CAPTURED")
        self.assertEqual(self.receipt()["acceptance_status"], "PENDING_CONTROLLER_REVIEW")
        self.assertEqual((Path(self.args.run_dir) / "answer.md").read_text(), "END_TEST\nExtra text")

    def test_cli_output_summary_excludes_prompt_and_answer(self):
        flags = []
        for name, value in vars(self.args).items():
            if value is not None:
                flags.extend(["--" + name.replace("_", "-"), str(value)])
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(runner.main(flags), 0)
        self.assertNotIn("PRIVATE", output.getvalue())
        self.assertNotIn("Review complete", output.getvalue())

    def test_ndjson_and_single_result_supported_but_multiple_finals_rejected(self):
        single = opus_events()[-1]
        self.assertEqual(runner.parse_events(json.dumps(single).encode()), [single])
        with self.assertRaises(runner.delivery.DeliveryError) as error:
            runner.decode_result("opus", [single, single])
        self.assertEqual(error.exception.code, "MULTIPLE_FINAL_EVENTS")

    def test_spawn_failure_keeps_ambiguous_state_and_never_falls_back(self):
        with mock.patch.object(runner.subprocess, "Popen", side_effect=OSError("launch failure")) as popen:
            result = runner.run(self.args)
        self.assertEqual(popen.call_count, 1)
        self.assertEqual(result["dispatch_state"], "UNKNOWN")
        self.assertEqual(result["delivery_status"], "INCOMPLETE")

    def test_gemini_stream_input_is_one_frozen_frame_without_print_flag(self):
        self.args.adviser = "gemini"
        self.fixture(gemini_events())
        result = runner.run(self.args)
        saved = self.receipt()
        self.assertEqual((result["delivery_status"], result["target_verification"]), ("COMPLETE", "CONFIGURED"))
        self.assertEqual(saved["session_ids"], ["native-conversation"])
        self.assertNotIn("-p", saved["argv"])
        self.assertIn("--print-timeout", saved["argv"])
        self.assertEqual(saved["argv"], [str(self.executable), "--input-format", "stream-json",
                         "--output-format", "stream-json", "--model", "gemini-3.8-flash-high",
                         "--effort", "high", "--mode", "plan", "--print-timeout", "2s",
                         "--log-file", str(Path(self.args.run_dir) / "native.log")])
        self.assertEqual(json.loads((self.root / "received-argv.json").read_text()), saved["argv"])
        frame = (Path(self.args.run_dir) / "stdin.jsonl").read_text()
        self.assertEqual(len(frame.splitlines()), 1)
        self.assertEqual(json.loads(frame)["message"]["content"], self.prompt.read_text())
        self.assertEqual((Path(self.args.run_dir) / "answer.md").read_text(), "Review complete.\nEND_TEST\n")

    def test_gemini_exit_zero_but_error_result_rejects_completion(self):
        self.args.adviser = "gemini"
        self.fixture(gemini_events(status="ERROR", error="native failure"))
        result = runner.run(self.args)
        self.assertEqual((result["dispatch_state"], result["delivery_status"]), ("SENT", "INCOMPLETE"))

    def test_gemini_stderr_native_error_invalidates_success_envelope(self):
        self.args.adviser = "gemini"
        self.fixture(gemini_events(), stderr="AGY_ERROR: timed out\n")
        self.assertEqual(runner.run(self.args)["delivery_status"], "INCOMPLETE")
        self.assertTrue(self.receipt()["native_error"])

    def test_gemini_denied_actions_invalidate_success(self):
        self.args.adviser = "gemini"
        self.fixture(gemini_events(denied_actions=[{"tool": "read_file"}]))
        self.assertEqual(runner.run(self.args)["delivery_status"], "INCOMPLETE")

    def test_gemini_streamed_deltas_cannot_replace_missing_final(self):
        self.args.adviser = "gemini"
        self.fixture(gemini_events()[:-1])
        result = runner.run(self.args)
        self.assertEqual((result["dispatch_state"], result["delivery_status"]), ("SENT", "INCOMPLETE"))
        self.assertFalse((Path(self.args.run_dir) / "answer.md").exists())

    def test_gemini_native_effort_high_is_separate_proof(self):
        self.args.adviser = "gemini"
        events = gemini_events()
        events[0]["init"]["effort"] = "high"
        self.fixture(events)
        runner.run(self.args)
        self.assertEqual(self.receipt()["target_verification"], "VERIFIED_NATIVE_METADATA")

    def test_gemini_single_json_envelope_and_structured_only(self):
        final = gemini_events()[-1]["result"]
        parsed = runner.decode_result("gemini", [final])
        self.assertEqual(parsed["answer"], "Review complete.\nEND_TEST\n")
        self.assertTrue(parsed["native_final_success"])
        parsed = runner.decode_result("gemini", gemini_events(answer="", structured_output={"text": "x"}))
        self.assertIsNone(parsed["answer"])
        self.assertTrue(parsed["structured_output_only"])

    def test_trusted_launcher_symlink_resolved_and_recorded(self):
        launcher = self.root / "official-launcher"
        self.make_symlink(launcher, self.executable)
        self.args.executable = str(launcher)
        runner.run(self.args)
        self.assertEqual(self.receipt()["executable_requested"], str(launcher))
        self.assertEqual(self.receipt()["executable_resolved"], str(self.executable))

    def test_prompt_symlink_still_rejected(self):
        link = self.root / "prompt-link"
        self.make_symlink(link, self.prompt)
        self.args.prompt_file = str(link)
        with self.assertRaises(runner.delivery.DeliveryError) as error:
            runner.run(self.args)
        self.assertEqual(error.exception.code, "LINK_OR_REPARSE_REFUSED")

    def make_symlink(self, link, target):
        try:
            link.symlink_to(target)
        except OSError as error:
            if os.name == "nt" and getattr(error, "winerror", None) == 1314:
                self.skipTest("Windows symlink privilege is unavailable")
            raise

    def test_windows_rejects_shell_wrappers_before_any_process_start(self):
        with mock.patch.object(runner, "IS_WINDOWS", True):
            for extension in (".cmd", ".bat", ".ps1", ".py", ""):
                with self.subTest(extension=extension):
                    with self.assertRaises(runner.delivery.DeliveryError) as error:
                        runner.require_native_launcher(Path("official-cli" + extension))
                    self.assertEqual(error.exception.code, "WINDOWS_NATIVE_EXECUTABLE_REQUIRED")
            runner.require_native_launcher(Path("official-cli.EXE"))
        self.fixture_process.assert_not_called()

    def test_windows_timeout_targets_only_owned_pid_tree(self):
        process = mock.Mock(pid=12345)
        process.poll.side_effect = [None, 1]
        with mock.patch.object(runner, "IS_WINDOWS", True), \
             mock.patch.object(runner, "windows_taskkill", return_value="trusted-system/taskkill.exe"), \
             mock.patch.object(runner.subprocess, "run", return_value=mock.Mock(returncode=0)) as stop:
            self.assertTrue(runner.stop_owned(process))
        self.assertEqual(stop.call_args.args[0],
                         ["trusted-system/taskkill.exe", "/PID", "12345", "/T", "/F"])
        self.assertIs(stop.call_args.kwargs["shell"], False)
        self.assertEqual(stop.call_args.kwargs["timeout"], 3)
        process.kill.assert_not_called()
        process.wait.assert_called_once_with(timeout=3)

    def test_windows_parent_only_fallback_does_not_claim_tree_termination(self):
        process = mock.Mock(pid=12345)
        process.poll.return_value = None
        with mock.patch.object(runner, "IS_WINDOWS", True), \
             mock.patch.object(runner, "windows_taskkill", side_effect=OSError("unavailable")):
            self.assertFalse(runner.stop_owned(process))
        process.kill.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=3)

    def test_main_assistant_model_mismatch_not_masked_by_init(self):
        events = opus_events(modelUsage={"claude-opus-5-5": {}, "subagent-model": {}})
        events[1]["message"]["model"] = "wrong-main-model"
        self.fixture(events)
        flags = []
        for name, value in vars(self.args).items():
            if value is not None:
                flags.extend(["--" + name.replace("_", "-"), str(value)])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.main(flags), 1)
        self.assertEqual(self.receipt()["delivery_status"], "COMPLETE")
        self.assertEqual(self.receipt()["target_verification"], "MISMATCH")
        self.assertEqual(self.receipt()["usage_models"], ["claude-opus-5-5", "subagent-model"])

    def test_missing_init_main_model_is_evidence_subagent_model_is_not(self):
        events = opus_events()[1:]
        events[0]["message"]["model"] = "claude-opus-5-5"
        events.insert(0, {"type": "assistant", "parent_tool_use_id": "subagent-task",
                          "message": {"model": "another-model"}})
        parsed = runner.decode_result("opus", events)
        self.assertEqual(parsed["observed_models"], ["claude-opus-5-5"])
        self.assertEqual(parsed["model_evidence"][0]["source"], "main_assistant.message.model")

    def test_gemini_nested_native_failures_and_denials_reject(self):
        for fields in ({"errors": ["backend failed"]}, {"state": "FAILED"},
                       {"tool_info": {"error": {"type": "PERMISSION_DENIED"}}},
                       {"tool_info": {"denied_actions": [{"tool": "read_file"}]}}):
            events = gemini_events()
            events.insert(2, {"event": "step_update", "step_update": {"step_type": "tool", **fields}})
            parsed = runner.decode_result("gemini", events)
            self.assertTrue(parsed["native_error"] or parsed["native_denial"])

    def test_exact_pre_dispatch_argument_rejection_is_not_sent_but_no_retry(self):
        self.args.adviser = "gemini"
        self.fixture([], exit_code=2, stderr='Error: -p took "--output-format" as its prompt, so the intended prompt was left as an argument and ignored.\n')
        result = runner.run(self.args)
        self.assertEqual(result["dispatch_state"], "NOT_SENT")
        self.assertEqual(result["error_code"], "CLI_ARGUMENT_REJECTED")
        with self.assertRaises(runner.delivery.DeliveryError) as error:
            runner.run(self.args)
        self.assertEqual(error.exception.code, "RUN_ALREADY_EXISTS_DO_NOT_RESEND")

    def test_explicit_wrong_workflow_is_target_mismatch(self):
        events = opus_events()
        events[0].update(effort="xhigh", workflow="different-workflow")
        self.fixture(events)
        runner.run(self.args)
        self.assertEqual(self.receipt()["target_verification"], "MISMATCH")

    def test_error_only_envelope_does_not_prove_submission(self):
        for adviser, events in (
            ("gemini", [{"event": "result", "result": {"conversation_id": "", "num_turns": 0,
                         "status": "ERROR", "response": "", "error": "invalid model"}}]),
            ("opus", [{"type": "result", "subtype": "error", "is_error": True, "errors": ["preflight failed"]}]),
        ):
            parsed = runner.decode_result(adviser, events)
            self.assertFalse(parsed["submission_observed"])
            self.assertFalse(parsed["native_final_success"])

    def test_success_with_native_timeout_or_truncation_flag_is_incomplete(self):
        for flag in ("timeout", "timed_out", "truncated", "response_truncated", "partial"):
            parsed = runner.decode_result("gemini", gemini_events(**{flag: True}))
            self.assertTrue(parsed["native_incomplete"])
        self.args.adviser = "gemini"
        self.fixture(gemini_events(timed_out=True))
        self.assertEqual(runner.run(self.args)["delivery_status"], "INCOMPLETE")

    def test_missing_model_proof_is_nonzero_even_for_complete_answer(self):
        self.fixture(opus_events()[1:])
        flags = []
        for name, value in vars(self.args).items():
            if value is not None:
                flags.extend(["--" + name.replace("_", "-"), str(value)])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.main(flags), 1)
        self.assertEqual(self.receipt()["delivery_status"], "COMPLETE")
        self.assertEqual(self.receipt()["target_verification"], "UNKNOWN_UNVERIFIED")

    def test_exact_agy_partial_timeout_warning_rejects_success_even_with_sentinel(self):
        self.args.adviser = "gemini"
        self.fixture(gemini_events(), stderr="[agy] print timeout after 5m0s with turn in progress; returning partial output\n")
        self.assertEqual(runner.run(self.args)["delivery_status"], "INCOMPLETE")
        self.assertEqual(self.receipt()["stderr_diagnostic_codes"], ["AGY_PRINT_TIMEOUT_PARTIAL"])

    def test_timeout_phrase_in_answer_or_unrelated_stderr_does_not_fake_timeout(self):
        self.args.adviser = "gemini"
        self.fixture(gemini_events(answer="[agy] print timeout after 5m0s with turn in progress; returning partial output\nEND_TEST"),
                     stderr="Diagnostic reference: print timeout configuration is 5m\n")
        self.assertEqual(runner.run(self.args)["delivery_status"], "COMPLETE")
        self.assertFalse(self.receipt()["native_incomplete"])


if __name__ == "__main__":
    unittest.main()
