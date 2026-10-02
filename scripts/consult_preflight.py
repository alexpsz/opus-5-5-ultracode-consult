#!/usr/bin/env python3
"""Cheap local dispatch checks; never logs in, calls a model, or edits policy."""
import argparse
import datetime as dt
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import tempfile

import collect_delivery as delivery

MAX_INPUT = 32 * 1024 * 1024


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    path = delivery._absolute(str(value))
    delivery._check_chain(path)
    delivery.require(str(path.resolve()) == str(path), "CANONICAL_PATH_REQUIRED")
    return path


def input_digest(path):
    path = canonical(path)
    before = path.stat()
    delivery.require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
                     "REGULAR_INPUT_REQUIRED")
    delivery.require(before.st_size <= MAX_INPUT, "INPUT_TOO_LARGE")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        delivery.require((before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino),
                         "INPUT_CHANGED")
        raw = stream.read(MAX_INPUT + 1)
        after = os.fstat(stream.fileno())
    delivery.require((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
                     and len(raw) == before.st_size, "INPUT_CHANGED")
    return {"path": str(path), "bytes": len(raw), "sha256": digest(raw)}


def load_settings(path):
    if not path.exists() and not path.is_symlink():
        return {}, {"path": str(path), "present": False}
    data = delivery.parse_json(delivery.read_file(canonical(path)))
    perms = data.get("permissions", {})
    delivery.require(isinstance(perms, dict), "INVALID_PERMISSION_SETTINGS")
    for name in ("allow", "deny", "ask"):
        rules = perms.get(name, [])
        delivery.require(isinstance(rules, list) and all(isinstance(x, str) for x in rules),
                         "INVALID_PERMISSION_SETTINGS")
    return data, {"path": str(path), "present": True,
                  "semantic_sha256": digest(json.dumps(data, sort_keys=True,
                                                       separators=(",", ":")).encode())}


def network_policy(adviser, project):
    home = Path.home()
    if adviser == "gemini":
        paths = [home / ".gemini/antigravity-cli/settings.json"]
    else:
        config = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(home / ".claude")))
        delivery.require(config.is_absolute() and ".." not in config.parts, "INVALID_CLAUDE_CONFIG_DIR")
        paths = [config / "settings.json", project / ".claude/settings.json",
                 project / ".claude/settings.local.json"]
        if os.name == "posix":
            paths.append(Path("/Library/Application Support/ClaudeCode/managed-settings.json")
                         if os.uname().sysname == "Darwin" else
                         Path("/etc/claude-code/managed-settings.json"))
    documents, fingerprints, restrictions = [], [], []
    for path in paths:
        data, proof = load_settings(path)
        documents.append(data)
        fingerprints.append(proof)
        for action in ("deny", "ask"):
            for rule in data.get("permissions", {}).get(action, []):
                relevant = (rule.startswith("read_url(") if adviser == "gemini" else
                            rule.startswith("WebSearch") or rule.startswith("WebFetch"))
                if relevant:
                    restrictions.append({"source": str(path), "action": action, "rule": rule})
    error = None
    if adviser == "gemini" and "read_url(*)" not in documents[0].get("permissions", {}).get("allow", []):
        error = "WEB_DEFAULT_MISSING"
    broad = {"read_url(*)"} if adviser == "gemini" else {
        "WebSearch", "WebFetch", "WebSearch(*)", "WebFetch(*)", "WebFetch(domain:*)"}
    if any(x["rule"] in broad for x in restrictions):
        error = "WEB_POLICY_BLOCKED"
    if adviser == "opus" and any(d.get("allowManagedPermissionRulesOnly") is True for d in documents):
        error = "WEB_MANAGED_POLICY_REQUIRES_REVIEW"
    return {"ok": error is None, "error_code": error,
            "default": "read_url(*)" if adviser == "gemini" else "--allowedTools WebSearch WebFetch",
            "settings": fingerprints, "restrictions": restrictions,
            "effective_access": "UNVERIFIED_UNTIL_NATIVE_TOOL_RESULT",
            "permissions": documents[0].get("permissions", {})}


