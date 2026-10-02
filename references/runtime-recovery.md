# Runtime checks and bounded recovery

The bundled runner checks the default web policy on **every** new request and explicit continuation, before spawning the official CLI. Claude always retains `--allowedTools WebSearch WebFetch`; Antigravity requires the already-authorized global `permissions.allow` entry `read_url(*)`. Missing broad access is `WEB_DEFAULT_MISSING`; explicit broad denial is `WEB_POLICY_BLOCKED`. These remain `NOT_SENT`. Restore the previously authorized narrow web default after backing up current settings; do not repeatedly request approval for the same already-authorized setup. Never erase explicit deny/ask or managed policy. Domain-specific restrictions remain visible and binding.

The check does not call a model, trigger login, run `agy models`, probe private credentials, or change settings. A successful local check means configured readiness, **not** demonstrated internet access. Report actual web errors from the native run. Profiles using nonstandard configuration paths or remotely managed settings need their own effective-policy check; local settings inspection cannot prove the complete policy.

The local host check briefly binds and closes an unused loopback socket and creates/removes one harmless temporary file in the consultation cache. It never listens, sends a remote request or touches credentials. These capabilities catch a restricted launcher before submission; success does not prove authentication or unrestricted host access. Use the authorized macOS desktop user's host execution context for every launch (in Codex, request the tool's host execution via `sandbox_permissions=require_escalated`). The helper does not escape or elevate itself. A `HOST_CONTEXT_REQUIRED` check failure remains NOT_SENT and can be corrected before the first actual submission.

## Reuse installation knowledge

Check version, help, supported target and installed harness once after installation or relevant changes. The runner stores only nonsecret observations under `~/.cache/codex-consultations/`: executable identity, policy fingerprint binding, request/model/outcome metadata. It excludes tokens, login links, prompts, native logs and answers. Cache keys include the adviser, project, executable identity and semantic settings fingerprints. A changed executable/project/settings causes a miss; native auth failure updates the record. Whitespace-only settings reformatting does not invalidate it. Cache write failure does not affect delivery.

Read `preflight.cache` and reuse the matching last native observation instead of repeatedly launching authentication or model-list probes. It never proves the login is still valid or skips native authentication. The cache is informational, not a capability grant. Keep the installation's verified model/version inventory alongside the setup evidence and refresh it only when needed.

## Check local evidence before sending

`INPUT_MANIFEST` and its optional hash in the frozen dispatch are recognized automatically; an explicit `--input-manifest /absolute/manifest.json` is also supported and must agree with that header. A manifest is a JSON object with optional `root` and an `inputs` list. Each entry specifies `project_relative_path` or `absolute_path`, `bytes`, `sha256`, and optionally `role`. If both path fields are present they must name the same file. Packet/header hashes and actual file bytes are checked before dispatch; symlinks, changed inputs and ambiguous headers fail locally.

Antigravity workspace access does not automatically include a screenshot stored in another project. A manifest input or packet outside the owning project without an existing matching read grant produces `INPUTS_OUTSIDE_PROJECT_NEED_STAGING` before any message is sent. Prepare generated screenshots and text evidence under that project's `docs/reviews/<request>-evidence/` from the start. For already-authorized external inputs, copy only those exact files to that location, preserve original source paths and byte hashes in the manifest, and update the outgoing packet. Verify copied bytes rather than recapturing screenshots unnecessarily. An explicit file deny/ask produces `INPUT_POLICY_BLOCKED`; do not copy or move that source to bypass its rule. Do not add filesystem wildcards. In-project location is only a preflight check; native tool results still establish actual access.

Optional standalone check:

```sh
python3 scripts/consult_preflight.py --adviser gemini --executable /absolute/path/to/agy --project-root /absolute/project --prompt-file /absolute/project/docs/reviews/dispatch.txt
```

## Classify before recovering

