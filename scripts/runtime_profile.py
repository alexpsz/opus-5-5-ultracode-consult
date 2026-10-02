#!/usr/bin/env python3
"""Read a fixed user-session profile without changing configuration or logging in."""
import hashlib
import os
import re
from pathlib import Path

import collect_delivery as delivery

SAFE_ENV_KEYS = frozenset({"HOME", "USER", "LOGNAME", "PATH", "CLAUDE_CONFIG_DIR"})
WINDOWS_ENV_KEYS = frozenset({"USERPROFILE", "USERNAME", "USERDOMAIN", "HOMEDRIVE", "HOMEPATH",
                              "APPDATA", "LOCALAPPDATA", "HOME", "PATH", "CLAUDE_CONFIG_DIR"})
WINDOWS_OPTIONAL_KEYS = frozenset({"HOME", "CLAUDE_CONFIG_DIR", "USERDOMAIN", "HOMEDRIVE", "HOMEPATH"})
CONFLICT_ENV_KEYS = frozenset({
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY_FILE", "ANTHROPIC_AUTH_TOKEN_FILE",
    "ANTHROPIC_BASE_URL", "ANTHROPIC_CUSTOM_HEADERS", "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN_FILE", "CLAUDE_CODE_API_KEY_HELPER",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
    "CLAUDE_CODE_PROVIDER", "CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST", "CLAUDE_CODE_PROXY_BASE_URL",
    "GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_GEMINI_BASE_URL", "GOOGLE_VERTEX_BASE_URL", "GEMINI_API_BASE_URL", "GEMINI_BASE_URL",
    "ANTIGRAVITY_API_KEY", "ANTIGRAVITY_AUTH_TOKEN", "ANTIGRAVITY_BASE_URL",
    "AGY_API_KEY", "AGY_AUTH_TOKEN", "AGY_BASE_URL",
})


def default_path():
    return Path.home() / ".config" / "codex-consultations" / "runtime.json"


def absolute(value):
    delivery.require(isinstance(value, str) and bool(value) and "\x00" not in value,
                     "RUNTIME_PROFILE_INVALID")
    path = Path(value)
    delivery.require(path.is_absolute() and os.path.normpath(value) == value, "RUNTIME_PROFILE_INVALID")
    return path


def conflicts(environment, fixed):
    names = sorted(CONFLICT_ENV_KEYS.intersection(environment))
    configured = fixed.get("CLAUDE_CONFIG_DIR")
    if (configured is None and environment.get("CLAUDE_CONFIG_DIR") or
            configured is not None and "CLAUDE_CONFIG_DIR" in environment and
            environment["CLAUDE_CONFIG_DIR"] != configured):
        names.append("CLAUDE_CONFIG_DIR")
    return sorted(set(names))


def is_windows():
    return os.name == "nt"


def posix_uid():
    delivery.require(not is_windows() and hasattr(os, "getuid"), "RUNTIME_PROFILE_HOST_MISMATCH")
    return os.getuid()


def windows_sid():
    """Read TokenUser from our own process; no credential-store or network access."""
    delivery.require(is_windows(), "RUNTIME_PROFILE_HOST_MISMATCH")
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    security = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    security.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    security.OpenProcessToken.restype = wintypes.BOOL
    security.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                              wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    security.GetTokenInformation.restype = wintypes.BOOL
    security.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    security.ConvertSidToStringSidW.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    text = wintypes.LPWSTR()
    try:
        delivery.require(bool(security.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008,
                                                        ctypes.byref(token))),
                         "RUNTIME_PROFILE_IDENTITY_UNAVAILABLE")
        size = wintypes.DWORD()
        security.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))  # TokenUser
        delivery.require(0 < size.value <= 65536, "RUNTIME_PROFILE_IDENTITY_UNAVAILABLE")
        buffer = ctypes.create_string_buffer(size.value)
        delivery.require(bool(security.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size))),
                         "RUNTIME_PROFILE_IDENTITY_UNAVAILABLE")
        # TOKEN_USER begins with SID_AND_ATTRIBUTES, whose first field is PSID.
        sid_pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        delivery.require(bool(security.ConvertSidToStringSidW(sid_pointer, ctypes.byref(text))),
                         "RUNTIME_PROFILE_IDENTITY_UNAVAILABLE")
        sid = text.value
        delivery.require(isinstance(sid, str) and re.fullmatch(r"S-1-(?:[0-9]+-)+[0-9]+", sid),
                         "RUNTIME_PROFILE_IDENTITY_UNAVAILABLE")
        return sid
    finally:
        if text:
            kernel.LocalFree(ctypes.cast(text, ctypes.c_void_p))
        if token:
            kernel.CloseHandle(token)


def schema_keys(data):
    version = data.get("schema_version")
    delivery.require(type(version) is int and version in (1, 2), "RUNTIME_PROFILE_INVALID")
    if version == 1:
        delivery.require(data.get("host_mode") == "macos-user-session" and type(data.get("uid")) is int,
                         "RUNTIME_PROFILE_INVALID")
        delivery.require(not is_windows(), "RUNTIME_PROFILE_HOST_MISMATCH")
        return SAFE_ENV_KEYS, {"CLAUDE_CONFIG_DIR"}
    delivery.require(data.get("host_mode") == "windows-user-session", "RUNTIME_PROFILE_INVALID")
    delivery.require(is_windows(), "RUNTIME_PROFILE_HOST_MISMATCH")
    identity = data.get("identity")
    delivery.require(isinstance(identity, dict) and set(identity) == {"kind", "sid"} and
                     identity["kind"] == "windows-process-token-sid" and
                     isinstance(identity["sid"], str) and
                     re.fullmatch(r"S-1-(?:[0-9]+-)+[0-9]+", identity["sid"]), "RUNTIME_PROFILE_INVALID")
    return WINDOWS_ENV_KEYS, WINDOWS_OPTIONAL_KEYS


