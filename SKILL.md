---
name: opus-5-5-ultracode-consult
description: Obtain an independent Opus 5.5 review with Ultracode through official Claude Code CLI, preserving the full harness and original answer; recover existing native consultations in their original conversation.
license: MIT
metadata:
  version: "1.4.0"
---

# Opus 5.5 Ultracode Consult

Obtain one independent answer through the official Claude Code CLI, preserve the original, and verify material claims locally. New consultations default to CLI with the normal project/account harness. Requires Claude Code, its own valid authentication, the requested model configuration, and Python 3.10+ for helpers. Native Desktop Code remains available for explicitly requested native work and recovery of existing native consultations.

Relevant public web search and page reading are part of ordinary consultation; the user need not request them separately each time. Use them when they help resolve the question, cite the sources actually accessed, and obey an explicit offline or narrower scope. This default does not authorize web interaction, publication or unrelated disclosure.

A user-requested consultation authorizes necessary evidence transfer and controller capture of the answer. Reuse existing authorization, including completed project trust. Skill discovery alone does not authorize transmission. Running the official CLI as transport does not authorize the adviser to run shell commands, edit products, install software, upload unrelated material, publish or change security settings. Native report writes require the exact named output paths.

## Resume or prepare

Start with the request's existing route and artifacts. For CLI, inspect its `run.json` and raw output; for native sessions, use `scripts/consult_state.py inspect --session /canonical/session.json`. These are different schemas. Reuse the request ID, frozen packet, conversation and valid observations. `SENT` and `UNKNOWN` stay on the original route and conversation; a timeout, failed collection or missing model field never authorizes resending or switching channels. Only a definitely unsent request can start a replacement route.

For new or changed evidence, read [packet and dispatch](references/context-packet-template.md). Use the owning project and applicable instructions; record its root, revision and dirty state once. Keep a common neutral packet and exact input allowlist, distinct output names and one writer per output. Exclude other advisers' opinions and local preferred answers; record unavoidable project or conversation exposure. A fresh chat alone is not a blind review.

Scan the outgoing packet and selected text with `scripts/check_packet_safety.py`; manually check screenshots, personal information and private URLs. Redact outgoing copies, not sources. A scanner pass is only a credential heuristic.

## Operate and dispatch

Read [CLI workflow](references/cli-workflow.md) for new consultations. Use the single-shot runner with `claude-opus-5-5` and `ultracode`; preserve ordinary skills, plugins, MCP, instructions and workflows. Preapprove `WebSearch` and `WebFetch` with `--allowedTools` while retaining `dontAsk`; this grants those tools permission without restricting the available tool inventory. Do not use a bare/minimal mode, `--tools` restriction or blanket permission bypass. Keep explicit deny/ask and managed rules; other harness capabilities may still require approval. `dontAsk` is not a read-only sandbox.

Separate requested configuration from runtime evidence. On current Claude Code, `--effort ultracode` requests `xhigh` plus the Ultracode workflow setting, not maximum reasoning. If native metadata omits effective effort or workflow state, report those as unverified; the model's prose cannot fill the gap. Do not substitute a different target.

Prepare evidence and inspect files in parallel; dispatch each ready adviser without waiting for blocked routes. The runner freezes one request in one predetermined run directory and records `UNKNOWN` before launching. Its guard must not be bypassed with another directory or request ID.

Use [native workflow](references/native-workflow.md) only for an explicitly selected native route or a CLI request proven `NOT_SENT`. Preserve existing native `SENT`/`UNKNOWN` conversations. One controller owns UI actions, with one shared recovery attempt and consolidated manual handoff. No CUA is needed for ordinary CLI operation.

Read [runtime checks and recovery](references/runtime-recovery.md) before dispatch or continuation. Every runner launch checks default web policy and declared input hashes; prepare Gemini evidence inside the owning project or reuse exact existing read grants. Reuse matching local setup observations, use one visible terminal for required login, and classify host, authentication, model and tool-permission failures separately. Use the bundled `--continue-from` only for an authorized new follow-up, preserving web defaults and the recorded native session. Watch live receipt phases; collect access evidence offline after completion.

## Collect and conclude

Read [delivery protocol](references/delivery-protocol.md). CLI collection retains raw output and the exact native final text; native collection retains adviser-written files or the original UI answer. Neither route may fabricate a model-written completion record. Delivery integrity, target verification, input access and factual accuracy are separate. Recover the same answer once if incomplete; do not request a reconstruction.

Report route, requested and observed model/effort/workflow, project binding, exposure, dispatch and collection status, material uncertainty, and locally supported findings. A focused follow-up has its own ID and is not another independent first review. Keep CLI probe success, helper tests, assisted native delivery and full review acceptance distinct.

On native Windows, follow [Windows CLI setup](references/windows-setup.md) before the first dispatch. Generate a machine-local profile; never reuse a macOS profile or another user’s credentials.