- `HOST_CONTEXT_REQUIRED`: explicit filesystem/keychain/loopback errors under a restricted launcher. Use the authorized host execution context. This is not evidence of a bad account password or web-tool denial. Check dispatch state before retrying; only proven `NOT_SENT` is safe for a replacement launch.
- `AUTH_REQUIRED` / `WAITING_FOR_AUTH`: an explicit native login failure. Stop hidden/background login attempts. Open one **visible** terminal and run the installed CLI's official login flow using its current help. Keep it open while the user completes the browser step. Never ask them to paste passwords, tokens or authorization codes into chat. Recheck once after they confirm completion; avoid generating several simultaneous login links. If the visible Claude login says it could not save credentials to the Mac keychain, browser authorization alone is insufficient: retain that exact diagnostic, ask the user to unlock the login keychain locally and retry the official login once. Do not collect their password, bypass keychain protections, or change credential storage.
- `MODEL_UNAVAILABLE`: recheck official model availability once and explain the restriction. Do not substitute another model silently.
- Native tool denial: retain the answer and missing-evidence list; fix only the authorized cause. Search/read permission, external-file permission, host sandbox access and account authentication are separate controls.

A macOS CLI reporting “not logged in” can mean its keychain credentials are inaccessible, not necessarily expired. If the original item still exists but native operations return `-25293` despite an unlocked status, inspect the actual error once. One user-authorized lock/unlock of the same login keychain may clear stale authentication state; require the user to enter the password locally, then verify real keychain operations and a fresh `claude auth status`. Do not automatically reset/delete the keychain, loosen item ACLs, export tokens, or run `/logout`: the latter can also remove MCP/plugin credentials. Preserve an explicit distinction between a generic unlock suggestion and an established diagnosis. References: [Anthropic login recovery](https://code.claude.com/docs/en/troubleshoot-install#not-logged-in-or-token-expired), [Apple developer report and DTS response](https://developer.apple.com/forums/thread/822120). The report describes a matching symptom, not proof of every affected OS version.

A transient auth warning followed by a successful native final is not a failed login. Unknown errors stay unknown. A timeout or lost stream may already be `SENT`; never call it unsent just to retry.

## Explicit same-conversation follow-up

For a genuinely changed question/evidence within the authorized consultation, use a **new** request ID, prompt and run directory plus:

```text
--continue-from /absolute/previous-run/run.json
```

The parent must belong to the same adviser, project and exact target, have observed `SENT`, a terminal process, a native final and one canonical session UUID. The runner binds the parent receipt hash and native session, and uses Claude `--resume` or Antigravity `--conversation`. It keeps the web grants/checks and full harness. A follow-up is recorded as `independent_review=false`; it is not another independent first opinion. Never use this option to inspect or recover an answer: it **sends a new turn**. Uncertain/live requests must be inspected first; no automatic retries or transport changes are provided.

Use a fresh final sentinel per follow-up. Ask for it as the **last line, exact plain text, without quotes, code fences or Markdown formatting**. Preserve a response with a malformed sentinel unchanged; captured text and accepted delivery are different states.

## Observe and verify

During execution, the receipt updates from complete NDJSON records with phases such as READY, SENT and GENERATING, the last native event/tool, and timing evidence. Initial metadata alone never proves submission. Partial last lines wait for more bytes; final parsing remains strict. The receipt records runner/skill hashes, timeout and parent provenance so it is clear which implementation actually ran.

`answer_capture_status=CAPTURED` means the original final text was saved. `delivery_status` describes transport/content-format checks. `acceptance_status=PENDING_CONTROLLER_REVIEW` requires the controller's evidence and factual review. None of these proves every file, screenshot or source was used. Do not rewrite the native answer to make a check pass.

After native completion, recover access evidence without another model call:

```sh
python3 scripts/collect_cli_evidence.py --run-dir /absolute/completed-run
```

This creates `evidence-summary.json` and `evidence-archive/sources/` once, preserving hashed original bytes and leaving run/answer/raw files untouched. Antigravity data defaults to `~/.gemini/antigravity-cli`; `--native-data-root` accepts an explicitly selected profile. Only the recorded conversation and steps observed in this run may supply evidence. It never follows another session or a linked/escaping path.

Classify tool calls, result envelopes, actual content, failures, denials and unknown coverage separately. DONE without payload is not a successful file/web read. A page fragment is not a complete page; a text description of an image is not proof the model received its pixels. Aggregate denials without a step ID cannot be attributed to every tool of that name. The collector's `content_accepted=false` is deliberate: the controller still checks substantive claims.


## Fixed user-session runtime profile

Every new turn and explicit continuation reads `~/.config/codex-consultations/runtime.json`, using the current user's home. An isolated test may select another absolute file with `--runtime-profile /absolute/runtime.json`. The runner reads this configuration; it never creates it, logs in, repairs Keychain, or changes permissions. The separate `scripts/create_runtime_profile.py` helper creates a profile only during authorized setup and refuses to overwrite an existing file.

The existing macOS schema 1 is shown below. Native Windows uses schema 2 with the current process SID instead of a Unix UID; create it using [Windows CLI setup](windows-setup.md). Replace all example values with the authorized current account and verified official launcher/resolved paths. PATH is an explicit list of stable absolute directories: retain needed CLI, hook and MCP runtime directories, but omit transient task directories and relative/empty entries. The project root remains the explicit root of each consultation.

```json
{
  "schema_version": 1,
  "host_mode": "macos-user-session",
  "uid": 501,
  "home": "/Users/example",
  "environment": {
    "HOME": "/Users/example",
    "USER": "example",
    "LOGNAME": "example",
    "PATH": "/Users/example/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
    "CLAUDE_CONFIG_DIR": null
  },
  "executables": {
    "opus": {"launcher": "/absolute/claude-launcher", "resolved": "/absolute/claude-native-executable"},
    "gemini": {"launcher": "/absolute/agy-launcher", "resolved": "/absolute/agy-native-executable"}
  }
}
```

For macOS schema 1, only the five listed environment keys are allowed. Windows schema 2 fixes native Windows account directories and environment instead; use its setup helper rather than adapting this example by hand. `CLAUDE_CONFIG_DIR` alone may be null: this explicitly fixes it as **unset**, preserving the existing default account/Keychain namespace. Do not convert unset into an explicit `~/.claude` value. A nonempty inherited value conflicts with a null profile; an empty inherited value is removed for the child. This variable configures Claude, not Antigravity; both CLIs still share the fixed HOME. A separately authorized nondefault Claude directory must be explicit in the profile and consistent with inherited configuration.

UID, current HOME, account-name fields and the selected launcher/resolved executable must match. Missing, malformed, conflicting or drifted profiles produce a NOT_SENT/FAILED preflight receipt before any CLI launch. Explicit API keys, authentication tokens and known provider/base-URL override variables produce `ENV_PROFILE_CONFLICT`; diagnostics name variables without exposing values. The runner neither clears credentials nor silently changes accounts. Other inherited environment remains available to normal hooks, skills, plugins and MCP; the fixed safe values are applied as overrides, not as an environment whitelist.

The receipt records the exact profile path/hash and its nonsecret fixed fields. `host_mode.required` is `macos-user-session` or `windows-user-session` according to the profile; `host_mode.verification` is `controller_attested`, and `runner_verified` is false. These labels assign the execution responsibility to the controller; they do not prove the process escaped a sandbox. Use the authorized host execution/escalation mechanism and retain that external evidence separately. A profile cannot repair an unavailable Keychain or authorize a new login.

The setup cache key includes the profile hash, so changed fixed configuration cannot reuse a previous environment cache entry. A continuation whose parent has a profile hash requires that same hash; a terminal parent from an older runner without the field may still be continued explicitly after current preflight succeeds. These guards never authorize automatic resubmission, and authentication or scope errors remain visible.
