---
name: opus-5-5-ultracode-consult
description: Obtain an independent project or artifact review from the exact Opus 5.5 and Ultracode selections in Claude desktop Code, using the host's supported native computer tools and shared project files. Use for this requested second opinion, not Claude API or terminal automation.
license: MIT
metadata:
  version: "1.0.0"
---

# Opus 5.5 Ultracode Consult

Requirements: a signed-in Claude desktop Code workspace, the exact requested model and effort in its current picker, and host-supported native computer control. Offline helpers require Python 3.10+. macOS native interaction is not yet end-to-end verified.

Obtain one independent answer, preserve the complete original, then verify its claims locally. The target names describe what to select; they are not a promise that a particular account or current product offers those options.

An explicit consultation request authorizes sending its question and necessary evidence to Claude, and writing the named report files in the owning project. It does not authorize unrelated uploads, product edits, terminal execution by the adviser, installs, commits, publication, or security changes. Apply the user's existing scope without asking again for the same authorized send or report write. Automatic skill discovery alone is not permission to transmit private material: establish that the user requested this consultation before dispatch.

## Host and target

Read [native workflow](references/native-workflow.md) and the currently available host's computer-use documentation before native actions. Use that host's supported interface. Windows `@oai/sky` and macOS computer APIs are different interfaces; never copy one platform's calls into the other. If native control is unavailable, prepare the packet and report that limitation. Do not silently switch to a browser, CLI, API, hidden application data, or a different model.

Verify the selected model **Opus 5.5** and selected effort **Ultracode** in the current conversation immediately before Send. A subscription badge, an unlabelled maximum slider, or a prior session's setting does not prove either. Inspect once, select if available, and reopen once if the state is unclear. If still unresolved, retain the packet and report the observed blocker.

## Project and neutral evidence

Use the user's chosen project root or the project that owns the artifact. Read its applicable instructions. Record root, branch, HEAD and dirty state with ordinary file tools when it is a Git repository; never initialize, clean, switch branch or copy a repository just for consultation.

Reuse the existing native project. Prefer its visible absolute folder path as binding evidence. If the UI only shows a basename, use the bounded corroboration route in the native workflow: the explicitly chosen root, matching native project, and an actual read of a fresh uniquely identified packet at that exact path. Record this as **content-corroborated**, not as a UI-confirmed absolute path. Do not loop through file managers merely to improve the label. Ambiguous duplicate projects or failed exact-file access remain blockers to relying on repository context.

Use [packet template](references/context-packet-template.md) for a shared neutral packet, bounded input manifest, and short dispatch. Put new review files in the project's existing review location, ordinarily `docs/reviews`. Do not create one workspace or folder per model. Give each adviser different output filenames and one writer per output.

Include actual artifacts, traceable facts, counterevidence, unknowns and the user's decision. Exclude the controller's preferred answer, rankings, prior model verdicts and other advisers' reports from the first review. Preserve an artifact's own rationale. Record unavoidable project rules, memory, open-buffer and prior-conversation exposure; a fresh chat alone does not prove independence.

Project selection is access permission, not evidence of reading. Require visible reads or content-specific references for essential inputs. When an input is missing, provide its approved contents or limit the result explicitly. Distinguish saved files from unsaved buffers.

Inspect the exact outgoing text and scan it offline:

```text
python3 scripts/check_packet_safety.py /absolute/path/to/packet.md /absolute/path/to/selected-text.txt
```

Use the host's available Python executable on Windows. The scanner is a credential heuristic; manually check personal information, private URLs and screenshots too. Redact outgoing copies without changing source evidence. Do not upload a whole repository or raw media by default.

## Send once and collect

Use [delivery protocol](references/delivery-protocol.md). Prefer native file reads and a complete first answer written directly to the named report, followed by completion JSON. Send a short dispatch pointing to those files, not a large pasted duplicate. If native file capability is unavailable before Send, use approved inline evidence and same-chat export.

Observe and focus the actual composer, enter the dispatch, and read back its complete text, request ID, permitted paths and sentinel. Verify selected project, Local/remote context, model, effort and attachments. Serialize native UI actions when consulting several apps.

Persist `NOT_SENT`; immediately before the single Send action persist `UNKNOWN`; set `SENT` only after seeing this request as a submitted user turn. A failed click can still submit. Recover `SENT` or `UNKNOWN` in the same conversation; never resend to obtain certainty. Preserve unrelated drafts and runs.

Wait in bounded intervals and inspect completion locally. Accept a consultation only after generation visibly stops, no unresolved approval/tool request remains, the full answer is collected, and its final nonempty line is the exact unique `OPUS55_ULTRACODE_RESULT_<request-id>_<nonce>` sentinel. Validate named files with the collector and its create-only receipt. A completion marker, notification, filename echo or matching hash alone does not establish reading or factual accuracy.

If collection is truncated, reacquire the same answer once using supported export or UI text; otherwise report incomplete. Never ask for a reconstruction as an export, route content through another AI composer, or change security settings to unblock collection. Keep the original request ID and sentinel when recovering a prior run.

## Local conclusion

Preserve the first answer before introducing local views. Verify material claims against source evidence and decide what to adopt. A focused follow-up may resolve a consequential gap, with its own identifier; it is not another independent review.

Report the requested and observed model/effort, host/app, project binding method and revision, conversation locator, dispatch state, collection/protocol status, recommendation, material uncertainty and local adoption decision. Keep package tests, native UI checks and actual end-to-end consultation status separate. No report or model agreement expands the user's execution authority.
