# Windows CLI setup and testing

Use native Windows Python 3.10+ and the official native Claude Code and Antigravity CLI executables. Keep the same Windows account and execution environment for setup and consultations. WSL is a separate environment; do not reuse a Windows or macOS profile inside it. This package's fixed-profile support currently targets macOS and native Windows.

## Install or update the skill

Download the repository ZIP or update a clean clone with `git pull --ff-only`. Keep a backup of an existing installation outside the skills discovery directory before replacing it; preserve local changes instead of resetting them. Copy the complete package into the configured Codex skills directory, using its repository name as the folder name, then refresh skill discovery. Keep only one installed copy of each skill.

Do not copy another machine's `runtime.json`, credentials or consultation directories. Only the reusable skill files belong in the public package.

## Verify the official CLIs

Follow the provider's installation and authentication instructions: [Claude Code on Windows](https://code.claude.com/docs/en/setup#set-up-on-windows) and [Antigravity CLI](https://www.antigravity.google/docs/cli/install/). Complete required sign-in locally. The skill does not install a CLI or copy desktop credentials.

In PowerShell, confirm the native executables that the runner will use:

```powershell
$claudeExe = (Get-Command claude.exe -CommandType Application -ErrorAction Stop).Source
$agyExe = (Get-Command agy.exe -CommandType Application -ErrorAction Stop).Source
& $claudeExe --version
& $agyExe --version
& $claudeExe auth status
```

The runner requires native `.exe` files on Windows. A `.cmd`, `.bat` or PowerShell wrapper is not accepted as the executable. The CLI paths can contain spaces; pass them as separate quoted arguments rather than a command string.

## Create this machine's fixed profile

From either skill's package directory, after verifying both official executable paths:

```powershell
py -3 -X utf8 scripts/create_runtime_profile.py --opus-executable "$claudeExe" --gemini-executable "$agyExe"
```

This creates a private profile at `%USERPROFILE%\.config\codex-consultations\runtime.json`. Both skills use the same profile. The helper refuses to overwrite an existing file. If a previous profile belongs to another machine or an executable has moved, inspect and back it up before explicitly regenerating it; do not bypass a drift error by reusing a submitted request.

Windows profiles bind the current process token SID, user profile, selected account directories, stable PATH and both CLI paths. They do not contain login tokens or passwords. Existing macOS schema 1 profiles remain supported; Windows uses schema 2. Keep `CLAUDE_CONFIG_DIR` unset when the native default account is intended. The setup helper does not authenticate or change permission settings.

Claude web permissions are retained on each consultation. Antigravity requires the current user's authorized `read_url(*)` rule in its settings; follow [CLI workflow](cli-workflow.md) to preserve existing settings and explicit restrictions. Windows managed policy may come from sources beyond the local files inspected by preflight; the native CLI remains authoritative, and actual denials must be retained in the result. Installing the skill alone does not grant global permission. The owning user's authorization can be reused when it already covers this setup.

## Validate before a real review

Run the offline suite from each package directory, using the test folder shown in its README. Use `py -3 -X utf8` instead of `python3` so UTF-8 fixtures also work on Windows installations with a legacy default encoding. These tests use synthetic local fixtures and do not call a model. Automated Windows checks establish helper behavior only, not the signed-in CLIs on your laptop.

For the first live test, ask Codex to use the installed skill for a small non-sensitive review in an existing project. Include one public source lookup and page read when testing network access. Preserve the original answer and inspect `run.json` plus the actual native tool output. A configured web permission or a successful process exit alone does not prove source access or a complete review.

`RUNTIME_PROFILE_MISSING`, identity drift and `WINDOWS_NATIVE_EXECUTABLE_REQUIRED` are preflight failures. `WAITING_FOR_AUTH` requires local sign-in; a sandbox/host restriction requires the appropriate authorized execution environment. Recover existing `SENT` or `UNKNOWN` requests without sending them again. Use [runtime recovery](runtime-recovery.md) for receipts, continuation and acceptance.
