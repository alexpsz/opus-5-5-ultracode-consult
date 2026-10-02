#!/usr/bin/env python3
"""One explicit official CLI turn; no automatic retry or channel fallback.

Use the same deterministic run directory for a request/adviser. Its exclusive
creation is the duplicate guard. Normal CLI configuration/skills remain enabled;
Permission mode and plan mode are not filesystem sandboxes.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time
import uuid

import collect_delivery as delivery
import consult_preflight as preflight
import runtime_profile

TARGETS = {"opus": ("claude-opus-5-5", "ultracode"),
           "gemini": ("gemini-3.8-flash-high", "high")}
MAX_OUTPUT = 32 * 1024 * 1024
PROGRESS_INTERVAL = 0.5
POLL_INTERVAL = 0.1
IS_WINDOWS = os.name == "nt"


def require(condition, code):
    delivery.require(condition, code)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def canonical(value, missing=False):
    path = delivery._absolute(value)
    require(str(path) == value, "CANONICAL_PATH_REQUIRED")
    delivery._check_chain(path, allow_missing_leaf=missing)
    require(str(path.resolve(strict=not missing)) == str(path), "CANONICAL_PATH_REQUIRED")
    return path


def save_receipt(directory, receipt):
    temporary = directory / ".run.json.tmp"
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, directory / "run.json")


def command(adviser, executable, model, effort, timeout, directory, session=None):
    require((model, effort) == TARGETS[adviser], "UNSUPPORTED_TARGET")
    if adviser == "opus":
        return [str(executable), "-p", "--verbose", "--output-format", "stream-json",
                "--model", model, "--effort", effort, "--permission-mode", "dontAsk"] + (
                ["--resume", session] if session else []) + [
                "--allowedTools", "WebSearch", "WebFetch"]
    return [str(executable), "--input-format", "stream-json", "--output-format", "stream-json",
            "--model", model, "--effort", effort, "--mode", "plan",
            "--print-timeout", str(timeout) + "s", "--log-file", str(directory / "native.log")] + (
            ["--conversation", session] if session else [])


def continuation(args, project, directory, model, effort):
    value = getattr(args, "continue_from", None)
    if value is None:
        return None
    path = canonical(value)
    require(path.name == "run.json", "PARENT_RECEIPT_REQUIRED")
    raw = delivery.read_file(path)
    parent = delivery.parse_json(raw)
    require(isinstance(parent, dict), "INVALID_PARENT_RECEIPT")
    require(parent.get("adviser") == args.adviser and parent.get("project_root") == str(project),
            "PARENT_SCOPE_MISMATCH")
    require((parent.get("requested_model"), parent.get("requested_effort")) == (model, effort) and
            parent.get("target_verification") in ("CONFIGURED", "VERIFIED_NATIVE_METADATA"),
            "PARENT_TARGET_MISMATCH")
    require(parent.get("dispatch_state") == "SENT" and parent.get("submission_observed") is True,
            "PARENT_NOT_SENT")
    require(parent.get("process_status") in ("SUCCESS", "ERROR", "TIMEOUT", "INTERRUPTED") and
            isinstance(parent.get("finished_at"), str) and bool(parent["finished_at"]) and
            isinstance(parent.get("returncode"), int) and not isinstance(parent["returncode"], bool),
            "PARENT_NOT_TERMINAL")
    require(parent.get("native_final_observed") is True, "PARENT_FINAL_REQUIRED")
    sessions = parent.get("session_ids")
    require(isinstance(sessions, list) and len(sessions) == 1 and isinstance(sessions[0], str),
            "PARENT_SESSION_REQUIRED")
    try:
        valid = str(uuid.UUID(sessions[0])) == sessions[0]
    except ValueError:
        valid = False
    require(valid, "INVALID_PARENT_SESSION_UUID")
    request = parent.get("request_id")
    require(isinstance(request, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", request),
            "INVALID_PARENT_REQUEST_ID")
    require(request != args.request_id and path.parent != directory, "FOLLOWUP_REQUIRES_NEW_REQUEST")
    previous_profile = parent.get("runtime_profile", {})
    require(isinstance(previous_profile, dict), "INVALID_PARENT_RUNTIME_PROFILE")
    profile_hash = previous_profile.get("sha256")
    require(profile_hash is None or isinstance(profile_hash, str) and
            re.fullmatch(r"[0-9a-f]{64}", profile_hash), "INVALID_PARENT_RUNTIME_PROFILE")
    return {"receipt": str(path), "receipt_sha256": hashlib.sha256(raw).hexdigest(),
            "request_id": request, "session_id": sessions[0], "runtime_profile_sha256": profile_hash}


def run_preflight(args, executable, project, prompt_file, prompt):
    profile = runtime_profile.check_profile(adviser=args.adviser, launcher=Path(args.executable),
                resolved=executable, path=getattr(args, "runtime_profile", None))
    if not profile["ok"]:
        return {"ok": False, "error_code": profile["error_code"], "runtime_profile": profile,
                "checks": {"runtime_profile": profile}, "warnings": [], "cache": {"status": "NOT_CHECKED"}}
    checked = dict(preflight.check_run(adviser=args.adviser, executable=executable, project=project,
                                      prompt_file=prompt_file, prompt=prompt,
                                      input_manifest=getattr(args, "input_manifest", None)))
    checked["runtime_profile"] = profile
    checked["checks"] = {**checked.get("checks", {}), "runtime_profile": profile}
    old_key = checked.get("cache_key")
    if isinstance(old_key, str) and re.fullmatch(r"[0-9a-f]{64}", old_key):
        checked["cache_key"] = hashlib.sha256((old_key + ":" + profile["sha256"]).encode()).hexdigest()
        checked["cache"] = preflight.read_cache(checked["cache_key"])
    return checked


def set_phase(receipt, phase, elapsed):
    if receipt.get("phase") != phase:
        receipt["phase"] = phase
        receipt.setdefault("phase_history", []).append(
            {"phase": phase, "at": now(), "elapsed_seconds": round(elapsed, 3)})


def phase_durations(receipt, elapsed):
    history = receipt.get("phase_history", [])
    totals = {}
    for index, entry in enumerate(history):
        end = history[index + 1]["elapsed_seconds"] if index + 1 < len(history) else elapsed
        totals[entry["phase"]] = round(totals.get(entry["phase"], 0) +
                                     max(0, end - entry["elapsed_seconds"]), 3)
    receipt["phase_durations_seconds"] = totals


def native_auth_required(event, payload):
    markers = {"AUTH_REQUIRED", "AUTHENTICATION_REQUIRED", "NOT_AUTHENTICATED", "WAITING_FOR_AUTH",
               "authentication_failed"}
    if event.get("type") in ("auth_required", "authentication_required") or event.get("event") in (
            "auth_required", "authentication_required"):
        return True
    error = payload.get("error")
    values = [payload.get("status"), payload.get("state"), error]
    if isinstance(error, dict):
        values.extend((error.get("code"), error.get("type")))
    return any(isinstance(value, str) and value in markers for value in values)


def model_assistant(event):
    """Synthetic CLI/API failures are local diagnostics, not model responses."""
    message = event.get("message")
    return (event.get("type") == "assistant" and event.get("parent_tool_use_id") is None and
            event.get("is_api_error_message") is not True and
            not (isinstance(message, dict) and message.get("model") == "<synthetic>"))


class LiveEvents:
    """Observe complete NDJSON records only; final collection remains strict."""
    def __init__(self, path, adviser, receipt, started):
        self.path, self.adviser, self.receipt, self.started = path, adviser, receipt, started
        self.offset, self.pending, self.tools = 0, b"", {}
        self.disabled = False

    def poll(self):
        if self.disabled:
            return False
        try:
            require(self.path.stat().st_size <= MAX_OUTPUT, "OUTPUT_TOO_LARGE")
            with self.path.open("rb") as stream:
                stream.seek(self.offset)
                chunk = stream.read(MAX_OUTPUT + 1 - self.offset)
            self.offset += len(chunk)
            self.pending += chunk
            lines = self.pending.split(b"\n")
            self.pending = lines.pop()
            changed = False
            for line in lines:
                if line.strip():
                    event = delivery.parse_json(line)
                    require(isinstance(event, dict), "INVALID_NATIVE_EVENT")
                    self.observe(event)
                    changed = True
            return changed
        except (delivery.DeliveryError, OSError, ValueError) as error:
            self.receipt["progress_error_code"] = getattr(error, "code", "PROGRESS_UNAVAILABLE")
            self.disabled = True
            return True

    def observe(self, event):
        receipt = self.receipt
        elapsed = time.monotonic() - self.started
        parsed = decode_result(self.adviser, [event])
        kind = event.get("type") if self.adviser == "opus" else event.get("event")
        payload = event if self.adviser == "opus" else event.get(kind, {}) if isinstance(kind, str) else event
        receipt.update(last_event_at=now(), last_event_type=str(kind or "result"),
                       event_count=receipt.get("event_count", 0) + 1)
        receipt.setdefault("first_event_seconds", round(elapsed, 3))
        if isinstance(event.get("timestamp"), str):
            receipt["last_native_event_at"] = event["timestamp"]
        for key in ("observed_models", "observed_efforts", "observed_workflows", "session_ids"):
            current = receipt.setdefault(key, [])
            for value in parsed[key]:
                if value not in current:
                    current.append(value)
        receipt.setdefault("model_evidence", []).extend(parsed["model_evidence"])
        for key in ("submission_observed", "native_error", "native_denial", "native_incomplete",
                    "native_final_observed", "native_final_success"):
            receipt[key] = receipt.get(key, False) or parsed[key]
        if parsed["submission_observed"]:
            receipt["dispatch_state"] = "SENT"
            receipt.setdefault("first_submission_seconds", round(elapsed, 3))
            if receipt["phase"] in ("READY", "WAITING_FOR_AUTH"):
                set_phase(receipt, "SENT", elapsed)
        generating = (kind == "assistant" and parsed["submission_observed"] or
                      kind == "step_update" and payload.get("step_type") == "agent_response" and
                      payload.get("state") in ("ACTIVE", "DONE") and parsed["submission_observed"])
        if generating:
            receipt.setdefault("first_generation_seconds", round(elapsed, 3))
            set_phase(receipt, "GENERATING", elapsed)
        if parsed["native_final_observed"]:
            receipt.setdefault("first_final_seconds", round(elapsed, 3))
        if native_auth_required(event, payload):
            receipt["auth_required_observed"] = True
            set_phase(receipt, "WAITING_FOR_AUTH", elapsed)
        message = payload.get("message", {})
        content = message.get("content", []) if isinstance(message, dict) else []
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                self.tools[block.get("id")] = block.get("name")
                receipt["last_tool"] = {"name": block.get("name"), "id": block.get("id"),
                                        "status": "STARTED", "at": now()}
            elif block.get("type") == "tool_result":
                identity = block.get("tool_use_id")
                receipt["last_tool"] = {"name": self.tools.get(identity), "id": identity,
                                        "status": "ERROR" if block.get("is_error") else "RESULT", "at": now()}
        if kind == "step_update" and isinstance(payload.get("tool_info"), dict):
            info = payload["tool_info"]
            receipt["last_tool"] = {"name": info.get("tool_name") or info.get("name"),
                                    "step_index": payload.get("step_index"),
                                    "status": payload.get("state"), "at": now()}


def parse_events(raw):
    require(len(raw) <= MAX_OUTPUT, "OUTPUT_TOO_LARGE")
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise delivery.DeliveryError("INVALID_OUTPUT_UTF8") from None
    require(bool(decoded.strip()), "EMPTY_OUTPUT")
    try:
        single = delivery.parse_json(raw)
        return [single]
    except delivery.DeliveryError:
        return [delivery.parse_json(line.encode("utf-8")) for line in decoded.splitlines() if line.strip()]


def decode_result(adviser, events):
    """Only native envelopes supply status/model; never infer them from prose."""
    models, efforts, workflows, sessions, model_sources = [], [], [], [], []
    result = {"submission_observed": False, "native_final_success": False,
              "native_error": False, "native_denial": False, "native_incomplete": False, "answer": None}
    final = None
    for event in events:
        require(isinstance(event, dict), "INVALID_NATIVE_EVENT")
        kind = event.get("type") if adviser == "opus" else event.get("event")
        payload = event if adviser == "opus" else event.get(kind, {}) if isinstance(kind, str) else event
        require(isinstance(payload, dict), "INVALID_NATIVE_EVENT")
        initial = kind == "init" or (kind == "system" and payload.get("subtype") == "init")
        if initial:
            for key, target in (("model", models), ("effort", efforts), ("workflow", workflows)):
                value = payload.get(key)
                if isinstance(value, str) and value and value not in target:
                    target.append(value)
                    if key == "model":
                        model_sources.append({"source": "init.model", "model": value})
        if adviser == "opus" and model_assistant(event):
            value = payload.get("message", {}).get("model") if isinstance(payload.get("message"), dict) else None
            if isinstance(value, str) and value:
                model_sources.append({"source": "main_assistant.message.model", "model": value})
                if value not in models:
                    models.append(value)
        for source in (event, payload):
            for key in ("session_id", "conversation_id"):
                value = source.get(key)
                if isinstance(value, str) and value and value not in sessions:
                    sessions.append(value)
        if (kind == "error" or payload.get("is_error") is True or payload.get("error") or
            payload.get("errors") or payload.get("state") in ("ERROR", "FAILED", "CANCELLED", "CANCELED", "DENIED")):
            result["native_error"] = True
        if payload.get("permission_denials") or payload.get("denied_actions") or (
                kind == "system" and payload.get("subtype") == "permission_denied"):
            result["native_denial"] = True
        if any(payload.get(key) is True for key in ("timeout", "timed_out", "truncated", "response_truncated", "partial")):
            result["native_incomplete"] = True
        tool_info = payload.get("tool_info", {})
        if isinstance(tool_info, dict):
            if tool_info.get("error") or tool_info.get("errors"):
                result["native_error"] = True
            if tool_info.get("denied_actions") or tool_info.get("permission_denials"):
                result["native_denial"] = True
        message = payload.get("message", {})
        if isinstance(message, dict) and isinstance(message.get("content"), list):
            if any(isinstance(block, dict) and block.get("type") == "tool_result" and
                   block.get("is_error") is True for block in message["content"]):
                result["native_error"] = True
        if (adviser == "opus" and model_assistant(event)) or (kind == "step_update" and
            ((payload.get("step_type") == "agent_response" and payload.get("state") in ("ACTIVE", "DONE") and
              isinstance(payload.get("text_delta"), str) and bool(payload["text_delta"])) or
             (payload.get("step_type") == "user_input" and payload.get("state") == "DONE"))):
            result["submission_observed"] = True
        # Support the native single-JSON envelope as well as NDJSON result events.
        is_final = kind == "result" or (adviser == "gemini" and kind is None and
                                         "status" in payload and "conversation_id" in payload)
        if is_final:
            require(final is None, "MULTIPLE_FINAL_EVENTS")
            final = payload
    require(len(sessions) <= 1, "MULTIPLE_NATIVE_SESSIONS")
    if final is not None:
        result["usage_models"] = list(final.get("modelUsage", {})) if isinstance(final.get("modelUsage"), dict) else []
        if adviser == "opus":
            result["native_final_success"] = final.get("subtype") == "success" and final.get("is_error") is False
            answer = final.get("result")
        else:
            result["native_final_success"] = final.get("status") == "SUCCESS"
            answer = final.get("response")
            if final.get("status") != "SUCCESS":
                result["native_error"] = True
        result["answer"] = answer if isinstance(answer, str) and answer.strip() else None
        if result["native_final_success"] and result["answer"] is not None and sessions:
            result["submission_observed"] = True
        if final.get("structured_output") is not None and result["answer"] is None:
            result["structured_output_only"] = True
    result.update(observed_models=models, observed_efforts=efforts, observed_workflows=workflows,
                  model_evidence=model_sources, session_ids=sessions, native_final_observed=final is not None)
    return result


def require_native_launcher(executable):
    # Windows may route batch files through cmd.exe even with shell=False.
    # A direct native executable keeps argument handling and ownership explicit.
    require(not IS_WINDOWS or executable.suffix.lower() == ".exe",
            "WINDOWS_NATIVE_EXECUTABLE_REQUIRED")


def windows_taskkill():
    """Locate the OS tree-termination utility without trusting PATH/SystemRoot."""
    import ctypes
    from ctypes import wintypes
    get_directory = ctypes.WinDLL("kernel32", use_last_error=True).GetSystemDirectoryW
    get_directory.argtypes = [wintypes.LPWSTR, wintypes.UINT]
    get_directory.restype = wintypes.UINT
    buffer = ctypes.create_unicode_buffer(32768)
    length = get_directory(buffer, len(buffer))
    if not 0 < length < len(buffer):
        raise OSError("WINDOWS_SYSTEM_DIRECTORY_UNAVAILABLE")
    return str(Path(buffer.value) / "taskkill.exe")


def stop_owned(process):
    if process.poll() is not None:
        return True
    if IS_WINDOWS:
        # terminate()/kill() stop only the CLI parent on Windows. Ask the OS to
        # stop this still-owned PID and its descendants, never an image name.
        tree_confirmed = False
        try:
            result = subprocess.run([windows_taskkill(), "/PID", str(process.pid), "/T", "/F"],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, shell=False, timeout=3)
            tree_confirmed = result.returncode == 0
            if not tree_confirmed and process.poll() is None:
                process.kill()
            process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            # Bound cleanup even if the OS utility is unavailable; the receipt
            # must not claim that descendants stopped when only the parent did.
            try:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                pass
            return False
        return tree_confirmed and process.poll() is not None
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            return False
    except ProcessLookupError:
        return process.poll() is not None
    return True


def summarize(receipt):
    keys = ("request_id", "adviser", "dispatch_state", "process_status", "delivery_status",
            "target_verification", "elapsed_seconds", "returncode", "error_code", "phase",
            "answer_capture_status", "acceptance_status", "independent_review")
    return {key: receipt[key] for key in keys if key in receipt}


def run(args):
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", args.request_id), "INVALID_REQUEST_ID")
    require(0 < args.timeout_seconds <= 3600, "INVALID_TIMEOUT")
    require(args.sentinel is None or (args.sentinel.strip() and "\n" not in args.sentinel and
                                    "\r" not in args.sentinel), "INVALID_SENTINEL")
    project = canonical(args.project_root)
    require(project.is_dir(), "INVALID_PROJECT_ROOT")
    # The caller explicitly selects a trusted official launcher; common installs
    # use a symlink. Resolve only this launcher, never adviser-supplied data paths.
    requested_executable = delivery._absolute(args.executable)
    require(str(requested_executable) == args.executable, "CANONICAL_PATH_REQUIRED")
    executable = canonical(str(requested_executable.resolve(strict=True)))
    require(stat.S_ISREG(executable.stat().st_mode), "EXECUTABLE_REQUIRED")
    require(os.access(executable, os.X_OK), "EXECUTABLE_REQUIRED")
    require_native_launcher(executable)
    prompt_file = canonical(args.prompt_file)
    prompt = delivery.read_file(prompt_file)
    require(bool(prompt.strip()), "EMPTY_PROMPT")
    try:
        prompt.decode("utf-8")
    except UnicodeDecodeError:
        raise delivery.DeliveryError("INVALID_PROMPT_UTF8") from None
    directory = canonical(args.run_dir, missing=True)
    require(not directory.exists(), "RUN_ALREADY_EXISTS_DO_NOT_RESEND")
    model, effort = args.model or TARGETS[args.adviser][0], args.effort or TARGETS[args.adviser][1]
    parent = continuation(args, project, directory, model, effort)
    argv = command(args.adviser, executable, model, effort, args.timeout_seconds, directory,
                   parent["session_id"] if parent else None)
    preflight_started = time.monotonic()
    checked = run_preflight(args, executable, project, prompt_file, prompt)
    if parent and parent["runtime_profile_sha256"] is not None and checked.get("ok") is True and (
            parent["runtime_profile_sha256"] != checked["runtime_profile"].get("sha256")):
        checked.update(ok=False, error_code="PARENT_RUNTIME_PROFILE_MISMATCH")
    child_env = None
    if checked.get("ok") is True:
        try:
            child_env = runtime_profile.child_environment(checked["runtime_profile"])
        except delivery.DeliveryError as error:
            checked.update(ok=False, error_code=error.code)
    preflight_elapsed = round(time.monotonic() - preflight_started, 3)
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        raise delivery.DeliveryError("RUN_ALREADY_EXISTS_DO_NOT_RESEND") from None
    started = time.monotonic()
    skill = Path(__file__).resolve().parent.parent / "SKILL.md"
    receipt = {"schema_version": 1, "request_id": args.request_id, "adviser": args.adviser,
               "created_at": now(), "dispatch_state": "NOT_SENT", "process_status": "PREPARED",
               "delivery_status": "INCOMPLETE", "target_verification": "UNKNOWN_UNVERIFIED",
               "project_root": str(project), "prompt_sha256": hashlib.sha256(prompt).hexdigest(),
               "executable_requested": args.executable, "executable_resolved": str(executable),
               "prompt_bytes": len(prompt), "argv": argv, "requested_model": model,
               "requested_effort": effort, "sentinel": args.sentinel, "timeout_seconds": args.timeout_seconds,
               "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "skill_sha256": hashlib.sha256(skill.read_bytes()).hexdigest(),
               "answer_capture_status": "NOT_CAPTURED", "acceptance_status": "PENDING_CONTROLLER_REVIEW",
               "independent_review": parent is None, "continuation_of": parent, "preflight": checked,
               "runtime_profile": checked["runtime_profile"],
               "preflight_elapsed_seconds": preflight_elapsed,
               "submission_observed": False,
               "model_evidence_provenance": "native CLI metadata, not backend-signed proof"}
    set_phase(receipt, "READY", 0)
    with (directory / "prompt.txt").open("xb") as stream:
        stream.write(prompt)
        stream.flush()
        os.fsync(stream.fileno())
    stdin_file = directory / "prompt.txt"
    if args.adviser == "gemini":
        stdin_file = directory / "stdin.jsonl"
        frame = json.dumps({"event": "user", "message": {"content": prompt.decode("utf-8")}},
                           ensure_ascii=False) + "\n"
        with stdin_file.open("xb") as stream:
            stream.write(frame.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        receipt["stdin_frame_sha256"] = hashlib.sha256(frame.encode("utf-8")).hexdigest()
    save_receipt(directory, receipt)
    if checked.get("ok") is not True:
        receipt.update(process_status="NOT_STARTED", error_code=checked.get("error_code") or "PREFLIGHT_FAILED",
                       finished_at=now(), elapsed_seconds=round(time.monotonic() - started, 3))
        set_phase(receipt, "FAILED", receipt["elapsed_seconds"])
        phase_durations(receipt, receipt["elapsed_seconds"])
        receipt["capability_cache"] = preflight.record_outcome(receipt)
        save_receipt(directory, receipt)
        return summarize(receipt)
    process = None
    try:
        with stdin_file.open("rb") as incoming, \
             (directory / "stdout.raw").open("xb") as outgoing, \
             (directory / "stderr.raw").open("xb") as errors:
            receipt.update(dispatch_state="UNKNOWN", process_status="RUNNING", started_at=now())
            save_receipt(directory, receipt)  # Persist uncertainty before any possible send.
            process = subprocess.Popen(argv, stdin=incoming, stdout=outgoing, stderr=errors,
                                       cwd=project, shell=False, start_new_session=os.name == "posix", env=child_env)
            receipt["pid"] = process.pid
            save_receipt(directory, receipt)
            live = LiveEvents(directory / "stdout.raw", args.adviser, receipt, started)
            last_saved, dirty = time.monotonic(), False
            while process.poll() is None:
                dirty = live.poll() or dirty
                elapsed = time.monotonic() - started
                if dirty and time.monotonic() - last_saved >= PROGRESS_INTERVAL:
                    receipt["elapsed_seconds"] = round(elapsed, 3)
                    phase_durations(receipt, elapsed)
                    save_receipt(directory, receipt)
                    last_saved, dirty = time.monotonic(), False
                if elapsed >= args.timeout_seconds:
                    receipt["process_status"] = "TIMEOUT"
                    receipt["termination_confirmed"] = stop_owned(process)
                    break
                time.sleep(min(POLL_INTERVAL, args.timeout_seconds - elapsed))
            live.poll()
            if receipt["process_status"] == "RUNNING":
                receipt["process_status"] = "SUCCESS" if process.returncode == 0 else "ERROR"
            receipt["returncode"] = process.returncode
    except (OSError, KeyboardInterrupt) as error:
        if process is not None and process.poll() is None:
            receipt["termination_confirmed"] = stop_owned(process)
        receipt.update(process_status="INTERRUPTED" if isinstance(error, KeyboardInterrupt) else "ERROR",
                       error_code="PROCESS_INTERRUPTED" if isinstance(error, KeyboardInterrupt) else "PROCESS_IO_ERROR")
    receipt.update(finished_at=now(), elapsed_seconds=round(time.monotonic() - started, 3))
    if process is not None:
        receipt["returncode"] = process.returncode
    stderr, events = b"", []
    try:
        raw_path = directory / "stdout.raw"
        require(raw_path.stat().st_size <= MAX_OUTPUT, "OUTPUT_TOO_LARGE")
        raw = raw_path.read_bytes()
        receipt["stdout_sha256"] = hashlib.sha256(raw).hexdigest()
        stderr_path = directory / "stderr.raw"
        require(stderr_path.stat().st_size <= MAX_OUTPUT, "OUTPUT_TOO_LARGE")
        stderr = stderr_path.read_bytes()
        receipt["stderr_sha256"] = hashlib.sha256(stderr).hexdigest()
        if (args.adviser == "gemini" and not raw and receipt.get("returncode") == 2 and
                stderr.startswith(b'Error: -p took "--output-format" as its prompt')):
            receipt.update(dispatch_state="NOT_SENT", submission_observed=False,
                           dispatch_evidence="exact_native_argument_rejection")
            raise delivery.DeliveryError("CLI_ARGUMENT_REJECTED")
        events = parse_events(raw)
        parsed = decode_result(args.adviser, events)
        if args.adviser == "gemini" and b"AGY_ERROR" in stderr:
            parsed["native_error"] = True
        if args.adviser == "gemini" and any(re.fullmatch(
            rb"\[agy\] print timeout after [^\r\n]+ with turn in progress; returning partial output", line)
            for line in stderr.splitlines()):
            parsed["native_incomplete"] = True
            receipt["stderr_diagnostic_codes"] = ["AGY_PRINT_TIMEOUT_PARTIAL"]
        answer = parsed.pop("answer")
        receipt.update(parsed)
        if parsed["submission_observed"]:
            receipt["dispatch_state"] = "SENT"
        if parent and parsed["session_ids"] != [parent["session_id"]]:
            receipt["error_code"] = "CONTINUATION_SESSION_MISMATCH"
            parsed["native_error"] = receipt["native_error"] = True
        if answer is not None:
            data = answer.encode("utf-8")
            with (directory / "answer.md").open("xb") as stream:
                stream.write(data)
            receipt.update(answer_sha256=hashlib.sha256(data).hexdigest(), answer_bytes=len(data),
                           answer_capture_status="CAPTURED")
        nonempty = [line for line in (answer or "").splitlines() if line.strip()]
        receipt["sentinel_verified"] = bool(answer) and (args.sentinel is None or nonempty[-1:] == [args.sentinel])
        models, efforts = parsed["observed_models"], parsed["observed_efforts"]
        compatible_efforts = {effort, "xhigh"} if args.adviser == "opus" else {effort}
        receipt.update(effective_effort=efforts[0] if len(efforts) == 1 else None,
                       ultracode_requested=args.adviser == "opus", actual_workflow=None)
        workflows = parsed["observed_workflows"]
        if len(workflows) == 1:
            receipt["actual_workflow"] = workflows[0]
        if ((models and models != [model]) or (efforts and any(e not in compatible_efforts for e in efforts)) or
            (args.adviser == "opus" and workflows and workflows != ["ultracode"])):
            receipt["target_verification"] = "MISMATCH"
        elif models == [model]:
            receipt["target_verification"] = "CONFIGURED"
            if efforts and (args.adviser == "gemini" or workflows == ["ultracode"]):
                receipt["target_verification"] = "VERIFIED_NATIVE_METADATA"
        complete = (receipt["process_status"] == "SUCCESS" and parsed["native_final_success"] and
                    not parsed["native_error"] and not parsed["native_denial"] and not parsed["native_incomplete"] and answer is not None and
                    receipt["sentinel_verified"])
        if complete:
            receipt["delivery_status"] = "COMPLETE"
    except (delivery.DeliveryError, OSError) as error:
        receipt["error_code"] = getattr(error, "code", "OUTPUT_UNAVAILABLE")
    classification = preflight.classify_failure(stderr, {"events": events, "receipt": receipt})
    if classification is None and receipt.get("auth_required_observed") and not receipt.get("native_final_success"):
        classification = "AUTH_REQUIRED"
    if classification:
        receipt["failure_classification"] = classification
    delivered = receipt["delivery_status"] == "COMPLETE" and receipt["target_verification"] in (
        "CONFIGURED", "VERIFIED_NATIVE_METADATA")
    terminal_phase = "DELIVERED" if delivered else "WAITING_FOR_AUTH" if (
        classification == "AUTH_REQUIRED" or receipt.get("auth_required_observed") and
        not receipt.get("native_final_success")) else "FAILED"
    set_phase(receipt, terminal_phase, receipt["elapsed_seconds"])
    phase_durations(receipt, receipt["elapsed_seconds"])
    receipt["capability_cache"] = preflight.record_outcome(receipt)
    save_receipt(directory, receipt)
    return summarize(receipt)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adviser", choices=TARGETS, required=True)
    for flag in ("executable", "project-root", "prompt-file", "run-dir", "request-id"):
        parser.add_argument("--" + flag, required=True)
    parser.add_argument("--model")
    parser.add_argument("--effort")
    parser.add_argument("--sentinel")
    parser.add_argument("--continue-from", help="Explicit new follow-up to a terminal parent's native session")
    parser.add_argument("--input-manifest")
    parser.add_argument("--runtime-profile", help="Explicit fixed profile JSON; defaults to the current user's runtime.json")
    parser.add_argument("--timeout-seconds", type=float, default=300)
    args = parser.parse_args(argv)
    try:
        result = run(args)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("delivery_status") == "COMPLETE" and result.get("target_verification") in ("CONFIGURED", "VERIFIED_NATIVE_METADATA") else 1
    except (delivery.DeliveryError, OSError, ValueError) as error:
        print(json.dumps({"error_code": getattr(error, "code", "INVALID_OR_UNAVAILABLE_INPUT")}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