def file_access(path, permissions, project):
    def matches(rule, actions):
        matched = re.fullmatch(r"(read_file|write_file)\((.*)\)", rule)
        if not matched or matched[1] not in actions:
            return False
        target = matched[2]
        if target == "*":
            return True
        base = Path(target)
        if not base.is_absolute():
            base = project / base
        # Be conservative about glob/relative traversal semantics; do not expand a grant.
        return ".." not in base.parts and (path == base or base in path.parents)
    if any(matches(r, {"read_file"}) for k in ("deny", "ask") for r in permissions.get(k, [])):
        return "EXPLICIT_RESTRICTION"
    if path == project or project in path.parents or any(
            matches(r, {"read_file", "write_file"}) for r in permissions.get("allow", [])):
        return "CONFIGURED"
    return "EXTERNAL_GRANT_MISSING"


def check_inputs(adviser, project, prompt, manifest_arg, permissions):
    headers = {}
    for name in ("PACKET", "PACKET_SHA256", "INPUT_MANIFEST", "INPUT_MANIFEST_SHA256"):
        values = re.findall(r"^" + name + r":\s*(\S[^\r\n]*)$", prompt.decode("utf-8"), re.M)
        delivery.require(len(values) <= 1, "AMBIGUOUS_DISPATCH_HEADER")
        if values:
            headers[name] = values[0].strip()
    if manifest_arg and "INPUT_MANIFEST" in headers:
        delivery.require(str(manifest_arg) == headers["INPUT_MANIFEST"], "MANIFEST_PATH_MISMATCH")
    manifest_name = manifest_arg or headers.get("INPUT_MANIFEST")
    result = {"status": "INLINE_OR_NO_MANIFEST", "inputs": [], "outside_project": [], "restricted_inputs": []}
    paths = []
    for label, name in (("PACKET", headers.get("PACKET")), ("INPUT_MANIFEST", manifest_name)):
        if name:
            item = input_digest(name)
            if label + "_SHA256" in headers:
                delivery.require(item["sha256"] == headers[label + "_SHA256"], label + "_HASH_MISMATCH")
            result[label.lower()] = item
            if label == "PACKET" or "INPUT_MANIFEST" in headers:
                paths.append(Path(item["path"]))
    if manifest_name:
        data = delivery.parse_json(delivery.read_file(canonical(manifest_name)))
        if "root" in data:
            delivery.require(data["root"] == str(project), "MANIFEST_ROOT_MISMATCH")
        inputs = data.get("inputs")
        delivery.require(isinstance(inputs, list), "MANIFEST_INPUTS_REQUIRED")
        delivery.require(len(inputs) <= 256, "TOO_MANY_INPUTS")
        for entry in inputs:
            delivery.require(isinstance(entry, dict), "INVALID_MANIFEST_ENTRY")
            relative, absolute = entry.get("project_relative_path"), entry.get("absolute_path")
            delivery.require(relative is None or isinstance(relative, str), "INVALID_RELATIVE_INPUT")
            delivery.require(absolute is None or isinstance(absolute, str), "INVALID_ABSOLUTE_INPUT")
            delivery.require(isinstance(relative, str) or isinstance(absolute, str), "INPUT_PATH_REQUIRED")
            if relative is not None:
                delivery.require(not Path(relative).is_absolute() and ".." not in Path(relative).parts,
                                 "INVALID_RELATIVE_INPUT")
                expected = str(project / relative)
                delivery.require(absolute is None or absolute == expected, "INPUT_PATH_MISMATCH")
            else:
                expected = absolute
            proof = input_digest(expected)
            delivery.require(proof["bytes"] == entry.get("bytes") and proof["sha256"] == entry.get("sha256"),
                             "INPUT_HASH_OR_SIZE_MISMATCH")
            proof["role"] = entry.get("role")
            result["inputs"].append(proof)
            paths.append(Path(proof["path"]))
        result["status"] = "HASHES_VERIFIED_ACCESS_UNVERIFIED"
    for path in paths:
        if adviser == "gemini":
            access = file_access(path, permissions, project)
            if access == "EXPLICIT_RESTRICTION":
                result["restricted_inputs"].append(str(path))
            elif access == "EXTERNAL_GRANT_MISSING":
                result["outside_project"].append(str(path))
    return result


