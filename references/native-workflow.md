# Native fallback and existing-session recovery

This reference applies to explicitly chosen native Desktop Code consultations, requests proven unsent before selecting native fallback, and existing native `SENT`/`UNKNOWN` conversations. For new interactive browser consultations, use [browser workflow](browser-workflow.md); use [official CLI workflow](cli-workflow.md) for CLI execution. A CLI timeout, model mismatch or incomplete answer does not permit an automatic native resend. No CUA step is required for CLI collection.

## Reuse before probing

Read the current host's native-control documentation. Windows and macOS APIs differ; use only calls actually exposed here. No supported native route means preserve the packet and report the limitation. Do not install a bridge or switch a sent/ambiguous request to CLI, browser chat or API.

Reuse the existing app handle, project and conversation. Validate capability through the next necessary action and its result; avoid a separate click-test tour. Prefer current semantic elements, with coordinates only from a fresh screenshot. Refresh the affected state after meaningful changes. Do not take a full screenshot, reacquire the app or reopen model pickers after every focus change.

A completed click/setValue is not proof of selection or typing. Check the resulting label or composer text. Use AX text for routine checks; if AX and pixels disagree, acquire one fresh matched observation of the same conversation. Do not combine an old AX “finished” with a newer screenshot showing “Working.” Unresolved conflict means completion remains unverified.

## Project and model

Reuse the owning checkout; do not create a worktree, switch branches or clone for consultation. Prefer a visible absolute project path; allow one alternative native check. Record Local/remote context and extra roots when exposed, otherwise unknown.

If only the project basename is visible, use the selected exact root, an unambiguous matching native project and a uniquely identified packet at that absolute path. The dispatch requires reading that packet first, stopping on access failure. An observed read plus a marker absent from the dispatch and a content-specific fact can corroborate access. Label it **content-corroborated; absolute native root not shown**. This is not proof of all workspace configuration or a strict pre-analysis handshake; record when evidence actually became available. Ambiguous duplicate projects need exact binding; implicit workspace-wide context needs more than packet access.

Confirm selected `Opus 5.5` and labelled `Ultracode`, not merely available menu entries. If the UI separates Ultracode and effort, set and record the numeric effort requested by the frozen wrapper; the new CLI-equivalent wrapper requests `xhigh`. Existing native requests retain their original target. Ultracode alone does not establish maximum model effort. Preserve that evidence across focus changes; invalidate it after project, conversation, execution context or setting changes. An ineffective selector uses the shared recovery budget below. An unavailable control does not prove the model absent. No silent substitution.

## One UI owner, independent progress

Use one UI owner across advisers and monitoring. Keep each short action/observation transaction on one app; separate cross-app calls so partial failures are attributable. File preparation, hashing and report checks can run concurrently. Send a ready route while another awaits setup or approval.

While generating, inspect exact completion paths after about 30 seconds, then back off to 60 seconds if unchanged. About once per minute, check the same conversation for progress or approvals; check sooner on completion-file change or a user signal. Do not continually refocus apps or reread full transcripts. Unchanged monitoring stays quiet; report meaningful changes and required actions. Each wait should permit interruption within 60 seconds.

## One recovery, then one handoff

Persist the stage, observation time/locator, actual control result, pending approval, and recovery attempts for this conversation and native capability. A control that returns success without effect counts as an unsuccessful action. Share one recovery budget across model, project and composer controls; do not restart it after compaction or for each new selector.

After an ineffective action, reacquire the target and observe once, then retry the necessary action once. If still ineffective, stop automated mutations and make one consolidated handoff covering the remaining project/model/composer steps. Retain read-only monitoring. A relevant user or environment change may justify a new attempt; record why, and use the next necessary action rather than assuming all controls recovered.

Preserve existing authorization. An unresolved real permission prompt follows the host's confirmation rules; completed trust/registration is not asked again. Never change security presets to recover. A human cancellation/Escape stops native actions until the user authorizes continuing.

For manual sending, provide the exact frozen dispatch and destination, ask for one send, and persist `UNKNOWN`, handoff pending, and whether the controller attempted Send **before** making the handoff actionable. Update each adviser independently. Inspect that same submitted turn, then set `SENT`; user confirmation alone is not UI verification. Record any difference between submitted text and frozen dispatch, distinguishing incomplete extraction from confirmed edits. Preserve ID/sentinel and inspect scope-critical clauses; do not resend to repair evidence. Where full text cannot be recovered, state that fidelity limit.

## Collection

A native completion file triggers UI verification, not automatic acceptance. Preserve complete native files, or the same original answer through supported export/full UI text if writes failed. No hidden databases, terminal/HTTP/CDP bridge, intermediary AI or rewrite-as-export. The official CLI route is a separate authorized workflow, not a bridge for this native conversation. One collection recovery is enough; retain partial evidence if unresolved.

## Native checkpoint helper

These session files belong to native delivery. Do not pass a CLI runner's `run.json` to this helper.

Use canonical absolute paths and the available Python executable:

```text
python3 scripts/consult_state.py inspect --session /canonical/a.session.json --session /canonical/b.session.json
python3 scripts/consult_state.py update --session /canonical/a.session.json --event-file /canonical/event.json
```

`inspect` reads sessions and stats only their exact completion files; it returns session hash, dispatch/phase, due/action and legacy status. Optional `--now` accepts a timezone-aware ISO timestamp. It neither reads reports nor proves completion.

For `update`, event JSON contains `expected_sha256` from inspect, unique `event_id`, timezone-aware `observed_at` and `current`. Add `migrate_legacy: true` only for explicit first migration. `current` replaces the whole current observation, not selected keys; preserve still-valid evidence and clear resolved blockers. The helper stores `controller_state` version 1 with current/history and synchronized top-level fields. On a hash conflict, inspect again rather than overwrite.

Required current fields: `phase`, `dispatch_state`, `generation_stopped`, `unresolved_approval`, boolean `input_access_verified`, and `input_access_status` (`unknown`, `partial`, `verified`, `unavailable`). True access verification requires status `verified`. Optional fields include `recovery_count`, `next_check_at`, `blocker`, `conversation_locator`, `controller_send_attempted`, `submission_observed`, `ui_evidence_conflict`, and `evidence` entries scoped to this adviser/session/time/source. `manual_handoff` requires UNKNOWN and no controller Send; SENT requires submission observed and its locator. UI conflict forbids stopped=true. Recovery counts and dispatch state cannot regress. Retain model/effort observations in evidence; do not convert partial reads to true.
