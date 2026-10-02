#!/usr/bin/env python3
"""Offline checkpoint/CAS helper. Resolve trusted paths before use; never send.

One cooperating writer uses an exclusive .lock and atomic replacement. CAS also
checks for out-of-band edits, but cannot fence a hostile writer at rename time.
A crash may leave a lock; inspect the owning process before manual removal.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

import collect_delivery as delivery

MAX_HISTORY = 25
REQUIRED = {"phase", "dispatch_state", "generation_stopped", "unresolved_approval",
            "input_access_verified", "input_access_status"}
BOOLEANS = {"generation_stopped", "unresolved_approval", "input_access_verified",
            "submission_observed", "controller_send_attempted", "ui_evidence_conflict"}
OPTIONAL = {"blocker", "next_check_at", "recovery_count", "conversation_locator", "evidence"}
MIRRORS = {"dispatch_state", "generation_stopped", "unresolved_approval",
           "input_access_verified", "input_access_status", "conversation_locator",
           "ui_evidence_conflict", "submission_observed", "controller_send_attempted"}
STATIC = {"schema_version", "request_id", "adviser", "input_manifest_sha256",
          "output_directory", "report_file", "completion_file", "findings_file",
          "findings_required", "sentinel", "packet_sha256", "request_wrapper_sha256",
          "requested_model", "requested_effort", "project_root", "branch", "head"}


def require(ok, code):
    delivery.require(ok, code)


def stamp(value):
    require(isinstance(value, str), "INVALID_TIMESTAMP")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(parsed.tzinfo is not None, "TIMEZONE_REQUIRED")
        return parsed
    except ValueError:
        raise delivery.DeliveryError("INVALID_TIMESTAMP") from None


def path_arg(value):
    path = delivery._absolute(value)
    require(str(path) == value, "CANONICAL_PATH_REQUIRED")
    delivery._check_chain(path)
    require(str(path.resolve(strict=True)) == str(path), "CANONICAL_PATH_REQUIRED")
    return path


def read_json(path):
    raw = delivery.read_file(path)
    return delivery.parse_json(raw), hashlib.sha256(raw).hexdigest()


def validate_current(current, session, path):
    require(isinstance(current, dict) and REQUIRED <= current.keys() and
            current.keys() <= REQUIRED | BOOLEANS | OPTIONAL | {"event_id", "observed_at"},
            "INVALID_CURRENT")
    require(isinstance(current["phase"], str) and
            re.fullmatch(r"[a-z][a-z0-9_]{0,63}", current["phase"]), "INVALID_PHASE")
    require(current["dispatch_state"] in ("NOT_SENT", "UNKNOWN", "SENT"), "INVALID_DISPATCH")
    for key in BOOLEANS & current.keys():
        require(type(current[key]) is bool, "BOOLEAN_REQUIRED")
    status = current["input_access_status"]
    require(status in ("unknown", "partial", "verified", "unavailable"), "INVALID_INPUT_STATUS")
    require(current["input_access_verified"] == (status == "verified"), "INPUT_STATUS_CONFLICT")
    require(not (current.get("ui_evidence_conflict", False) and
                 current["generation_stopped"]), "UI_EVIDENCE_CONFLICT")
    if current["dispatch_state"] == "SENT":
        require(current.get("submission_observed") is True and
                isinstance(current.get("conversation_locator"), str) and
                bool(current["conversation_locator"].strip()), "SUBMISSION_EVIDENCE_REQUIRED")
    if current["phase"] == "manual_handoff":
        require(current["dispatch_state"] == "UNKNOWN" and
                current.get("controller_send_attempted") is False, "INVALID_MANUAL_HANDOFF")
    if current["phase"] == "complete":
        require(current["dispatch_state"] == "SENT" and current["generation_stopped"] and
                not current["unresolved_approval"], "INCOMPLETE_CURRENT")
    if current.get("next_check_at") is not None:
        stamp(current["next_check_at"])
    require(type(current.get("recovery_count", 0)) is int and
            current.get("recovery_count", 0) >= 0, "INVALID_RECOVERY_COUNT")
    require(current.get("blocker") is None or isinstance(current["blocker"], str), "INVALID_BLOCKER")
    evidence = current.get("evidence", [])
    require(isinstance(evidence, list) and len(evidence) <= 100, "INVALID_EVIDENCE")
    for item in evidence:
        require(isinstance(item, dict) and
                {"adviser", "session", "observed_at", "source"} <= item.keys(), "INVALID_EVIDENCE")
        require(item["adviser"] == session["adviser"] and item["session"] == str(path),
                "EVIDENCE_PROVENANCE_MISMATCH")
        stamp(item["observed_at"])
        require(isinstance(item["source"], str) and bool(item["source"].strip()), "INVALID_EVIDENCE")


def load_session(path):
    session, digest = read_json(path)
    require(type(session.get("schema_version")) is int and
            session["schema_version"] in (1, 2), "INVALID_SESSION_SCHEMA")
    require(session.get("adviser") in ("opus", "gemini") and
            isinstance(session.get("request_id"), str), "INVALID_SESSION_SCHEMA")
    require(session.get("dispatch_state") in ("NOT_SENT", "UNKNOWN", "SENT"), "INVALID_DISPATCH")
    state = session.get("controller_state")
    if state is not None:
        require(isinstance(state, dict) and type(state.get("version")) is int and
                state["version"] == 1 and isinstance(state.get("history"), list), "INVALID_CONTROLLER_STATE")
        require(len(state["history"]) <= MAX_HISTORY and
                all(isinstance(item, dict) for item in state["history"]), "INVALID_HISTORY")
        validate_current(state.get("current"), session, path)
        require({"event_id", "observed_at"} <= state["current"].keys(), "INVALID_CONTROLLER_STATE")
        stamp(state["current"]["observed_at"])
        for key in MIRRORS:
            require((key in session) == (key in state["current"]) and
                    type(session.get(key)) is type(state["current"].get(key)) and
                    session.get(key) == state["current"].get(key), "MIRROR_MISMATCH")
    return session, digest


def inspect(path, now):
    session, digest = load_session(path)
    state = session.get("controller_state")
    current = state["current"] if state else session
    legacy = state is None
    names = delivery.delivery_names(session)
    directory = path_arg(session["output_directory"])
    require(directory.is_dir(), "INVALID_OUTPUT_DIRECTORY")
    completion = directory / names["completion"]
    require(completion != path, "CONTROLLER_OUTPUT_OVERLAP")
    metadata = None
    try:
        st = delivery._file_stat(completion)  # Never open reports or completion content.
        metadata = {"size": st.st_size, "mtime_ns": st.st_mtime_ns}
    except FileNotFoundError:
        pass
    due = current.get("next_check_at") is None or stamp(current["next_check_at"]) <= now
    dispatch = current["dispatch_state"]
    if legacy:
        action = "MIGRATE_LEGACY"
    elif not due:
        action = "WAIT"
    elif current.get("ui_evidence_conflict"):
        action = "RESOLVE_UI_CONFLICT"
    elif current["unresolved_approval"]:
        action = "RESOLVE_APPROVAL"
    elif dispatch == "UNKNOWN":
        action = "RECOVER_SUBMISSION"
    elif dispatch == "NOT_SENT":
        action = "PREPARE"
    elif current["phase"] == "complete":
        action = "DONE_RECORDED"
    elif metadata:
        action = "COLLECT" if current["generation_stopped"] else "CHECK_UI_THEN_COLLECT"
    else:
        action = "CHECK_PROGRESS"
    return {"session": str(path), "sha256": digest, "adviser": session["adviser"],
            "request_id": session["request_id"], "dispatch_state": dispatch,
            "phase": current.get("phase", "legacy"), "legacy": legacy,
            "legacy_input_type": type(current.get("input_access_verified")).__name__ if legacy else None,
            "due": due, "next_check_at": current.get("next_check_at"),
            "action": action, "completion_metadata": metadata}


def update(path, event):
    require(isinstance(event, dict) and
            {"expected_sha256", "event_id", "observed_at", "current"} <= event.keys() and
            event.keys() <= {"expected_sha256", "event_id", "observed_at", "current", "migrate_legacy"},
            "INVALID_EVENT")
    require(isinstance(event["event_id"], str) and bool(event["event_id"].strip()), "INVALID_EVENT_ID")
    observed = stamp(event["observed_at"])
    require(type(event.get("migrate_legacy", False)) is bool, "BOOLEAN_REQUIRED")
    lock = path.with_name(path.name + ".lock")
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        raise delivery.DeliveryError("SESSION_LOCKED") from None
    temporary = None
    try:
        with os.fdopen(fd, "w") as owner:
            owner.write(str(os.getpid()) + "\n")
        session, digest = load_session(path)
        require(event["expected_sha256"] == digest, "CAS_MISMATCH")
        previous = session.get("controller_state")
        require(previous is not None or event.get("migrate_legacy") is True, "EXPLICIT_MIGRATION_REQUIRED")
        require(isinstance(event["current"], dict), "INVALID_CURRENT")
        current = dict(event["current"])
        require(not ({"event_id", "observed_at"} & current.keys()), "RESERVED_CURRENT_FIELDS")
        validate_current(current, session, path)
        old = previous["current"] if previous else {k: v for k, v in session.items() if k not in STATIC}
        ranks = {"NOT_SENT": 0, "UNKNOWN": 1, "SENT": 2}
        require(ranks[current["dispatch_state"]] >= ranks[session["dispatch_state"]], "DISPATCH_REGRESSION")
        if previous:
            require(observed >= stamp(old["observed_at"]), "STALE_EVENT")
            require(current.get("recovery_count", 0) >= old.get("recovery_count", 0), "RECOVERY_REGRESSION")
            require(all(event["event_id"] != entry.get("event_id")
                        for entry in previous["history"] + [old]), "DUPLICATE_EVENT")
        current.update(event_id=event["event_id"], observed_at=event["observed_at"])
        history = ((previous["history"] if previous else []) + [old])[-MAX_HISTORY:]
        result = {k: v for k, v in session.items() if k in STATIC}
        result.update({k: current[k] for k in MIRRORS if k in current})
        result["controller_state"] = {"version": 1, "current": current, "history": history}
        raw = (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
        require(len(raw) <= delivery.MAX_BYTES, "OVERSIZE_FILE")
        fd, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
        temporary = Path(name)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        path_arg(str(path))
        require(read_json(path)[1] == digest, "CAS_MISMATCH")
        os.replace(temporary, path)
        temporary = None
        return {"session": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                "dispatch_state": current["dispatch_state"], "phase": current["phase"],
                "event_id": event["event_id"]}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        lock.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    read = commands.add_parser("inspect")
    read.add_argument("--session", action="append", required=True)
    read.add_argument("--now", help="Timezone-aware ISO timestamp (default: current UTC)")
    write = commands.add_parser("update")
    write.add_argument("--session", required=True)
    write.add_argument("--event-file", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            now = stamp(args.now) if args.now else dt.datetime.now(dt.timezone.utc)
            result = []
            for item in args.session:
                try:
                    result.append(inspect(path_arg(item), now))
                except (delivery.DeliveryError, OSError, ValueError, TypeError) as error:
                    result.append({"session": item, "error": getattr(error, "code", "INVALID_OR_UNAVAILABLE_INPUT")})
        else:
            event, _ = read_json(path_arg(args.event_file))
            result = update(path_arg(args.session), event)
        print(json.dumps(result, ensure_ascii=False))
        return int(isinstance(result, list) and any("error" in item for item in result))
    except (delivery.DeliveryError, OSError, ValueError, TypeError) as error:
        print(json.dumps({"error": getattr(error, "code", "INVALID_OR_UNAVAILABLE_INPUT")}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
