#!/usr/bin/env python3
"""Freeze a bounded native-adviser delivery; PASS validates protocol, not claims."""

import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import time

MAX_BYTES = 2 * 1024 * 1024
DELIVERABLES = {"completion.json", "report.md", "findings.json"}
IDENTITY_FIELDS = ("request_id", "adviser", "input_manifest_sha256")


class DeliveryError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise DeliveryError(code)


def _pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _constant(_):
    raise DeliveryError("INVALID_JSON")


def parse_json(data):
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_constant=_constant)
    except UnicodeDecodeError:
        raise DeliveryError("INVALID_UTF8") from None
    except (ValueError, RecursionError):
        raise DeliveryError("INVALID_JSON") from None
    require(isinstance(value, dict), "INVALID_SCHEMA")
    return value


def _is_reparse(st):
    return bool(getattr(st, "st_file_attributes", 0) & 0x400)


def _identity(st):
    # Windows path stat and descriptor stat can report different ctime values
    # immediately after creation. Compare identity, links, size, and mtime;
    # exact bytes are compared independently across the stability interval.
    return (st.st_dev, st.st_ino, st.st_mode, st.st_nlink, st.st_size,
            st.st_mtime_ns)


def _absolute(value):
    require(isinstance(value, str) and value and "\x00" not in value,
            "INVALID_PATH")
    path = Path(value)
    require(path.is_absolute(), "ABSOLUTE_PATH_REQUIRED")
    # Accept a Windows drive colon only; no ADS, traversal, or device paths.
    require(not value.startswith(("\\\\", "//")), "LOCAL_PATH_REQUIRED")
    require(all(part not in ("..", ".") and ":" not in part
                for part in path.parts[1:]), "INVALID_PATH")
    # Win32 silently aliases trailing dots/spaces. Reject before filesystem
    # access so lexical overlap checks cannot be bypassed by those spellings.
    require(all(not part.endswith((".", " ")) for part in path.parts[1:]),
            "AMBIGUOUS_WINDOWS_PATH")
    return path


def _check_chain(path, allow_missing_leaf=False):
    parts = list(reversed(path.parents)) + [path]
    for index, part in enumerate(parts):
        try:
            st = part.lstat()
        except FileNotFoundError:
            require(allow_missing_leaf and index == len(parts) - 1,
                    "PATH_NOT_FOUND")
            return
        require(not stat.S_ISLNK(st.st_mode) and not _is_reparse(st),
                "LINK_OR_REPARSE_REFUSED")
        if index < len(parts) - 1:
            require(stat.S_ISDIR(st.st_mode), "INVALID_PATH")


def _file_stat(path):
    st = path.lstat()
    require(not stat.S_ISLNK(st.st_mode) and not _is_reparse(st),
            "LINK_OR_REPARSE_REFUSED")
    require(stat.S_ISREG(st.st_mode), "NON_FILE_REFUSED")
    require(st.st_nlink == 1, "HARDLINK_REFUSED")
    require(st.st_size <= MAX_BYTES, "OVERSIZE_FILE")
    return st