def check_identity(data, inherited):
    fixed = data["environment"]
    delivery.require(str(Path.home()) == data["home"], "RUNTIME_PROFILE_IDENTITY_DRIFT")
    if data["schema_version"] == 1:
        delivery.require(data["uid"] == posix_uid() and inherited.get("HOME") == data["home"],
                         "RUNTIME_PROFILE_IDENTITY_DRIFT")
        delivery.require(all(inherited.get(name, fixed[name]) == fixed[name] for name in ("USER", "LOGNAME")),
                         "RUNTIME_PROFILE_IDENTITY_DRIFT")
    else:
        delivery.require(data["identity"]["sid"] == windows_sid(), "RUNTIME_PROFILE_IDENTITY_DRIFT")
        # PATH is intentionally pinned; account/config locations must not silently change.
        identity_keys = WINDOWS_ENV_KEYS - {"PATH", "CLAUDE_CONFIG_DIR"}
        delivery.require(all((inherited.get(k) or None) == fixed[k] for k in identity_keys),
                         "RUNTIME_PROFILE_IDENTITY_DRIFT")


def validate_data(data, *, adviser, launcher, resolved, environment):
    delivery.require(isinstance(data, dict), "RUNTIME_PROFILE_INVALID")
    allowed, nullable = schema_keys(data)
    identity_key = "uid" if data["schema_version"] == 1 else "identity"
    delivery.require(set(data) == {"schema_version", "host_mode", identity_key, "home", "environment",
                                   "executables"}, "RUNTIME_PROFILE_INVALID")
    home = absolute(data["home"])
    fixed = data["environment"]
    delivery.require(isinstance(fixed, dict) and set(fixed) == allowed and
                     all(k in nullable and v is None or isinstance(v, str) and v and "\x00" not in v
                         for k, v in fixed.items()), "RUNTIME_PROFILE_INVALID")
    home_key = "HOME" if data["schema_version"] == 1 else "USERPROFILE"
    delivery.require(fixed[home_key] == str(home), "RUNTIME_PROFILE_INVALID")
    path_keys = {"CLAUDE_CONFIG_DIR"} if data["schema_version"] == 1 else {
        "CLAUDE_CONFIG_DIR", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOME"}
    for key in path_keys:
        if fixed[key] is not None:
            absolute(fixed[key])
    for entry in fixed["PATH"].split(os.pathsep):
        absolute(entry)
    executables = data["executables"]
    delivery.require(isinstance(executables, dict) and set(executables) == {"opus", "gemini"},
                     "RUNTIME_PROFILE_INVALID")
    for binding in executables.values():
        delivery.require(isinstance(binding, dict) and set(binding) == {"launcher", "resolved"},
                         "RUNTIME_PROFILE_INVALID")
        absolute(binding["launcher"])
        absolute(binding["resolved"])
    found = conflicts(environment, fixed)
    if found:
        return {"ok": False, "error_code": "ENV_PROFILE_CONFLICT", "conflict_variables": found}
    check_identity(data, environment)
    chosen = executables[adviser]
    delivery.require(chosen["launcher"] == str(launcher) and chosen["resolved"] == str(resolved) and
                     str(Path(chosen["launcher"]).resolve(strict=True)) == chosen["resolved"],
                     "RUNTIME_PROFILE_EXECUTABLE_DRIFT")
    return {"ok": True, "error_code": None, "schema_version": data["schema_version"],
            identity_key: data[identity_key], "home": str(home), "environment": dict(fixed),
            "executables": executables,
            "host_mode": {"required": data["host_mode"], "verification": "controller_attested",
                          "runner_verified": False}}


def check_profile(*, adviser, launcher, resolved, path=None, environment=None):
    inherited = dict(os.environ if environment is None else environment)
    selected = str(default_path()) if path is None else str(path)
    result = {"ok": False, "error_code": None, "path": selected}
    try:
        profile_path = absolute(selected)
        if not profile_path.exists() and not profile_path.is_symlink():
            result["error_code"] = "RUNTIME_PROFILE_MISSING"
            return result
        delivery._check_chain(profile_path)
        delivery.require(str(profile_path.resolve(strict=True)) == selected, "RUNTIME_PROFILE_INVALID")
        raw = delivery.read_file(profile_path)
        data = delivery.parse_json(raw)
        result.update(validate_data(data, adviser=adviser, launcher=launcher, resolved=resolved,
                                    environment=inherited))
        if result["ok"]:
            result["sha256"] = hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError, KeyError, delivery.DeliveryError) as error:
        known = getattr(error, "code", None)
        result["error_code"] = known if isinstance(known, str) and known.startswith("RUNTIME_PROFILE_") else "RUNTIME_PROFILE_INVALID"
    return result


def child_environment(profile):
    """Override only safe profile keys; retain normal hook, plugin and MCP env."""
    delivery.require(profile.get("ok") is True, "RUNTIME_PROFILE_INVALID")
    data = dict(profile)
    data["host_mode"] = profile["host_mode"]["required"]
    allowed, _ = schema_keys(data)
    fixed = data.get("environment")
    delivery.require(isinstance(fixed, dict) and set(fixed) == allowed, "RUNTIME_PROFILE_INVALID")
    inherited = dict(os.environ)
    delivery.require(not conflicts(inherited, fixed), "ENV_PROFILE_CONFLICT")
    check_identity(data, inherited)
    child = dict(inherited)
    for key, value in fixed.items():
        if value is None:
            child.pop(key, None)
        else:
            child[key] = value
    return child
