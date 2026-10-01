# Native workflow and bounded recovery

## Choose the host interface

Discover the computer-control tools actually available in this session and read their current documentation. Do not vendor another tool's implementation or rely on a fixed installed skill version. Native Claude Code remains the destination on every platform.

| Host | Route | Verification status of this release |
| --- | --- | --- |
| Windows | Host-supported native computer tools. Where the installed Computer Use documentation exposes `node_repl` with `@oai/sky`, use only the documented calls. | Offline Python checks executed; full consultation was not rerun for this release. |
| macOS | Host-supported native macOS computer tools, after reading their own documentation and required permissions. | Workflow designed for this route; native end-to-end run not performed. |
| Linux | Use native control only if both the host and installed destination actually support it. | No native compatibility claim; offline helpers are portable Python. |

A browser tool saying “native APIs disabled” does not establish that a separately installed native tool is unavailable. Conversely, the presence of a skill file does not prove a working native tool. If none is callable, stop native actions, keep the packet and state the missing capability. Do not install tools or change OS/app security settings as an implicit recovery.

## Observe, act, observe

Select the existing Claude window and Code workspace from current native state. Preserve other tasks and drafts. Use semantic elements when exposed; use coordinates only from a fresh screenshot. Refresh after navigation, opening a menu, changing model/effort, focusing the composer or submitting. Accessibility text can lag behind a screenshot; resolve a mismatch with one new observation before acting.

Use a new conversation only when this request is definitely `NOT_SENT`. Reuse the verified existing project root. Inspect Local versus cloud/remote execution, branch/worktree and extra workspace roots if the app exposes them; record fields not exposed as unknown. Never change branches or create a worktree to simplify consultation.

## Bind the right project without UI loops

The controller records the owning root with ordinary filesystem tools. Resolve an intentionally selected path once and inspect whether it identifies a different checkout; do not accept a symlink destination merely because it has a similar name.

Prefer either a folder-picker description or existing project settings showing the full path. One direct check and, if necessary, one alternative native check is enough. Do not repeatedly open Explorer/Finder or search unrelated folders for stronger evidence.

If only a basename is visible, all of the following permit a bounded fallback:

1. The user or artifact context has selected one exact local root; no competing duplicate is apparent.
2. The native workspace visibly matches that project and the intended Local/remote context.
3. The controller has created a uniquely named packet inside the selected root, with a fresh random identity marker and recorded hash.
4. The submitted dispatch requires reading that exact absolute packet path first and reporting the marker and a content-specific fact. It requires stopping with a binding/access limitation before examining other files if the first read fails.

Before submission label this `content corroboration pending`. After an observed native read or a checkable response, label it `content-corroborated; absolute native root not shown`. This confirms access to the intended packet, not an otherwise invisible workspace configuration. If a task requires implicit workspace-wide context, this fallback is insufficient; supply bounded contents or obtain the precise native root.

Never expose a real token as the identity marker. This is a non-secret random string that only identifies the packet. Model echo of a path, project title or hash supplied in the dispatch alone does not corroborate access.

## Verify model and effort

Open the current model picker. Confirm its selected option is `Opus 5.5`, not a menu entry that is merely available. Then inspect effort and select the labelled `Ultracode` option. A slider must show that label; do not infer it from its numeric maximum. Read back both selections immediately before dispatch. New conversations can reset effort.

Target labels are account- and version-dependent. If a selector or exact option is absent, reopen once and record the observed options. A login error, expired session or control failure is not proof of model absence. Do not substitute Extra, another Opus generation, Sonnet, a browser chat, CLI or API without explicit user direction.

## Composer and submission

Click the observed prompt, refresh, confirm focus, type the short dispatch and read it back in full. Never type into a terminal, source editor, search box or uncertain focus. If file mentions are available, select only the allowed inputs. The dispatch and packet define reads precisely; project binding alone is not permission to read other reports.

Store `UNKNOWN` before Send, click once and observe the submitted user turn before storing `SENT`. If a tool errors, recover the same conversation and inspect before deciding anything. Never create a duplicate request after `UNKNOWN`.

If the user stops computer control, including a host-reported user cancellation or Escape stop, stop native actions and checkpoint the existing dispatch state. Do not treat a human stop as a transient failure to retry. Resume native interaction only after the user authorizes continuing; a cancelled Send remains UNKNOWN until the same conversation can be inspected.

If an actual permission prompt appears, apply the host's confirmation rules and existing user authorization. Do not change permission presets, disable checks or retry an expired app approval indefinitely. Continue independent local preparation and accurately report a remaining blocker.

## Collection and recovery

Poll the named completion file, then check the same conversation for stopped generation and pending requests. A file or toast by itself is insufficient. Read and preserve the complete report; validate it with the local collector. Do not have the adviser hash its own result as a substitute for controller validation.

If native files are unavailable, supported export or full native UI text from the same answer is the fallback. Do not inspect hidden conversation databases or use a terminal/HTTP/CDP bridge to obtain it. One bounded collection recovery is enough; preserve a partial result and label it incomplete if the full answer remains unavailable.
