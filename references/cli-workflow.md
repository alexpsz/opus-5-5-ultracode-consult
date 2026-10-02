# Official CLI workflow for new consultations

## Preflight and context

Use the installed official `claude` executable, not a direct API wrapper or a browser chat. Read `--version` and relevant `--help` once after an upgrade. `claude auth status --text` checks authentication without a model prompt; Desktop login alone does not prove CLI authentication. Use the owning project's canonical root as the working directory and record its revision/dirty state. Do not create a worktree or clone for consultation.

Retain normal account/project skills, plugins, MCP, hooks, `CLAUDE.md` and workflows. Ordinary `-p` loads this context. Do not add `--bare`, `--safe-mode`, `--restricted`, `--disable-slash-commands`, a replacement system prompt or an inventory restriction such as `--tools`. These change the harness; removing `Workflow` undermines Ultracode. Account skill/plugin sync also depends on the CLI version, login and account policy, so a loaded inventory is evidence of availability rather than proof that every expected item ran.

The runner uses `--permission-mode dontAsk --allowedTools WebSearch WebFetch`. These are per-run permission grants for relevant web research, not a replacement list of available tools; keep the rest of the harness loaded. The user need not explicitly request searching or page reading on every consultation. An explicit offline instruction or narrower research scope takes precedence in the frozen packet. Use sources when they improve the review, rather than making a network call solely because tools are available.

`dontAsk` denies actions that still require approval; already allowed actions can run. It does not enforce filesystem read-only access. Inspect relevant existing permission rules once and recheck when configuration changes. Preserve explicit deny/ask rules, managed policy and existing hooks; do not edit them or enable blanket bypass to force web access. Network grants do not promise that all harness tools will run without permission friction. Record any actual denial and its effect on the answer, avoid repeating the same rejected action, and keep inherited context/exposure explicit. A permission failure never authorizes resending an existing request.

## Exact target and one launch

Use `claude-opus-5-5`, not the changing `opus` alias. In Claude Code 2.1.286, `--effort ultracode` is accepted even though the brief help lists only numeric effort levels. It requests `xhigh` reasoning plus Ultracode, which orchestrates dynamic workflows for substantive tasks. Ultracode is independent of the numeric level from 2.1.284 onward. This runner targets the named combination; do not silently replace it with `max` or another model.

Scan the outgoing wrapper and text, then use the runner with absolute paths. Project, prompt and run paths must be canonical. The official installed launcher may be a symlink; the runner resolves it and records both requested and resolved executable paths. Choose one deterministic run directory per request/adviser; it must be new on first launch, and its parent must exist.

```text
python3 scripts/run_consult.py --adviser opus --executable /absolute/path/to/claude --project-root /absolute/owning-project --prompt-file /absolute/review-example-01.opus.dispatch.txt --run-dir /absolute/review-example-01.opus.cli --request-id review-example-01 --model claude-opus-5-5 --effort ultracode --sentinel OPUS55_ULTRACODE_RESULT_review-example-01_freshnonce --timeout-seconds 300
```

The helper freezes `prompt.txt`, saves `run.json`, and persists `UNKNOWN` before process launch. It performs no automatic retry or channel fallback. An explicit, separately identified follow-up uses the bundled `--continue-from` path described in [runtime recovery](runtime-recovery.md). `RUN_ALREADY_EXISTS_DO_NOT_RESEND` means inspect that directory; a different directory is not a recovery. Process error/timeout alone does not establish `NOT_SENT`. Preserve the raw stream and recorded native session ID, then inspect the original output read-only; resume flags send a new turn and are reserved for an authorized follow-up. Do not launch another first review.

Wait for the bounded runner while keeping user updates interruptible. Its timeout stops its owned process; timeout is incomplete delivery, not proof of no submission. Native fallback is available only for an explicitly chosen native consultation or a request proven unsent. Existing native requests retain their native conversation.

## Evidence and acceptance

Read [delivery protocol](delivery-protocol.md) for receipt semantics. Preserve `stdout.raw`, `stderr.raw`, `answer.md` and `run.json`; do not reduce the only original stream to selected text. `answer.md` is extracted native final text, not a rewritten summary. Do not ask the model to create these controller files or fabricate a native completion JSON to use the file collector.

The native init event records initial model, project `cwd`, session/version and loaded inventories. It does not prove input access. Confirm packet access through tool-result evidence plus its marker/content fact. The runner also reads main-conversation assistant model metadata, excluding forwarded subagent messages. Final `modelUsage` corroborates usage but may include helper models; do not label those all as the main reviewer. Preserve the complete events behind the compact classification.

Requested flags do not establish effective effort or Ultracode. Caps, environment overrides, model support and disabled workflows can alter them. An absent effective field remains unknown: report `requested_effort=ultracode`, the equivalent requested `xhigh`, and `effective_effort`/`actual_workflow` only when exposed by native metadata. Neither model prose nor merely listing the Workflow tool verifies that Ultracode was active. `CONFIGURED` is not `VERIFIED_NATIVE_METADATA`, and `delivery_status=COMPLETE` does not override `target_verification=MISMATCH` or missing target evidence.

A live 2.1.286 probe completed in 10.554 seconds and showed packet Read plus Opus 5.5 in init, assistant and model-usage metadata. Effective effort and Ultracode were absent. This establishes that probe's transport/read/model path, not verified workflow activation, general timing or acceptance of a substantive review.

That earlier probe did not validate this default web configuration. Confirm actual WebSearch/WebFetch result events in the current run before claiming network access succeeded; retaining a grant in argv alone is insufficient.

Official references: [shared Desktop Code configuration](https://code.claude.com/docs/en/desktop#shared-configuration), [model and Ultracode settings](https://code.claude.com/docs/en/model-config#adjust-effort-level), [headless context and streams](https://code.claude.com/docs/en/headless), [CLI flags](https://code.claude.com/docs/en/cli-reference).

The runner exits 0 only for complete delivery with matching configured or verified target metadata. This is not proof of effective effort when that field is absent, nor a factual-review verdict. A native Antigravity print-timeout warning invalidates completion even when the process exits 0 and retains a partial answer.

For default web preflight, reusable setup records, visible login handoff, manifest path checks, live progress, explicit same-conversation follow-up and offline access-evidence collection, follow [runtime checks and recovery](runtime-recovery.md).
