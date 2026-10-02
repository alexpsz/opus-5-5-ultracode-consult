import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent
if SCRIPTS.name == "tests":
    SCRIPTS = SCRIPTS.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import runtime_profile as runtime
import create_runtime_profile as creator


class RuntimeProfileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.host = mock.patch.object(runtime, "is_windows", return_value=False)
        self.host.start()
        self.addCleanup(self.host.stop)
        self.uid = mock.patch.object(runtime, "posix_uid", return_value=501)
        self.uid.start()
        self.addCleanup(self.uid.stop)
        self.executable = self.root / "native-cli.exe"
        self.executable.write_text("fixture, never executed")
        self.launcher = self.executable
        home = str(Path.home())
        home_patch = mock.patch.object(runtime.Path, "home", return_value=Path(home))
        home_patch.start()
        self.addCleanup(home_patch.stop)
        user = os.environ.get("USER", "fixture-user")
        self.environment = {"HOME": home, "USER": user, "LOGNAME": os.environ.get("LOGNAME", user),
                            "PATH": os.pathsep.join((str(self.root), str(self.root.parent))), "NORMAL_MCP_CONFIGURATION": "keep-me"}
        self.config = {"schema_version": 1, "host_mode": "macos-user-session", "uid": 501,
            "home": home, "environment": {k: self.environment[k] for k in ("HOME", "USER", "LOGNAME", "PATH")},
            "executables": {name: {"launcher": str(self.launcher), "resolved": str(self.executable)}
                            for name in ("opus", "gemini")}}
        self.config["environment"]["CLAUDE_CONFIG_DIR"] = None
        self.profile = self.root / "runtime.json"
        self.write()

    def write(self):
        self.profile.write_text(json.dumps(self.config))

    def check(self, **changes):
        args = {"adviser": "opus", "launcher": self.launcher, "resolved": self.executable,
                "path": str(self.profile), "environment": self.environment}
        args.update(changes)
        return runtime.check_profile(**args)

    def test_valid_profile_returns_only_fixed_nonsecret_fields_and_hash(self):
        before = self.profile.read_bytes()
        result = self.check()
        self.assertTrue(result["ok"])
        self.assertEqual(result["sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual(set(result["environment"]), runtime.SAFE_ENV_KEYS)
        self.assertNotIn("NORMAL_MCP_CONFIGURATION", json.dumps(result))
        self.assertFalse(result["host_mode"]["runner_verified"])
        self.assertEqual(result["host_mode"]["verification"], "controller_attested")
        self.assertEqual(before, self.profile.read_bytes())
        self.assertTrue(self.check(adviser="gemini")["ok"])

    def test_child_env_preserves_harness_and_overrides_only_safe_values(self):
        profile = self.check()
        inherited = {**self.environment, "PATH": "/another/stable/path", "PLUGIN_SESSION_FLAG": "normal"}
        with mock.patch.dict(os.environ, inherited, clear=True):
            child = runtime.child_environment(profile)
            expected = inherited | {k: v for k, v in self.config["environment"].items() if v is not None}
            self.assertEqual(child, expected)
            self.assertEqual(os.environ, inherited)
        self.assertNotIn("CLAUDE_CONFIG_DIR", child)
        self.assertEqual(child["NORMAL_MCP_CONFIGURATION"], "keep-me")
        self.assertEqual(child["PLUGIN_SESSION_FLAG"], "normal")

    def test_missing_profile_fails_without_writing_it(self):
        missing = self.root / "missing.json"
        self.assertEqual(self.check(path=str(missing))["error_code"], "RUNTIME_PROFILE_MISSING")
        self.assertFalse(missing.exists())

    def test_default_location_is_current_home_not_a_hardcoded_user(self):
        with mock.patch.object(runtime.Path, "home", return_value=self.root):
            self.assertEqual(runtime.default_path(), self.root / ".config/codex-consultations/runtime.json")

    def test_explicit_credentials_and_provider_overrides_report_names_only(self):
        for name in runtime.CONFLICT_ENV_KEYS:
            with self.subTest(name=name):
                result = self.check(environment={**self.environment, name: "SENSITIVE-VALUE"})
                self.assertEqual(result["error_code"], "ENV_PROFILE_CONFLICT")
                self.assertEqual(result["conflict_variables"], [name])
                self.assertNotIn("SENSITIVE-VALUE", json.dumps(result))
        self.assertEqual(self.check(environment={**self.environment, "ANTHROPIC_API_KEY": ""})["error_code"],
                         "ENV_PROFILE_CONFLICT")

    def test_existing_different_claude_config_directory_is_not_silently_replaced(self):
        result = self.check(environment={**self.environment, "CLAUDE_CONFIG_DIR": "/different/account"})
        self.assertEqual(result["error_code"], "ENV_PROFILE_CONFLICT")
        self.assertEqual(result["conflict_variables"], ["CLAUDE_CONFIG_DIR"])

    def test_unset_claude_config_remains_unset_instead_of_explicit_default(self):
        profile = self.check()
        self.assertIsNone(profile["environment"]["CLAUDE_CONFIG_DIR"])
        for inherited in (self.environment, {**self.environment, "CLAUDE_CONFIG_DIR": ""}):
            with mock.patch.dict(os.environ, inherited, clear=True):
                self.assertNotIn("CLAUDE_CONFIG_DIR", runtime.child_environment(profile))
        result = self.check(environment={**self.environment, "CLAUDE_CONFIG_DIR": self.config["home"] + "/.claude"})
        self.assertEqual(result["error_code"], "ENV_PROFILE_CONFLICT")

    def test_explicit_claude_config_directory_is_preserved_when_authorized(self):
        self.config["environment"]["CLAUDE_CONFIG_DIR"] = str(Path(self.config["home"]) / ".claude-other")
        self.write()
        inherited = self.environment | self.config["environment"]
        profile = self.check(environment=inherited)
        self.assertTrue(profile["ok"])
        with mock.patch.dict(os.environ, inherited, clear=True):
            self.assertEqual(runtime.child_environment(profile)["CLAUDE_CONFIG_DIR"], inherited["CLAUDE_CONFIG_DIR"])

    def test_identity_and_executable_drift_are_rejected(self):
        original = copy.deepcopy(self.config)
        for change, expected in ((lambda: self.config.update(uid=502), "RUNTIME_PROFILE_IDENTITY_DRIFT"),
            (lambda: self.config.update(home="/different/home"), "RUNTIME_PROFILE_INVALID"),
            (lambda: self.config["executables"]["opus"].update(resolved=str(self.root / "different-executable.exe")), "RUNTIME_PROFILE_EXECUTABLE_DRIFT")):
            self.config = copy.deepcopy(original)
            change()
            self.write()
            self.assertEqual(self.check()["error_code"], expected)
        self.config = original
        self.write()
        self.assertEqual(self.check(environment={**self.environment, "HOME": "/different/home"})["error_code"],
                         "RUNTIME_PROFILE_IDENTITY_DRIFT")
        self.assertEqual(self.check(launcher=self.root / "different-launcher.exe")["error_code"], "RUNTIME_PROFILE_EXECUTABLE_DRIFT")

    def test_schema_rejects_extra_env_keys_relative_paths_and_unknown_fields(self):
        original = copy.deepcopy(self.config)
        mutations = [lambda: self.config["environment"].update(ANTHROPIC_API_KEY="SECRET"),
                     lambda: self.config["environment"].update(HOME=None),
                     lambda: self.config["environment"].update(PATH=os.pathsep.join((str(self.root), ".", str(self.root.parent)))),
                     lambda: self.config["environment"].update(PATH=os.pathsep.join((str(self.root), "", str(self.root.parent)))),
                     lambda: self.config["environment"].update(CLAUDE_CONFIG_DIR="relative"),
                     lambda: self.config.update(secret="SECRET"),
                     lambda: self.config.update(schema_version=True),
                     lambda: self.config.update(host_mode="sandbox")]
        for mutate in mutations:
            self.config = copy.deepcopy(original)
            mutate()
            self.write()
            result = self.check()
            self.assertFalse(result["ok"])
            self.assertNotIn("SECRET", json.dumps(result))

    def test_symlink_profile_is_rejected(self):
        link = self.root / "profile-link.json"
        try:
            link.symlink_to(self.profile)
        except OSError:
            self.skipTest("Creating symlinks requires Windows Developer Mode or privilege")
        self.assertEqual(self.check(path=str(link))["error_code"], "RUNTIME_PROFILE_INVALID")

    def test_environment_conflict_added_after_check_is_not_removed(self):
        profile = self.check()
        with mock.patch.dict(os.environ, {**self.environment, "CLAUDE_CODE_OAUTH_TOKEN": "secret"}, clear=True):
            with self.assertRaises(runtime.delivery.DeliveryError) as error:
                runtime.child_environment(profile)
            self.assertEqual(error.exception.code, "ENV_PROFILE_CONFLICT")
            self.assertEqual(os.environ["CLAUDE_CODE_OAUTH_TOKEN"], "secret")


class WindowsRuntimeProfileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.executable = self.root / "native-cli.exe"
        self.executable.write_text("fixture, never executed")
        self.executable.chmod(0o700)
        self.profile = self.root / "runtime.json"
        self.home = str(Path.home())
        self.environment = {
            "USERPROFILE": self.home, "USERNAME": "fixture-user", "USERDOMAIN": "TESTHOST",
            "HOMEDRIVE": "C:", "HOMEPATH": r"\Users\fixture-user",
            "APPDATA": str(self.root / "Roaming"), "LOCALAPPDATA": str(self.root / "Local"),
            "PATH": str(self.root), "PLUGIN_CONFIGURATION": "retain-me"}
        self.sid = "S-1-5-21-100-200-300-1001"
        self.config = {"schema_version": 2, "host_mode": "windows-user-session",
                       "identity": {"kind": "windows-process-token-sid", "sid": self.sid},
                       "home": self.home,
                       "environment": {k: self.environment.get(k) for k in runtime.WINDOWS_ENV_KEYS},
                       "executables": {k: {"launcher": str(self.executable), "resolved": str(self.executable)}
                                       for k in ("opus", "gemini")}}
        for target, changes in (("is_windows", {"return_value": True}),
                                ("windows_sid", {"return_value": self.sid}),
                                ("posix_uid", {"side_effect": AssertionError("Windows must not call getuid")})):
            patcher = mock.patch.object(runtime, target, **changes)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.write()

    def write(self):
        self.profile.write_text(json.dumps(self.config), encoding="utf-8")

    def check(self, **changes):
        args = {"adviser": "opus", "launcher": self.executable, "resolved": self.executable,
                "path": str(self.profile), "environment": self.environment}
        args.update(changes)
        return runtime.check_profile(**args)

    def test_windows_profile_uses_process_sid_and_preserves_optional_unset_home(self):
        result = self.check()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["identity"]["sid"], self.sid)
        self.assertIsNone(result["environment"]["HOME"])
        self.assertEqual(result["host_mode"]["required"], "windows-user-session")
        self.assertNotIn("uid", result)
        self.assertNotIn("PLUGIN_CONFIGURATION", json.dumps(result))

    def test_windows_child_keeps_harness_without_inventing_home_or_changing_profile(self):
        result = self.check()
        inherited = {**self.environment, "PATH": str(self.root.parent)}
        with mock.patch.dict(os.environ, inherited, clear=True):
            child = runtime.child_environment(result)
            self.assertEqual(child["PATH"], str(self.root))
            self.assertEqual(child["PLUGIN_CONFIGURATION"], "retain-me")
            self.assertEqual(child["USERPROFILE"], self.home)
            self.assertNotIn("HOME", child)
            self.assertNotIn("CLAUDE_CONFIG_DIR", child)
            self.assertEqual(dict(os.environ), inherited)

    def test_windows_sid_failure_or_account_drift_never_passes(self):
        with mock.patch.object(runtime, "windows_sid", return_value=self.sid + "9"):
            self.assertEqual(self.check()["error_code"], "RUNTIME_PROFILE_IDENTITY_DRIFT")
        with mock.patch.object(runtime, "windows_sid", side_effect=runtime.delivery.DeliveryError(
                "RUNTIME_PROFILE_IDENTITY_UNAVAILABLE")):
            self.assertEqual(self.check()["error_code"], "RUNTIME_PROFILE_IDENTITY_UNAVAILABLE")
        for key in runtime.WINDOWS_ENV_KEYS - {"PATH", "CLAUDE_CONFIG_DIR"}:
            with self.subTest(key=key):
                changed = {**self.environment, key: "DIFFERENT"}
                self.assertEqual(self.check(environment=changed)["error_code"], "RUNTIME_PROFILE_IDENTITY_DRIFT")
        result = self.check()
        with mock.patch.dict(os.environ, {**self.environment, "USERDOMAIN": "OTHER"}, clear=True):
            with self.assertRaisesRegex(runtime.delivery.DeliveryError, "RUNTIME_PROFILE_IDENTITY_DRIFT"):
                runtime.child_environment(result)

    def test_windows_explicit_home_and_config_are_preserved_and_conflicts_report_names_only(self):
        self.environment.update(HOME=self.home, CLAUDE_CONFIG_DIR=str(self.root / "account"))
        self.config["environment"].update(HOME=self.home, CLAUDE_CONFIG_DIR=str(self.root / "account"))
        self.write()
        result = self.check()
        self.assertTrue(result["ok"], result)
        with mock.patch.dict(os.environ, self.environment, clear=True):
            self.assertEqual(runtime.child_environment(result)["HOME"], self.home)
        result = self.check(environment={**self.environment, "ANTHROPIC_API_KEY": "private-marker"})
        self.assertEqual(result["error_code"], "ENV_PROFILE_CONFLICT")
        self.assertNotIn("private-marker", json.dumps(result))

    def test_windows_schema_cannot_be_used_on_posix_or_accept_posix_profile(self):
        with mock.patch.object(runtime, "is_windows", return_value=False):
            self.assertEqual(self.check()["error_code"], "RUNTIME_PROFILE_HOST_MISMATCH")
        self.config.update(schema_version=1, host_mode="macos-user-session", uid=501)
        del self.config["identity"]
        self.write()
        self.assertEqual(self.check()["error_code"], "RUNTIME_PROFILE_HOST_MISMATCH")

    def test_windows_schema_rejects_bad_identity_env_and_unknown_fields(self):
        original = copy.deepcopy(self.config)
        for mutate in (lambda: self.config["identity"].update(sid="some-user"),
                       lambda: self.config["identity"].update(kind="username"),
                       lambda: self.config["environment"].update(USERNAME=None),
                       lambda: self.config["environment"].update(APPDATA="relative"),
                       lambda: self.config["environment"].update(TOKEN="private-marker"),
                       lambda: self.config.update(uid=501)):
            self.config = copy.deepcopy(original)
            mutate()
            self.write()
            self.assertEqual(self.check()["error_code"], "RUNTIME_PROFILE_INVALID")

    def test_create_helper_builds_windows_profile_without_adviser_or_policy_calls(self):
        with mock.patch.dict(os.environ, self.environment, clear=True):
            config = creator.build_profile(str(self.executable), str(self.executable))
        self.assertEqual(config, self.config)
        destination = self.root / "new" / "runtime.json"
        creator.create_profile(config, destination)
        before = destination.read_bytes()
        with self.assertRaisesRegex(runtime.delivery.DeliveryError, "RUNTIME_PROFILE_ALREADY_EXISTS"):
            creator.create_profile({"changed": True}, destination)
        self.assertEqual(destination.read_bytes(), before)
        self.assertNotIn("PLUGIN_CONFIGURATION", before.decode())

    def test_creator_rejects_windows_batch_launchers(self):
        batch = self.root / "claude.cmd"
        batch.write_text("never executed")
        batch.chmod(0o700)
        with self.assertRaisesRegex(runtime.delivery.DeliveryError, "NATIVE_WINDOWS_EXE_REQUIRED"):
            creator.binding(str(batch))

    def test_creator_rejects_relative_path_and_removes_transient_codex_entry(self):
        transient = self.root / ".codex" / "tmp" / "arg0-test"
        path = os.pathsep.join((str(self.root), "", str(transient), str(self.root)))
        self.assertEqual(creator.stable_path(path), str(self.root))
        with self.assertRaises(runtime.delivery.DeliveryError):
            creator.stable_path(os.pathsep.join((str(self.root), ".")))


class NativeWindowsIdentityTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Actual Windows process-token check")
    def test_process_token_sid_is_stable_without_environment_identity(self):
        sid = runtime.windows_sid()
        self.assertRegex(sid, r"^S-1-(?:[0-9]+-)+[0-9]+$")
        with mock.patch.dict(os.environ, {"USERNAME": "untrusted-env-name"}):
            self.assertEqual(runtime.windows_sid(), sid)


if __name__ == "__main__":
    unittest.main()