def cache_root():
    return Path.home() / ".cache/codex-consultations"


def check_host_context():
    """Probe only required local capabilities, not authentication or sandbox escape."""
    result = {"ok": False, "auth_tested": False, "sandbox_escape_verified": False,
              "loopback_bind": False, "runtime_state_write": False}
    temporary = None
    stage = "loopback_bind"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
            connection.bind(("127.0.0.1", 0))  # Never listen or contact a remote host.
        result["loopback_bind"] = True
        stage = "runtime_state_write"
        root = cache_root()
        ancestor = root
        while not ancestor.exists():
            ancestor = ancestor.parent
        canonical(ancestor)
        root.mkdir(parents=True, mode=0o700, exist_ok=True)
        canonical(root)
        fd, temporary = tempfile.mkstemp(prefix=".preflight-", dir=root)
        with os.fdopen(fd, "wb") as stream:
            stream.write(b"local runtime readiness\n")
        os.unlink(temporary)
        temporary = None
        result.update(ok=True, runtime_state_write=True)
    except (OSError, delivery.DeliveryError) as exc:
        result.update(failed_check=stage, error_code="HOST_CONTEXT_REQUIRED" if
                      isinstance(exc, PermissionError) or getattr(exc, "errno", None) in (errno.EPERM, errno.EACCES)
                      else "HOST_RUNTIME_STATE_UNAVAILABLE")
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    return result


def read_cache(key):
    path = cache_root() / (key + ".json")
    try:
        data = delivery.parse_json(delivery.read_file(canonical(path)))
        return {"status": "HIT", "path": str(path), "previous": data,
                "auth_current": "UNVERIFIED", "skip_native_auth": False}
    except (OSError, delivery.DeliveryError):
        return {"status": "MISS", "path": str(path), "auth_current": "UNVERIFIED"}


def check_run(*, adviser, executable, project, prompt_file, prompt, input_manifest=None):
    result = {"ok": False, "error_code": None, "checks": {}, "warnings": [],
              "input_manifest": None, "cache": {"status": "NOT_CHECKED"}}
    try:
        policy = network_policy(adviser, project)
        permissions = policy.pop("permissions")
        result["checks"]["network"] = policy
        exe = executable.stat()
        identity = {"path": str(executable), "size": exe.st_size, "mtime_ns": exe.st_mtime_ns,
                    "inode": exe.st_ino, "device": exe.st_dev}
        result["checks"]["executable"] = identity
        result["cache_key"] = digest(json.dumps({"adviser": adviser, "project": str(project),
                                                "executable": identity, "settings": policy["settings"]},
                                               sort_keys=True).encode())
        result["cache"] = read_cache(result["cache_key"])
        if not policy["ok"]:
            result["error_code"] = policy["error_code"]
            return result
        if policy["restrictions"]:
            result["warnings"].append("DOMAIN_SPECIFIC_WEB_RULES_PRESERVED")
        host = check_host_context()
        result["checks"]["host"] = host
        if not host["ok"]:
            result["error_code"] = host["error_code"]
            return result
        result["input_manifest"] = check_inputs(adviser, project, prompt, input_manifest, permissions)
        if result["input_manifest"]["restricted_inputs"]:
            result["error_code"] = "INPUT_POLICY_BLOCKED"
            return result
        if result["input_manifest"]["outside_project"]:
            result["error_code"] = "INPUTS_OUTSIDE_PROJECT_NEED_STAGING"
            return result
        result["ok"] = True
    except (OSError, ValueError, delivery.DeliveryError) as exc:
        result["error_code"] = str(exc) if isinstance(exc, delivery.DeliveryError) else "PREFLIGHT_LOCAL_READ_FAILED"
    return result


