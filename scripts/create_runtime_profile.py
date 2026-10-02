#!/usr/bin/env python3
"""Create a local fixed runtime profile once; never authenticate or edit CLI policy."""
import argparse
import json
import os
from pathlib import Path
import sys

import collect_delivery as delivery
import runtime_profile as runtime


def binding(value):
    launcher = runtime.absolute(value)
    resolved = launcher.resolve(strict=True)
    delivery.require(resolved.is_file() and os.access(resolved, os.X_OK), "EXECUTABLE_REQUIRED")
    if runtime.is_windows():
        delivery.require(resolved.suffix.lower() == ".exe", "NATIVE_WINDOWS_EXE_REQUIRED")
    return {"launcher": str(launcher), "resolved": str(resolved)}


def stable_path(value):
    """Remove empty/duplicate entries, refusing relative or transient Codex paths."""
    entries = []
    seen = set()
    for item in value.split(os.pathsep):
        if not item:
            continue
        entry = os.path.normpath(item)
        runtime.absolute(entry)
        # These injected execution directories change between Codex turns.
        parts = Path(entry).parts
        if any(parts[i:i + 2] == (".codex", "tmp") and parts[i + 2].startswith("arg0")
               for i in range(len(parts) - 2)):
            continue
        key = os.path.normcase(entry)
        if key not in seen:
            entries.append(entry)
            seen.add(key)
    delivery.require(bool(entries), "RUNTIME_PROFILE_INVALID")
    return os.pathsep.join(entries)


def build_profile(opus_executable, gemini_executable, *, path_value=None):
    inherited = dict(os.environ)
    home = str(Path.home())
    executable_map = {"opus": binding(opus_executable), "gemini": binding(gemini_executable)}
    if runtime.is_windows():
        fixed = {key: inherited.get(key) or None for key in runtime.WINDOWS_ENV_KEYS}
        config = {"schema_version": 2, "host_mode": "windows-user-session",
                  "identity": {"kind": "windows-process-token-sid", "sid": runtime.windows_sid()}}
    else:
        delivery.require(sys.platform == "darwin", "RUNTIME_PROFILE_HOST_UNSUPPORTED")
        fixed = {key: inherited.get(key) or None for key in runtime.SAFE_ENV_KEYS}
        # USER/LOGNAME may be absent from a GUI host, but never guess another account.
        import pwd
        account = pwd.getpwuid(runtime.posix_uid()).pw_name
        fixed["USER"] = fixed["USER"] or account
        fixed["LOGNAME"] = fixed["LOGNAME"] or account
        config = {"schema_version": 1, "host_mode": "macos-user-session", "uid": runtime.posix_uid()}
    fixed["PATH"] = stable_path(inherited.get("PATH", "") if path_value is None else path_value)
    config.update(home=home, environment=fixed, executables=executable_map)
    for adviser, executable in executable_map.items():
        checked = runtime.validate_data(config, adviser=adviser, launcher=Path(executable["launcher"]),
                                        resolved=Path(executable["resolved"]), environment=inherited)
        delivery.require(checked["ok"], checked["error_code"])
    return config


def create_profile(config, output):
    """Create-only publication after validation; existing files are never overwritten."""
    path = runtime.absolute(str(output))
    ancestor = path.parent
    while not ancestor.exists():
        ancestor = ancestor.parent
    delivery._check_chain(ancestor)
    delivery.require(str(ancestor.resolve()) == str(ancestor), "RUNTIME_PROFILE_INVALID")
    delivery.require(not path.exists() and not path.is_symlink(), "RUNTIME_PROFILE_ALREADY_EXISTS")
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    delivery._check_chain(path.parent)
    raw = (json.dumps(config, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise delivery.DeliveryError("RUNTIME_PROFILE_ALREADY_EXISTS") from None
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--opus-executable", required=True, help="Absolute trusted official Claude launcher")
    parser.add_argument("--gemini-executable", required=True, help="Absolute trusted official AGY launcher")
    parser.add_argument("--output", help="Absolute create-only profile destination; defaults under current home")
    parser.add_argument("--path", dest="path_value", help="Explicit stable PATH; otherwise normalize current PATH")
    args = parser.parse_args()
    try:
        config = build_profile(args.opus_executable, args.gemini_executable, path_value=args.path_value)
        output = create_profile(config, args.output or runtime.default_path())
        print(json.dumps({"created": True, "path": str(output), "host_mode": config["host_mode"],
                          "authentication_tested": False, "web_policy_changed": False}))
        return 0
    except (OSError, ValueError, delivery.DeliveryError) as error:
        code = error.code if isinstance(error, delivery.DeliveryError) else "RUNTIME_PROFILE_CREATE_FAILED"
        print(json.dumps({"created": False, "error_code": code}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
