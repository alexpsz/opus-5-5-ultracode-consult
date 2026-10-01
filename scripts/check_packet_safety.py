#!/usr/bin/env python3
"""Heuristic UTF-8 credential preflight; output never includes source contents.

Exit codes: 0 no findings, 1 suspected credentials, 2 unreadable/invalid input.
A pass is a heuristic result, not a guarantee that material is safe to share.
"""

import argparse
import json
from pathlib import Path
import re
import sys


ENV_REFERENCE = r"\$\{[A-Za-z_][A-Za-z0-9_]*\}"
PLACEHOLDER = re.compile(
    r"(?:redacted|removed|omitted|hidden|placeholder|example|sample|dummy|fake|"
    r"changeme|change_me|not_set|none|null|nil|undefined|n/a|todo|tbd|"
    r"your(?:[_ -](?:api|access|refresh|secret|private|client|auth|bearer|"
    r"key|token|password|credential|here))+|"
    r"(?:insert|replace|example|sample|dummy|fake|placeholder|redacted)"
    r"(?:[_ -](?:api|access|refresh|client|key|token|secret|password|credential|value|me|with|your|here))+|"
    r"not[_ -]a[_ -]real[_ -](?:key|token|secret|password|credential)|"
    r"x{3,}|\*{3,})", re.IGNORECASE
)
PLACEHOLDER_LABEL = re.compile(
    r"(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|"
    r"client[_ -]?secret|secret|token|password|credential|credentials)",
    re.IGNORECASE,
)


def is_placeholder(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'`":
        value = value[1:-1].strip()
    if not value:
        return True
    if re.fullmatch(ENV_REFERENCE, value):
        return True
    if re.fullmatch(r"\$[A-Za-z_][A-Za-z0-9_]*|%[A-Za-z_][A-Za-z0-9_]*%", value):
        return True
    if PLACEHOLDER.fullmatch(value):
        return True
    if len(value) >= 2 and (value[0], value[-1]) in (("<", ">"), ("[", "]")):
        label = value[1:-1].strip()
        return bool(PLACEHOLDER.fullmatch(label) or PLACEHOLDER_LABEL.fullmatch(label))
    return False


SIGNATURES = (
    ("private_key_pem", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")),
    ("anthropic_api_key", re.compile(r"(?<![A-Za-z0-9_-])sk-ant-[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])")),
    ("openai_api_key", re.compile(r"(?<![A-Za-z0-9_-])sk-(?!ant-)(?:(?:proj|svcacct)-)?[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])")),
    ("github_token", re.compile(r"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})(?![A-Za-z0-9_])")),
    ("aws_access_key_id", re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])")),
    ("google_api_key", re.compile(r"(?<![A-Za-z0-9_-])AIza[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])")),
    ("google_oauth_token", re.compile(r"(?<![A-Za-z0-9_-])ya29\.[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])")),
    ("google_oauth_client_secret", re.compile(r"(?<![A-Za-z0-9_-])GOCSPX-[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])")),
)
VALUE = (
    r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|'
    + ENV_REFERENCE + r"|<[^<>\r\n]+>|\[(?:REDACTED|REMOVED|OMITTED|HIDDEN)\]|[^\s,;\]}#]+"
)
ASSIGNMENT = re.compile(
    r"(?<![\w./-])[\"']?(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)[\"']?\s*[:=]\s*(?P<value>"
    + VALUE + r")(?=$|[\s,;\]}#])", re.IGNORECASE
)
CREDENTIAL_KEY = re.compile(
    r"(?:^|[_.-])(?:api[_-]?(?:key|token)|(?:access|refresh|auth|bearer|id)[_-]?token|"
    r"client[_-]?secret|(?:secret[_-]?)?access[_-]?key|private[_-]?key|"
    r"password|passwd|pwd|secret|token|credential|credentials)$", re.IGNORECASE
)
AUTH_HEADER = re.compile(
    r"\b(?:proxy-)?authorization[\"']?\s*[:=]\s*[\"']?\s*"
    r"(?P<scheme>Bearer|Basic)\s+(?P<value><[^<>\r\n]+>(?=$|[\s\"'])|[^\s\"'\r\n]+)",
    re.IGNORECASE,
)
COOKIE_HEADER = re.compile(
    r"\b(?P<name>set-cookie|cookie)[\"']?\s*:\s*(?P<value>[^\r\n]*)", re.IGNORECASE
)


def cookie_has_credential(value):
    value = value.strip().strip("\"'")
    if is_placeholder(value):
        return False
    for part in value.split(";"):
        key, separator, cookie_value = part.strip().partition("=")
        if separator and key.lower() not in {
            "path", "domain", "expires", "max-age", "samesite", "priority"
        } and not is_placeholder(cookie_value.strip().strip("\"'")):
            return True
    # A nonempty opaque Cookie header can itself contain a session credential.
    return "=" not in value and bool(value)


def scan_text(text, file_label):
    findings = set()

    def report(offset, kind):
        findings.add((text.count("\n", 0, offset) + 1, kind))

    for kind, pattern in SIGNATURES:
        for match in pattern.finditer(text):
            if not is_placeholder(match.group()):
                report(match.start(), kind)
    for match in AUTH_HEADER.finditer(text):
        if not is_placeholder(match["value"]):
            report(match.start(), "authorization_" + match["scheme"].lower())
    for match in COOKIE_HEADER.finditer(text):
        if cookie_has_credential(match["value"]):
            report(match.start(), "cookie_header")
    for match in ASSIGNMENT.finditer(text):
        key = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", match["key"])
        if CREDENTIAL_KEY.search(key) and not is_placeholder(match["value"]):
            report(match.start(), "credential_assignment")
    return [{"file": file_label, "line": line, "type": kind}
            for line, kind in sorted(findings)]


def emit_result(findings, checked, has_input_error=False):
    status = "error" if has_input_error else ("blocked" if findings else "pass")
    print(json.dumps({"status": status, "heuristic": True,
                      "inputs_checked": checked, "findings": findings}, ensure_ascii=True))
    return 2 if has_input_error else (1 if findings else 0)


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default error includes arbitrary argument strings.
        emit_result([{"file": "<arguments>", "line": None, "type": "invalid_arguments"}], 0, True)
        raise SystemExit(2)


def main(argv=None):
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="UTF-8 text files; '-' reads stdin once")
    parser.add_argument("--stdin", action="store_true", help="also scan UTF-8 bytes from stdin")
    args = parser.parse_args(argv)
    if args.files.count("-") + int(args.stdin) > 1 or not (args.files or args.stdin):
        parser.error("Expected an input and at most one stdin source")
    inputs = args.files + (["-"] if args.stdin else [])
    findings = []
    checked = 0
    has_error = False
    for path in inputs:
        label = "<stdin>" if path == "-" else path
        try:
            raw = sys.stdin.buffer.read() if path == "-" else Path(path).read_bytes()
            text = raw.decode("utf-8-sig", errors="strict")
        except UnicodeError:
            findings.append({"file": label, "line": None, "type": "invalid_utf8"})
            has_error = True
            continue
        except (OSError, ValueError):
            findings.append({"file": label, "line": None, "type": "unreadable_input"})
            has_error = True
            continue
        checked += 1
        findings.extend(scan_text(text, label))
    return emit_result(findings, checked, has_error)


if __name__ == "__main__":
    raise SystemExit(main())