def read_file(path):
    before = _file_stat(path)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        require(_identity(os.fstat(fd)) == _identity(before), "FILE_CHANGED")
        chunks = []
        total = 0
        while True:
            chunk = os.read(fd, min(65536, MAX_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            require(total <= MAX_BYTES, "OVERSIZE_FILE")
        require(_identity(os.fstat(fd)) == _identity(before), "FILE_CHANGED")
        require(_identity(_file_stat(path)) == _identity(before), "FILE_CHANGED")
        return b"".join(chunks)
    finally:
        os.close(fd)


def read_set(directory, allowed):
    _check_chain(directory)
    before = directory.lstat()
    require(stat.S_ISDIR(before.st_mode), "INVALID_OUTPUT_DIRECTORY")
    with os.scandir(directory) as entries:
        names = {entry.name for entry in entries}
    require(names <= allowed, "UNEXPECTED_FILE_SET")
    result = {name: read_file(directory / name) for name in sorted(names)}
    with os.scandir(directory) as entries:
        after_names = {entry.name for entry in entries}
    _check_chain(directory)
    require(names == after_names and _identity(before) == _identity(directory.lstat()),
            "FILE_SET_CHANGED")
    return result


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def validate_session(session):
    required = {"schema_version", *IDENTITY_FIELDS, "output_directory", "sentinel",
                "dispatch_state", "generation_stopped", "unresolved_approval"}
    require(required <= session.keys(), "INVALID_SESSION_SCHEMA")
    require(type(session["schema_version"]) is int and session["schema_version"] in (1, 2),
            "INVALID_SESSION_SCHEMA")
    require(_nonempty(session["request_id"]) and len(session["request_id"]) <= 256,
            "INVALID_SESSION_SCHEMA")
    require(session["adviser"] in ("opus", "gemini"), "INVALID_SESSION_SCHEMA")
    digest = session["input_manifest_sha256"]
    require(isinstance(digest, str) and re.fullmatch(r"[0-9a-fA-F]{64}", digest),
            "INVALID_SESSION_SCHEMA")
    require(_nonempty(session["sentinel"]) and
            not any(c in session["sentinel"] for c in "\r\n") and
            len(session["sentinel"]) <= 512, "INVALID_SESSION_SCHEMA")
    require(session["dispatch_state"] == "SENT", "NOT_SENT")
    require(session["generation_stopped"] is True, "GENERATION_NOT_STOPPED")
    require(session["unresolved_approval"] is False, "UNRESOLVED_APPROVAL")
    require(type(session.get("findings_required", False)) is bool,
            "INVALID_SESSION_SCHEMA")
    if session["schema_version"] == 2:
        names = delivery_names(session)
        require(not session.get("findings_required", False) or names["findings"] is not None,
                "INVALID_SESSION_SCHEMA")


def match_identity(document, session):
    require(type(document.get("schema_version")) is int and
            document["schema_version"] == session["schema_version"], "INVALID_SCHEMA")
    require(all(document.get(key) == session[key] for key in IDENTITY_FIELDS),
            "IDENTITY_MISMATCH")


def validate_findings(document, session):
    match_identity(document, session)
    require(set(document) == {"schema_version", *IDENTITY_FIELDS, "recommendation",
                              "findings", "evidence_read", "unknowns"}, "INVALID_FINDINGS_SCHEMA")
    require(_nonempty(document["recommendation"]), "INVALID_FINDINGS_SCHEMA")
    require(all(isinstance(document[field], list)
                for field in ("findings", "evidence_read", "unknowns")), "INVALID_FINDINGS_SCHEMA")
    require(all(isinstance(item, str) for field in ("evidence_read", "unknowns")
                for item in document[field]), "INVALID_FINDINGS_SCHEMA")
    seen = set()
    for finding in document["findings"]:
        fields = {"id", "severity", "claim", "file", "line", "trigger",
                  "evidence_kind", "counterevidence", "suggested_check"}
        require(isinstance(finding, dict) and set(finding) == fields, "INVALID_FINDING_SCHEMA")
        require(all(_nonempty(finding[key]) for key in
                    ("id", "claim", "trigger", "evidence_kind", "suggested_check")),
                "INVALID_FINDING_SCHEMA")
        require(finding["id"] not in seen, "DUPLICATE_FINDING_ID")
        seen.add(finding["id"])
        require(finding["severity"] in ("info", "low", "medium", "high", "critical"),
                "INVALID_FINDING_SCHEMA")
        require(isinstance(finding["counterevidence"], str), "INVALID_FINDING_SCHEMA")
        require(finding["file"] is None or _nonempty(finding["file"]), "INVALID_FINDING_SCHEMA")
        require(finding["line"] is None or
                (type(finding["line"]) is int and finding["line"] > 0), "INVALID_FINDING_SCHEMA")
        require(finding["file"] is not None or finding["line"] is None, "INVALID_FINDING_SCHEMA")


def validate_delivery(files, session):
    names = delivery_names(session)
    require(names["completion"] in files and names["report"] in files, "MISSING_DELIVERABLE")
    completion = parse_json(files[names["completion"]])
    match_identity(completion, session)
    require(set(completion) == {"schema_version", *IDENTITY_FIELDS, "status",
                               "report_file", "findings_file"}, "INVALID_COMPLETION_SCHEMA")
    require(completion["status"] == "complete", "INCOMPLETE_DELIVERY")
    require(completion["report_file"] == names["report"] and
            completion["findings_file"] in (None, names["findings"]), "INVALID_DELIVERABLE_NAME")
    require(not session.get("findings_required", False) or
            completion["findings_file"] == names["findings"], "REQUIRED_FINDINGS_MISSING")
    expected = {names["completion"], names["report"]}
    if completion["findings_file"] is not None:
        expected.add(names["findings"])
    require(set(files) == expected, "UNEXPECTED_OR_MISSING_DELIVERABLE")
    try:
        report = files[names["report"]].decode("utf-8")
    except UnicodeDecodeError:
        raise DeliveryError("INVALID_UTF8") from None
    require(bool(report.strip()) and session["request_id"] in report, "REPORT_REQUEST_MISSING")
    lines = report.splitlines()
    final_nonempty = next((line for line in reversed(lines) if line != ""), None)
    require(final_nonempty == session["sentinel"], "REPORT_SENTINEL_MISSING")
    if names["findings"] in files:
        validate_findings(parse_json(files[names["findings"]]), session)


def delivery_names(session):
    if session["schema_version"] == 1:
        return {"report": "report.md", "completion": "completion.json", "findings": "findings.json"}
    require(all(key in session for key in ("report_file", "completion_file", "findings_file")),
            "INVALID_SESSION_SCHEMA")
    names = {key: session[key + "_file"] for key in ("report", "completion", "findings")}
    for key, name in names.items():
        if key == "findings" and name is None:
            continue
        require(isinstance(name, str) and len(name) <= 200 and
                re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) and
                not name.endswith(".") and ".." not in name and
                name.split(".")[0].upper() not in
                {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)],
                 *[f"LPT{i}" for i in range(1, 10)]}, "INVALID_DELIVERABLE_NAME")
    selected = [name.casefold() for name in names.values() if name is not None]
    require(len(selected) == len(set(selected)), "INVALID_DELIVERABLE_NAME")
    return names


