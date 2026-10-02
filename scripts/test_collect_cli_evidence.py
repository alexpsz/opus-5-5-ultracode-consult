"""Offline evidence boundaries; all adviser streams and native files are fixtures."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


PACKAGE = Path(__file__).resolve().parents[1]
SCRIPT = PACKAGE / "scripts" / "collect_cli_evidence.py"
SPEC = importlib.util.spec_from_file_location("cli_evidence_under_test", SCRIPT)
c = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(c)
SESSION = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


class CliEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.native = self.root / "native"
        self.native.mkdir()
        self.counter = 0
        home = mock.patch.object(c.Path, "home", return_value=self.root / "fixture-home")
        home.start()
        self.addCleanup(home.stop)

    def write_jsonl(self, path, records):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")

    def run_dir(self, adviser="gemini", events=None):
        self.counter += 1
        run = self.root / ("run-" + str(self.counter))
        run.mkdir()
        (run / "run.json").write_text(json.dumps({
            "adviser": adviser, "session_ids": [SESSION],
        }), encoding="utf-8")
        initial = ({"event": "init", "init": {"conversation_id": SESSION}}
                   if adviser == "gemini" else
                   {"type": "system", "subtype": "init", "session_id": SESSION})
        self.write_jsonl(run / "stdout.raw", [initial] + (events or []))
        return run

    def gemini_call(self, output=None, include_output=False, step=2, name="read_url_content"):
        info = {"name": name, "parameters": {"url": "https://example.test/source"}}
        if include_output:
            info["output"] = output
        return {"event": "step_update", "step_update": {
            "step_index": step, "step_type": "tool_call", "state": "DONE", "tool_info": info,
        }}

    def claude_call(self, name="WebFetch", tool_id="call-1"):
        return {"type": "assistant", "session_id": SESSION, "message": {"content": [
            {"type": "tool_use", "id": tool_id, "name": name,
             "input": {"url": "https://example.test/source"}},
        ]}}

    def claude_result(self, content="A returned source excerpt.", error=False, tool_id="call-1"):
        return {"type": "user", "session_id": SESSION, "message": {"content": [
            {"type": "tool_result", "tool_use_id": tool_id, "content": content, "is_error": error},
        ]}}

    def transcript(self, content, step=2, status="DONE", step_type="GENERIC"):
        path = self.native / "brain" / SESSION / ".system_generated/logs/transcript.jsonl"
        self.write_jsonl(path, [{"step_index": step, "source": "MODEL", "type": step_type,
                                 "status": status, "content": content}])
        return path

    def step_file(self, content, name="output.txt", step=2, session=SESSION):
        path = self.native / "brain" / session / ".system_generated/steps" / str(step) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def collect(self, run, native=False):
        result = c.collect(str(run), str(self.native) if native else None)
        self.assertIs(result["content_accepted"], False)
        self.assertEqual(result, json.loads((run / "evidence-summary.json").read_bytes()))
        return result

    def only_tool(self, summary):
        self.assertEqual(len(summary["tools"]), 1)
        tool = summary["tools"][0]
        for key in ("tool_id", "name", "category", "call_observed", "result_observed",
                    "native_content", "status", "content_extent", "sources", "boundaries"):
            self.assertIn(key, tool)
        self.assertIn(tool["category"], ("file", "web", "image", "other"))
        self.assertIn(tool["status"], ("corroborated", "denied", "failed", "unknown"))
        self.assertIn(tool["content_extent"], ("unknown", "fragment", "complete"))
        self.assertIsInstance(tool["boundaries"], list)
        return tool

    def rejected(self, run, native=False):
        with self.assertRaises(c.EvidenceError) as caught:
            c.collect(str(run), str(self.native) if native else None)
        self.assertTrue(caught.exception.code)
        return caught.exception

    def archived_path(self, run, source):
        archive = Path(source["archive_path"])
        return archive if archive.is_absolute() else run / archive

    def test_done_call_without_output_is_not_source_access(self):
        tool = self.only_tool(self.collect(self.run_dir(events=[self.gemini_call()])))
        self.assertTrue(tool["call_observed"])
        self.assertFalse(tool["native_content"])
        self.assertEqual(tool["status"], "unknown")
        self.assertEqual(tool["content_extent"], "unknown")

    def test_empty_results_are_not_corroboration(self):
        for output in ("", " \n", None, [], {}):
            with self.subTest(output=output):
                run = self.run_dir(events=[self.gemini_call(output, True)])
                tool = self.only_tool(self.collect(run))
                self.assertNotEqual(tool["status"], "corroborated")
                self.assertFalse(tool["native_content"])

    def test_line_and_byte_metadata_is_not_native_content(self):
        cases = (("read_url_content", "56 lines, 8684 bytes"),
                 ("view_file", "56 lines, 8684 bytes"),
                 ("read_url_content", "Error: HTTP 404 Not Found"),
                 ("view_file", "File Path: /fixture/source.txt\nThe following is the entire, complete content of the requested file."))
        for name, output in cases:
            with self.subTest(name=name, output=output):
                run = self.run_dir(events=[self.gemini_call(output, True, name=name)])
                tool = self.only_tool(self.collect(run))
                self.assertFalse(tool["native_content"])
                self.assertNotEqual(tool["status"], "corroborated")

    def test_nonempty_inline_result_never_proves_full_page_coverage(self):
        run = self.run_dir(events=[self.gemini_call("Title: Source\nReturned excerpt.", True)])
        tool = self.only_tool(self.collect(run))
        self.assertEqual(tool["status"], "corroborated")
        self.assertTrue(tool["result_observed"])
        self.assertTrue(tool["native_content"])
        self.assertEqual(tool["category"], "web")
        self.assertIn(tool["content_extent"], ("unknown", "fragment"))

    def test_claude_paired_nonempty_result_is_corroborated(self):
        run = self.run_dir("opus", [self.claude_call(), self.claude_result()])
        tool = self.only_tool(self.collect(run))
        self.assertEqual(tool["tool_id"], "call-1")
        self.assertEqual(tool["status"], "corroborated")
        self.assertTrue(tool["native_content"])
        self.assertIn(tool["content_extent"], ("unknown", "fragment"))

    def test_claude_permission_denial_is_not_content_success(self):
        run = self.run_dir("opus", [self.claude_call(), self.claude_result(
            "Permission denied: WebFetch is not allowed by the current policy.", True)])
        tool = self.only_tool(self.collect(run))
        self.assertEqual(tool["status"], "denied")
        self.assertTrue(tool["result_observed"])
        self.assertFalse(tool["native_content"])

    def test_claude_tool_error_is_failed(self):
        run = self.run_dir("opus", [self.claude_call(), self.claude_result("Connection timed out", True)])
        tool = self.only_tool(self.collect(run))
        self.assertEqual(tool["status"], "failed")
        self.assertFalse(tool["native_content"])

    def test_non_tool_messages_and_unpaired_results_do_not_invent_access(self):
        events = [{"type": kind, "session_id": SESSION, "message": {"content": "I read a page."}}
                  for kind in ("assistant", "user")]
        events += [self.claude_result(tool_id="never-called")]
        summary = self.collect(self.run_dir("opus", events))
        self.assertFalse(any(t["status"] == "corroborated" for t in summary["tools"]))
        event = self.gemini_call("Source excerpt", True)
        event["step_update"]["step_type"] = "agent_response"
        run = self.run_dir(events=[event])
        try:
            summary = self.collect(run)
        except c.EvidenceError:
            self.assertFalse((run / "evidence-summary.json").exists())
        else:
            self.assertFalse(summary["tools"], "A non-tool step cannot establish a tool call")

    def test_image_evidence_retains_an_explicit_acceptance_boundary(self):
        run = self.run_dir(events=[self.gemini_call("Image loaded: 640 by 480 pixels", True,
                                                   name="open_image")])
        tool = self.only_tool(self.collect(run))
        self.assertEqual(tool["category"], "image")
        self.assertTrue(tool["boundaries"], "Native metadata does not independently verify image perception")
        self.transcript("Created At: 2026-10-01\nCompleted At: 2026-10-01")
        self.step_file(b"The following is the entire, complete content of the requested file.")
        event = self.gemini_call("56 lines, 8684 bytes", True, name="view_file")
        event["step_update"]["tool_info"]["parameters"] = {"AbsolutePath": "/fixture/reference.png"}
        tool = self.only_tool(self.collect(self.run_dir(events=[event]), native=True))
        self.assertEqual(tool["category"], "image")
        self.assertFalse(tool["native_content"])
        self.assertEqual(tool["status"], "unknown")
        self.assertTrue(tool["boundaries"])

    def test_native_transcript_supplements_exact_observed_step(self):
        transcript = self.transcript("Created At: 2026-10-01\nCompleted At: 2026-10-01\nSource excerpt.")
        run = self.run_dir(events=[self.gemini_call()])
        summary = self.collect(run, native=True)
        self.assertEqual(self.only_tool(summary)["status"], "corroborated")
        self.assertIn(str(transcript), [s["path"] for s in summary["sources"]])

    def test_native_output_file_supplements_matching_step(self):
        self.transcript("Created At: 2026-10-01\nCompleted At: 2026-10-01")
        output = self.step_file(b"Returned native source excerpt.\n")
        run = self.run_dir(events=[self.gemini_call("1 lines, 32 bytes", True)])
        summary = self.collect(run, native=True)
        self.assertEqual(self.only_tool(summary)["status"], "corroborated")
        self.assertIn(str(output), [s["path"] for s in summary["sources"]])

    def test_explicit_same_step_content_pointer_is_archived(self):
        content = self.step_file(b"Detailed source content.\n", name="content.md")
        self.transcript("The full content has been saved to: " + str(content))
        run = self.run_dir(events=[self.gemini_call()])
        summary = self.collect(run, native=True)
        self.assertEqual(self.only_tool(summary)["status"], "corroborated")
        self.assertIn(str(content), [s["path"] for s in summary["sources"]])

    def test_unobserved_native_step_and_unreferenced_content_are_not_collected(self):
        other = self.step_file(b"UNRELATED PRIVATE SOURCE", step=99)
        unreferenced = self.step_file(b"UNREFERENCED PRIVATE SOURCE", name="content.md")
        for fields in ({"step": 99}, {"status": "ACTIVE"}, {"step_type": "USER_INPUT"}):
            with self.subTest(fields=fields):
                self.transcript("Unrelated or unfinished native content.", **fields)
                run = self.run_dir(events=[self.gemini_call()])
                summary = self.collect(run, native=True)
                self.assertEqual(self.only_tool(summary)["status"], "unknown")
                sources = [s["path"] for s in summary["sources"]]
                self.assertNotIn(str(other), sources)
                self.assertNotIn(str(unreferenced), sources)

    def test_wrong_stream_session_is_rejected_in_init_and_result(self):
        for kind in ("init", "result"):
            with self.subTest(kind=kind):
                run = self.run_dir(events=[{"event": kind, kind: {"conversation_id": OTHER}}])
                self.rejected(run)
                self.assertFalse((run / "evidence-summary.json").exists())
        run = self.run_dir()
        self.write_jsonl(run / "stdout.raw", [self.gemini_call("Source excerpt", True)])
        self.assertEqual(self.rejected(run).code, "NATIVE_SESSION_NOT_OBSERVED")

    def test_receipt_requires_one_canonical_session_and_known_adviser(self):
        for updates in ({"session_ids": []}, {"session_ids": [SESSION, OTHER]},
                        {"session_ids": ["../escape"]},
                        {"session_ids": ["ABCDEFAB-1111-4111-8111-111111111111"]},
                        {"adviser": "unrecognized"}):
            with self.subTest(updates=updates):
                run = self.run_dir()
                receipt = {"adviser": "gemini", "session_ids": [SESSION], **updates}
                (run / "run.json").write_text(json.dumps(receipt), encoding="utf-8")
                if len(receipt["session_ids"]) == 1:
                    self.write_jsonl(run / "stdout.raw", [{"event": "init", "init": {
                        "conversation_id": receipt["session_ids"][0],
                    }}])
                self.rejected(run)

    def test_malformed_or_truncated_stream_never_creates_success_summary(self):
        for suffix in (b'{"event":', b'not-json\n', b'\xff\n'):
            with self.subTest(suffix=suffix):
                run = self.run_dir(events=[self.gemini_call("Source excerpt", True)])
                with (run / "stdout.raw").open("ab") as stream:
                    stream.write(suffix)
                self.rejected(run)
                self.assertFalse((run / "evidence-summary.json").exists())

    def test_symlinked_stdout_is_refused(self):
        run = self.run_dir()
        target = self.root / "outside-stream"
        (run / "stdout.raw").rename(target)
        (run / "stdout.raw").symlink_to(target)
        self.rejected(run)

    def test_hardlinked_source_is_refused(self):
        run = self.run_dir()
        os.link(run / "stdout.raw", self.root / "outside-hardlink")
        self.assertEqual(self.rejected(run).code, "HARDLINK_REFUSED")
        self.assertFalse((run / "evidence-summary.json").exists())

    def test_source_limit_applies_before_archive(self):
        run = self.run_dir(events=[self.gemini_call("source excerpt", True)])
        with mock.patch.object(c, "MAX_FILE", 4):
            self.assertEqual(self.rejected(run).code, "SOURCE_TOO_LARGE")
        self.assertFalse((run / "evidence-summary.json").exists())

    def test_ambiguous_paths_cannot_be_used_as_source_capabilities(self):
        for suffix in ("name.", "name ", "name:stream"):
            with self.subTest(suffix=suffix), self.assertRaises(c.EvidenceError):
                c.absolute(str(self.root / suffix))

    @unittest.skipUnless(os.name == "nt", "Windows directory handle semantics")
    def test_windows_parent_is_pinned_until_guard_closes(self):
        directory = self.root / "pinned-parent"
        directory.mkdir()
        with c.WindowsFiles().directory(directory):
            with self.assertRaises(OSError):
                directory.rename(self.root / "moved-parent")
            # Pinning the parent must still permit exclusive creation within it.
            c.Collector.write_windows(directory / "created.bin", b"fixture bytes")
        self.assertEqual((directory / "created.bin").read_bytes(), b"fixture bytes")
        directory.rename(self.root / "moved-parent")

    @unittest.skipUnless(os.name == "nt", "Windows native reparse-point handling")
    def test_windows_parent_symlink_is_refused(self):
        real = self.root / "real-parent"
        real.mkdir()
        (real / "source.bin").write_bytes(b"PRIVATE OUTSIDE CONTENT")
        link = self.root / "linked-parent"
        link.symlink_to(real, target_is_directory=True)
        with self.assertRaises(c.EvidenceError):
            c.read_bytes(link / "source.bin")

    @unittest.skipUnless(os.name == "nt", "Windows native file share semantics")
    def test_windows_source_handle_prevents_write_and_delete(self):
        source = self.root / "pinned-source.bin"
        source.write_bytes(b"stable bytes")
        api = c.WindowsFiles()
        handle = api.open(source)
        try:
            self.assertEqual(api.info(handle).links, 1)
            with self.assertRaises(OSError):
                source.write_bytes(b"changed")
            with self.assertRaises(OSError):
                source.unlink()
        finally:
            api.close(handle)
        self.assertEqual(c.read_bytes(source), b"stable bytes")

    def test_symlinked_native_transcript_is_refused(self):
        path = self.transcript("Source excerpt")
        target = self.root / "outside-transcript"
        path.rename(target)
        path.symlink_to(target)
        self.rejected(self.run_dir(events=[self.gemini_call()]), native=True)

    def test_symlinked_native_step_output_is_refused(self):
        self.transcript("Created At: 2026-10-01\nCompleted At: 2026-10-01")
        path = self.step_file(b"Source excerpt")
        target = self.root / "outside-output"
        path.rename(target)
        path.symlink_to(target)
        self.rejected(self.run_dir(events=[self.gemini_call()]), native=True)

    def test_cross_session_and_traversal_content_pointers_are_refused(self):
        other = self.step_file(b"PRIVATE OTHER SESSION", name="content.md", session=OTHER)
        current = self.step_file(b"Source excerpt", name="content.md")
        for pointer in (str(other), str(current.parent / ".." / "2" / "content.md")):
            with self.subTest(pointer=pointer):
                self.transcript("The full content has been saved to: " + pointer)
                run = self.run_dir(events=[self.gemini_call()])
                self.rejected(run, native=True)
                self.assertFalse((run / "evidence-summary.json").exists())

    def test_source_archives_preserve_bytes_hashes_and_exact_tool_line_links(self):
        run = self.run_dir("opus", [self.claude_call(), self.claude_result()])
        raw = (run / "stdout.raw").read_bytes()
        summary = self.collect(run)
        by_id = {source["source_id"]: source for source in summary["sources"]}
        self.assertEqual(len(by_id), len(summary["sources"]))
        for source in by_id.values():
            original = Path(source["path"]).read_bytes()
            archived = self.archived_path(run, source)
            self.assertTrue(archived.is_relative_to(run / "evidence-archive/sources"))
            self.assertEqual(archived.read_bytes(), original)
            self.assertEqual(source["bytes"], len(original))
            self.assertEqual(source["sha256"], hashlib.sha256(original).hexdigest())
        tool = self.only_tool(summary)
        linked_lines = set()
        for reference in tool["sources"]:
            self.assertIn(reference["source_id"], by_id)
            source = by_id[reference["source_id"]]
            if source["path"] == str(run / "stdout.raw"):
                self.assertIsInstance(reference.get("line"), int)
                linked_lines.add(reference["line"])
        self.assertTrue({2, 3}.issubset(linked_lines), "Call and result need their exact source lines")
        self.assertEqual((run / "stdout.raw").read_bytes(), raw)

    def test_existing_summary_and_archive_are_never_overwritten(self):
        run = self.run_dir(events=[self.gemini_call("Source excerpt", True)])
        self.collect(run)
        protected = {p: (p.read_bytes(), p.stat().st_mtime_ns)
                     for p in run.rglob("*") if p.is_file()}
        self.rejected(run)
        for path, before in protected.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_preexisting_archive_or_summary_blocks_first_collection(self):
        for filename in ("evidence-summary.json", "evidence-archive/sources/keep.txt"):
            with self.subTest(filename=filename):
                run = self.run_dir(events=[self.gemini_call("Source excerpt", True)])
                existing = run / filename
                existing.parent.mkdir(parents=True, exist_ok=True)
                existing.write_bytes(b"PRESERVE ME")
                self.rejected(run)
                self.assertEqual(existing.read_bytes(), b"PRESERVE ME")

    def test_symlinked_archive_destination_cannot_write_outside_run(self):
        run = self.run_dir(events=[self.gemini_call("Source excerpt", True)])
        target = self.root / "outside-archive"
        target.mkdir()
        (run / "evidence-archive").symlink_to(target, target_is_directory=True)
        self.rejected(run)
        self.assertEqual(list(target.iterdir()), [])

    def test_cli_accepts_explicit_run_and_native_root_without_model_execution(self):
        self.transcript("Native source excerpt")
        run = self.run_dir(events=[self.gemini_call()])
        completed = subprocess.run([sys.executable, str(SCRIPT), "--run-dir", str(run),
                                    "--native-data-root", str(self.native)],
                                   capture_output=True, text=True, timeout=15, check=False)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        summary = json.loads((run / "evidence-summary.json").read_bytes())
        self.assertIs(summary["content_accepted"], False)
        self.assertEqual(self.only_tool(summary)["status"], "corroborated")


if __name__ == "__main__":
    unittest.main()
