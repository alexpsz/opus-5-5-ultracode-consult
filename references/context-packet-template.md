# Shared packet and dispatch

Use a project-relative input manifest for portability, then resolve exact absolute paths on the destination host before dispatch. Never rewrite source artifacts to make an old machine's paths valid. Recompute hashes after any intentional redaction or derived bundle change. Keep controller sessions and prior opinions outside the adviser's exact allowlist.

## Neutral packet

```text
CONTEXT_PACKET_V2
Request: review-example-01
Packet identity marker: a fresh non-secret random identifier
Decision and intended audience:
User goals and constraints:
Artifact and intrinsic rationale:
Known facts with file/section references:
Counterevidence and conflicting observations:
Unknowns and tests not performed:
Neutral alternatives to assess:
Questions:
  What works, what fails, and what evidence supports each judgment?
  What are the highest-value changes, tradeoffs, and remaining uncertainties?
Deliverable: full independent report; distinguish observed fact from inference.
```

The headings are a scaffold, not questions to send unfilled. Use only relevant ones. A manifest can list `path`, `sha256`, `bytes`, `media_type` and a short evidence purpose for each exact input. Hash the completed manifest and use that same digest across independent advisers. Preserve one common neutral packet rather than producing biased variants.

## Short native dispatch

Replace the illustrative paths and values with actual current-host values. The root and packet are absolute; the allowed manifest entries must be unambiguously resolved beneath the recorded root or explicitly separately authorized locations. No recursive repository access is implied.

```text
CONSULT_DISPATCH_V3
REQUEST_ID: review-example-01
ADVISER: opus
MODEL: Opus 5.5
EFFORT: Ultracode
ROOT: /absolute/owning-project
PACKET: /absolute/owning-project/docs/reviews/review-example-01.packet.md
PACKET_SHA256: actual packet hash
INPUT_MANIFEST: /absolute/owning-project/docs/reviews/review-example-01.manifest.json
INPUT_MANIFEST_SHA256: actual manifest hash

Read the exact packet first. Report its identity marker and one content-specific
fact. If the file cannot be read, stop and state the access limitation; do not
guess its contents or search other folders. Then read only the manifest's exact
allowed inputs. Do not read controller records, other reviews, or unrelated
workspace content. Product inputs are read-only. Use native file tools only;
do not execute terminal commands, install packages, change settings, commit,
publish, or contact others.

Write the complete first answer to the report path below, then the completion
JSON last. Include request ID, evidence actually read, recommendation,
counterevidence and uncertainties. The report must end with the exact sentinel.
Completion uses schema_version 2, request_id, adviser, input_manifest_sha256,
status "complete", report_file (basename), and findings_file null.
If native writes fail, keep the full answer in this same chat with the sentinel.

REPORT: /absolute/owning-project/docs/reviews/review-example-01.opus.report.md
COMPLETION: /absolute/owning-project/docs/reviews/review-example-01.opus.completion.json
FINAL_SENTINEL: OPUS55_ULTRACODE_RESULT_review-example-01_freshnonce
END_DISPATCH
```

For macOS/Linux use actual POSIX paths; for Windows use actual drive paths. Python helpers do not translate one machine's paths into another's. Do not send the illustrative dispatch or fabricate checksums.

## Controller observations

Persist request identity, manifest digest, native conversation locator, chosen and observed model/effort, selected root and binding method, revision/dirty state, allowed context and exposure, wrapper digest, dispatch state and timestamps. Keep generation stop, collection completeness, protocol validation and factual review separate. Store exact output names following the delivery protocol. These controller records are not first-review evidence.
