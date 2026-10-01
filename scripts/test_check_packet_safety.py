"""Offline tests using only synthetic credential-shaped strings."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
SCANNER = ROOT / "check_packet_safety.py"
SPEC = importlib.util.spec_from_file_location("scanner", SCANNER)
scanner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scanner)


class ScannerTests(unittest.TestCase):
    def run_cli(self, arguments, stdin=None):
        result = subprocess.run([sys.executable, str(SCANNER), *arguments],
                                input=stdin, capture_output=True, check=False)
        self.assertEqual(result.stderr, b"")
        payload = json.loads(result.stdout.decode("utf-8"))
        self.assertTrue(payload["heuristic"])
        for finding in payload["findings"]:
            self.assertEqual(set(finding), {"file", "line", "type"})
        return result.returncode, payload, result.stdout

    def test_common_provider_shapes(self):
        cases = {
            "openai_api_key": "sk-proj-" + "A1b2" * 20,
            "anthropic_api_key": "sk-ant-api03-" + "C3d4" * 20,
            "github_token": "github_pat_" + "E5f6" * 20,
            "aws_access_key_id": "AKIA" + "G7" * 8,
            "google_api_key": "AIza" + "H" * 35,
            "google_oauth_token": "ya29." + "J9k0" * 20,
            "google_oauth_client_secret": "GOCSPX-" + "L1m2" * 8,
        }
        for kind, secret in cases.items():
            with self.subTest(kind=kind):
                code, payload, raw = self.run_cli(["--stdin"], ("context\n" + secret + "\n").encode())
                self.assertEqual(code, 1)
                self.assertIn({"file": "<stdin>", "line": 2, "type": kind}, payload["findings"])
                self.assertNotIn(secret.encode(), raw)
                self.assertNotIn(b"context", raw)

    def test_legacy_and_service_provider_shapes(self):
        for secret in ("sk-" + "Ab" * 24, "sk-svcacct-" + "Cd" * 30,
                       "ghp_" + "E" * 36, "gho_" + "F" * 36,
                       "ASIA" + "G8" * 8):
            with self.subTest(prefix=secret[:5]):
                self.assertTrue(scanner.scan_text(secret, "packet.md"))

    def test_all_private_key_pem_variants(self):
        for kind in ("", "ENCRYPTED ", "RSA ", "EC ", "OPENSSH ", "DSA "):
            with self.subTest(kind=kind):
                findings = scanner.scan_text("-----BEGIN " + kind + "PRIVATE KEY-----\nSYNTHETIC", "packet.md")
                self.assertEqual(findings[0]["type"], "private_key_pem")

    def test_authorization_headers(self):
        for scheme, value in (("Bearer", "synthetic_session_123456"),
                              ("Basic", "dGVzdDpzeW50aGV0aWM=")):
            text = "curl -H 'Authorization: " + scheme + " " + value + "'"
            code, payload, raw = self.run_cli(["-"], text.encode())
            self.assertEqual(code, 1)
            self.assertIn("authorization_" + scheme.lower(), [f["type"] for f in payload["findings"]])
            self.assertNotIn(value.encode(), raw)
            self.assertNotIn(b"curl", raw)

    def test_cookie_headers(self):
        for line in ("Cookie: session=synthetic_cookie_123; theme=dark",
                     "Set-Cookie: sid=synthetic_cookie_123; HttpOnly; Path=/"):
            findings = scanner.scan_text(line, "packet.md")
            self.assertIn("cookie_header", [f["type"] for f in findings])

    def test_credential_assignments(self):
        cases = (
            'API_KEY="synthetic_value_123"',
            'AWS_SECRET_ACCESS_KEY=synthetic_aws_secret_1234567890',
            '"client_secret": "synthetic_value_123"',
            "db_password: 'synthetic_value_123'",
            'accessToken = "synthetic_value_123"',
            '"refresh_token":"synthetic_value_123"',
            "password = weakpass",
        )
        for text in cases:
            with self.subTest(key=text.split("=")[0][:20]):
                self.assertIn("credential_assignment", [f["type"] for f in scanner.scan_text(text, "packet.md")])

    def test_safe_placeholders_and_noncredentials(self):
        text = '''API_KEY=${OPENAI_API_KEY}
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}"
password = <password>
client_secret = [REDACTED]
token = YOUR_ACCESS_TOKEN_HERE
api_key = "your-api-key-here"
secret = ""
password = "********"
Authorization: Bearer ${TOKEN}
Authorization: Basic <redacted>
Cookie: session=${SESSION}; theme=<redacted>
Set-Cookie: sid=; Path=/; Max-Age=0
task_name = "review"
token_count = 4096
public_key = "sample public data"
'''
        code, payload, raw = self.run_cli(["--stdin"], text.encode())
        self.assertEqual((code, payload["status"], payload["findings"]), (0, "pass", []))
        self.assertNotIn(b"sample public data", raw)

    def test_env_reference_is_not_a_blanket_exemption(self):
        for value in ("${TOKEN}-real-suffix", "${TOKEN:-synthetic_real_default}"):
            findings = scanner.scan_text("token=" + value, "packet.md")
            self.assertTrue(findings)

    def test_common_documentation_placeholders(self):
        for value in ("REPLACE_ME", "REPLACE_WITH_YOUR_API_KEY", "example_api_key",
                      "dummy_token", "NOT_A_REAL_SECRET", "<YOUR_API_KEY_HERE>"):
            with self.subTest(placeholder=value):
                self.assertEqual(scanner.scan_text("api_key=" + value, "packet.md"), [])

    def test_placeholder_prefix_cannot_hide_a_credential(self):
        for line in ("Authorization: Bearer ${TOKEN}-synthetic_suffix",
                     "Authorization: Basic <redacted>-synthetic_suffix",
                     "password=<redacted>-synthetic_suffix",
                     "api_key=example_realSecret123"):
            self.assertTrue(scanner.scan_text(line, "packet.md"))

    def test_missing_file_and_invalid_utf8(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            missing = Path(directory) / "missing.md"
            code, payload, _ = self.run_cli([str(missing)])
            self.assertEqual(code, 2)
            self.assertEqual(payload["findings"][0]["type"], "unreadable_input")
            bad = Path(directory) / "bad.md"
            bad.write_bytes(b"private surrounding text\xff")
            code, payload, raw = self.run_cli([str(bad)])
            self.assertEqual(code, 2)
            self.assertEqual(payload["findings"][0]["type"], "invalid_utf8")
            self.assertNotIn(b"surrounding", raw)

    def test_invalid_utf8_stdin(self):
        code, payload, raw = self.run_cli(["--stdin"], b"sensitive prefix\xff")
        self.assertEqual(code, 2)
        self.assertEqual(payload["findings"][0]["type"], "invalid_utf8")
        self.assertNotIn(b"sensitive prefix", raw)

    def test_multiple_files_and_stdin_are_all_checked(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            first, second = Path(directory) / "first.md", Path(directory) / "second.md"
            first.write_text("api_key=${KEY}", encoding="utf-8")
            second.write_text("safe UTF-8: 中文", encoding="utf-8-sig")
            code, payload, _ = self.run_cli([str(first), str(second), "--stdin"], b"password=synthetic_password_123")
            self.assertEqual(code, 1)
            self.assertEqual(payload["inputs_checked"], 3)

    def test_input_errors_cannot_hide_other_findings(self):
        code, payload, _ = self.run_cli([str(ROOT / "no-such-input.md"), "--stdin"], b"token=synthetic_token_123")
        self.assertEqual(code, 2)
        self.assertEqual({f["type"] for f in payload["findings"]}, {"unreadable_input", "credential_assignment"})

    def test_invalid_arguments_and_no_bypass(self):
        for arguments in ([], ["--allow-credentials"], ["--stdin", "-"], ["--synthetic-secret-123"]):
            code, payload, raw = self.run_cli(arguments)
            self.assertEqual(code, 2)
            self.assertEqual(payload["findings"][0]["type"], "invalid_arguments")
            self.assertNotIn(b"synthetic-secret-123", raw)


if __name__ == "__main__":
    unittest.main()
