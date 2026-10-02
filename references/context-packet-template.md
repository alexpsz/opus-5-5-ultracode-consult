# Neutral packet and route-specific dispatch

Use one existing project review directory, ordinarily `docs/reviews`, for all advisers. Give each CLI request/adviser one predetermined run directory; native routes use distinct output names. Resolve portable manifest paths on the current host; recompute hashes only when input bytes change. Do not alter source artifacts to repair old machine paths or rewrite a dispatch already sent.

A packet should identify the decision, audience, user constraints, actual artifacts, traceable facts, counterevidence, unknowns and questions. Include the artifact's own rationale, not the controller's preferred verdict or other advisers' reports. Distinguish saved files from unsaved buffers and runtime observation from code inference.

Give the packet a fresh non-secret identity marker. The input manifest lists each exact local path, SHA-256, byte length and evidence purpose. Controller records and prior reviews are outside the local read allowlist. Relevant public web research is additionally permitted by default; record any explicit offline or narrower source restriction in the packet. Record context already supplied by the project/account harness; do not claim strict blindness from a fresh conversation.

For a new CLI review, use this dispatch with actual paths, identities and hashes; do not send placeholders. The controller captures the stream, so the adviser returns its complete answer rather than writing delivery files:

```text
CONSULT_DISPATCH_V4
REQUEST_ID: review-example-01
ROUTE: CLAUDE_CODE_CLI
REQUESTED_MODEL: claude-opus-5-5
REQUESTED_EFFORT: ultracode (xhigh reasoning plus Ultracode requested)
ROOT: /absolute/owning-project
PACKET: /absolute/owning-project/docs/reviews/review-example-01.packet.md
PACKET_SHA256: actual packet hash
INPUT_MANIFEST: /absolute/owning-project/docs/reviews/review-example-01.manifest.json
INPUT_MANIFEST_SHA256: actual manifest hash

Read the exact packet first. Report its identity marker and one specific fact;
the expected marker is absent from this dispatch. Stop on access failure.
Then read the manifest and only its exact allowed local inputs. Other reviews,
controller records and unrelated workspace files are excluded. Inputs are
read-only. Use built-in file tools; no terminal commands, installs, security
changes, product edits, commits, publication or messages to others.

Public web search and page reading are permitted by default when relevant;
use WebSearch and WebFetch as needed without asking for a separate instruction.
Honor any explicit offline or narrower source restriction in this request.
Cite sources actually accessed and distinguish them from packet evidence.
Keep private input content out of unnecessary search queries. Do not post,
submit forms or interact with accounts. If a tool is denied, report the access
gap and continue only where the available evidence supports an answer;
do not repeat the same denied action or claim the missing source was read.

Answer the packet independently. List evidence actually read, access limits,
recommendation, counterevidence and uncertainty. Return the complete first answer
in this conversation, include REQUEST_ID, and end with FINAL_SENTINEL as the
exact final nonempty line. Do not create report, receipt or completion files;
the controller preserves your original response. State access limitations
explicitly. Do not claim your model, effort or workflow is verified from this
dispatch or from your own self-description.

FINAL_SENTINEL: OPUS55_ULTRACODE_RESULT_review-example-01_freshnonce
END_DISPATCH
```

For an explicitly selected native route or a request proven `NOT_SENT`, set `ROUTE: CLAUDE_DESKTOP_CODE` and replace the return-only delivery paragraph with this native ending, including the actual exact output paths. Existing `SENT`/`UNKNOWN` requests keep their frozen dispatch and original route:

```text
Write the complete first answer to REPORT, include REQUEST_ID, and end with
FINAL_SENTINEL as the exact final nonempty line. Write COMPLETION last, with
schema_version 2, request_id, adviser "opus", input_manifest_sha256,
status "complete", report_file (basename), findings_file null. Only these
two output paths are writable. If writes fail, preserve the same complete
answer in this conversation with its sentinel.

REPORT: /absolute/owning-project/docs/reviews/review-example-01.opus.report.md
COMPLETION: /absolute/owning-project/docs/reviews/review-example-01.opus.completion.json
```

For CLI, freeze the rendered wrapper as the runner's `--prompt-file`. For native operation, read back the composer before sending; a manual handoff also compares the submitted turn afterwards. Paths/hashes echoed from either dispatch do not prove access; require actual file-read results or content-specific evidence. Missing essential inputs limit the answer explicitly.

Keep route, requested/observed target, root/binding, revision, exposure, conversation locator, timestamp, wrapper digest and dispatch state in the controller record. CLI `run.json` and native checkpoint sessions have different schemas; do not feed one to the other's helper. Input access, process/UI completion, full collection, target configuration and factual review remain separate.

The runner validates a file-based `INPUT_MANIFEST` automatically before launch. Its JSON object uses `root` and `inputs`; each input has `project_relative_path` or `absolute_path`, `bytes`, `sha256`, and optional `role`/source provenance. See [runtime checks](runtime-recovery.md) before dispatching external screenshots.