def read_named(directory, names):
    """Read only exact authorized outputs; other concurrent reviews are irrelevant."""
    _check_chain(directory)
    require(directory.is_dir(), "INVALID_OUTPUT_DIRECTORY")
    result = {}
    for name in sorted(name for name in names.values() if name is not None):
        try:
            result[name] = read_file(directory / name)
        except FileNotFoundError:
            continue
    return result


def _receipt_core(files, session):
    return {
        "schema_version": session["schema_version"],
        **{key: session[key] for key in IDENTITY_FIELDS},
        "protocol_validation": "PASS",
        "evidence_status": "adviser_claims_unverified",
        "sentinel": session["sentinel"],
        "files": {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
                  for name, data in sorted(files.items())},
    }


def _encode_json(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")


def freeze(files, session, snapshot):
    _check_chain(snapshot, allow_missing_leaf=True)
    core = _receipt_core(files, session)
    if snapshot.exists():
        frozen = read_set(snapshot, DELIVERABLES | {"receipt.json"})
        require("receipt.json" in frozen, "PARTIAL_SNAPSHOT")
        receipt = parse_json(frozen.pop("receipt.json"))
        captured_at = receipt.pop("captured_at_utc", None)
        require(isinstance(captured_at, str) and
                re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z", captured_at),
                "INVALID_SNAPSHOT_RECEIPT")
        require(frozen == files and receipt == core, "SNAPSHOT_CONFLICT")
        return "RECOVERED_IDENTICAL"
    snapshot.mkdir()
    # Receipt is the final commit marker. A interrupted write stays explicit;
    # collection never fills, repairs, deletes, or overwrites a partial archive.
    try:
        for name, data in sorted(files.items()):
            with (snapshot / name).open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        receipt = {**core, "captured_at_utc": dt.datetime.now(dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ")}
        with (snapshot / "receipt.json").open("xb") as stream:
            stream.write(_encode_json(receipt))
            stream.flush()
            os.fsync(stream.fileno())
        saved = read_set(snapshot, DELIVERABLES | {"receipt.json"})
        require(saved.pop("receipt.json") == _encode_json(receipt) and saved == files,
                "SNAPSHOT_WRITE_MISMATCH")
    except OSError:
        raise DeliveryError("SNAPSHOT_WRITE_FAILED_PARTIAL") from None
    return "CREATED"


def save_receipt(files, session, receipt_path):
    """Create-only integrity receipt; an identical retry never rewrites it."""
    _check_chain(receipt_path, allow_missing_leaf=True)
    core = _receipt_core(files, session)
    if receipt_path.exists():
        receipt = parse_json(read_file(receipt_path))
        captured = receipt.pop("captured_at_utc", None)
        require(isinstance(captured, str) and
                re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z", captured),
                "INVALID_RECEIPT")
        require(receipt == core, "RECEIPT_CONFLICT")
        return "RECOVERED_IDENTICAL"
    receipt = {**core, "captured_at_utc": dt.datetime.now(dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ")}
    encoded = _encode_json(receipt)
    with receipt_path.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    require(read_file(receipt_path) == encoded, "RECEIPT_WRITE_MISMATCH")
    return "CREATED"


def collect(session_path, snapshot_dir=None, stable_seconds=1, receipt_file=None):
    require(isinstance(stable_seconds, (int, float)) and not isinstance(stable_seconds, bool)
            and math.isfinite(stable_seconds) and 0 <= stable_seconds <= 10,
            "INVALID_STABILITY_INTERVAL")
    session_path = _absolute(str(session_path))
    _check_chain(session_path)
    session_path = session_path.resolve(strict=True)
    session_bytes = read_file(session_path)
    session = parse_json(session_bytes)
    validate_session(session)
    output = _absolute(session["output_directory"])
    _check_chain(output)
    output = output.resolve(strict=True)
    if session["schema_version"] == 2:
        require(receipt_file is not None and snapshot_dir is None, "V2_RECEIPT_REQUIRED")
        receipt = _absolute(str(receipt_file))
        _check_chain(receipt, allow_missing_leaf=True)
        receipt = receipt.resolve(strict=False)
        names = delivery_names(session)
        selected = {output / name for name in names.values() if name is not None}
        require(session_path not in selected and receipt not in selected and
                receipt != session_path, "CONTROLLER_PATH_OVERLAP")
        first = read_named(output, names)
        time.sleep(stable_seconds)
        second = read_named(output, names)
        require(first == second, "DELIVERY_CHANGED_DURING_STABILITY")
        require(read_file(session_path) == session_bytes, "SESSION_CHANGED")
        validate_delivery(second, session)
        action = save_receipt(second, session, receipt)
        return {"status": "PASS", "scope": "protocol_only", "receipt_action": action,
                **{key: session[key] for key in IDENTITY_FIELDS},
                "file_count": len(second), "evidence_status": "adviser_claims_unverified"}
    require(snapshot_dir is not None and receipt_file is None, "V1_SNAPSHOT_REQUIRED")
    snapshot = _absolute(str(snapshot_dir))
    _check_chain(snapshot, allow_missing_leaf=True)
    # Resolve existing paths only after refusing links/reparse points. On
    # Windows this also expands existing 8.3 aliases before overlap checks.
    snapshot = snapshot.resolve(strict=False)
    require(not session_path.is_relative_to(output), "SESSION_INSIDE_ADVISER_OUTPUT")
    require(not snapshot.is_relative_to(output) and not output.is_relative_to(snapshot),
            "SNAPSHOT_OVERLAPS_ADVISER_OUTPUT")
    first = read_set(output, DELIVERABLES)
    time.sleep(stable_seconds)
    second = read_set(output, DELIVERABLES)
    require(first == second, "DELIVERY_CHANGED_DURING_STABILITY")
    require(read_file(session_path) == session_bytes, "SESSION_CHANGED")
    validate_delivery(second, session)
    action = freeze(second, session, snapshot)
    return {"status": "PASS", "scope": "protocol_only", "snapshot_action": action,
            **{key: session[key] for key in IDENTITY_FIELDS},
            "file_count": len(second), "evidence_status": "adviser_claims_unverified"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--snapshot-dir")
    parser.add_argument("--receipt-file")
    parser.add_argument("--stable-seconds", type=float, default=1)
    args = parser.parse_args(argv)
    try:
        result = collect(args.session, args.snapshot_dir, args.stable_seconds, args.receipt_file)
    except DeliveryError as exc:
        print(json.dumps({"status": "FAIL", "code": exc.code, "scope": "protocol_only"}))
        return 2
    except (OSError, ValueError, TypeError, OverflowError):
        # Never print file contents, source excerpts, or arbitrary OS diagnostics.
        print(json.dumps({"status": "FAIL", "code": "IO_OR_SCHEMA_ERROR", "scope": "protocol_only"}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