def classify_failure(stderr, native):
    receipt = native.get("receipt", {})
    if receipt.get("native_final_success") and not receipt.get("native_error"):
        return None  # A transient startup auth warning is not a failed login.
    if receipt.get("auth_required_observed") is True:
        return "AUTH_REQUIRED"
    text = stderr.decode("utf-8", errors="replace").lower()
    # Only structural error messages supplement stderr, never generated prose.
    for event in native.get("events", []):
        if not isinstance(event, dict):
            continue
        if event.get("type") == "error" or event.get("event") == "error":
            text += "\n" + json.dumps(event).lower()
    if any(x in text for x in ("operation not permitted", "eacces", "eperm", "permission denied")) and any(
            x in text for x in ("listen", "bind", "keychain", ".gemini", ".claude", "sandbox")):
        return "HOST_CONTEXT_REQUIRED"
    if any(x in text for x in ("please log in", "please login", "please sign in", "not signed in",
                               "not logged in", "not authenticated", "authentication required", "login required",
                               "run /login", "invalid authentication")):
        return "AUTH_REQUIRED"
    if any(x in text for x in ("model not found", "unknown model", "model is not available", "invalid model")):
        return "MODEL_UNAVAILABLE"
    return None


def record_outcome(receipt):
    preflight = receipt.get("preflight", {})
    key = preflight.get("cache_key")
    if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key):
        return {"status": "NOT_RECORDED"}
    if (receipt.get("error_code") == "AUTH_REQUIRED" or receipt.get("failure_classification") == "AUTH_REQUIRED"
            or receipt.get("phase") == "WAITING_FOR_AUTH"):
        status = "AUTH_REQUIRED"
    elif receipt.get("native_final_observed") and receipt.get("session_ids"):
        status = "NATIVE_RUN_OBSERVED"
    else:
        return {"status": "NOT_RECORDED"}
    data = {"schema_version": 1, "status": status, "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "request_id": receipt.get("request_id"), "adviser": receipt.get("adviser"),
            "project_root": receipt.get("project_root"), "runner_sha256": receipt.get("runner_sha256"),
            "requested_model": receipt.get("requested_model"), "observed_models": receipt.get("observed_models", []),
            "delivery_status": receipt.get("delivery_status"),
            "auth_current": "UNVERIFIED", "policy_recheck_required": True}
    temporary = None
    try:
        root = cache_root()
        # Check existing ancestors before creating any directories.
        ancestor = root
        while not ancestor.exists():
            ancestor = ancestor.parent
        canonical(ancestor)
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        canonical(root)
        path = root / (key + ".json")
        if path.exists() or path.is_symlink():
            canonical(path)
            delivery.require(path.stat().st_nlink == 1, "CACHE_LINK_REJECTED")
        fd, temporary = tempfile.mkstemp(prefix=".receipt-", dir=root)
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
        return {"status": "RECORDED", "path": str(path)}
    except (OSError, delivery.DeliveryError):
        return {"status": "CACHE_UNWRITABLE", "impact": "delivery_unaffected"}
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adviser", choices=("opus", "gemini"), required=True)
    parser.add_argument("--executable", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--input-manifest")
    args = parser.parse_args()
    result = check_run(adviser=args.adviser, executable=Path(args.executable).resolve(strict=True),
                       project=canonical(args.project_root), prompt_file=canonical(args.prompt_file),
                       prompt=delivery.read_file(canonical(args.prompt_file)), input_manifest=args.input_manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
