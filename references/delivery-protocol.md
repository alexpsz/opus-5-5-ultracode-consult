# Shared-directory delivery protocol

Use schema 2 for new requests. One existing project review directory can contain several advisers' outputs. Each request gets distinct named report and completion files; one adviser owns each pair. Only those files are writable. Other files in that directory are neither read nor modified implicitly.

## Adviser output

Write the complete report first and completion JSON last. Use native file tools; terminal execution is not needed. The report includes its request ID, full answer, evidence actually read, counterevidence and uncertainty. Its final nonempty line is the exact request sentinel, without trailing spaces.

Example completion:

```json
{
  "schema_version": 2,
  "request_id": "review-example-01",
  "adviser": "opus",
  "input_manifest_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "status": "complete",
  "report_file": "review-example-01.opus.report.md",
  "findings_file": null
}
```

The digest is illustrative; use the actual common manifest SHA-256. A report-only review is sufficient. Structured findings are optional, not another mandatory copy of the prose.

## Controller record

Keep the session and receipt outside the adviser's named read/write scope. These files may share the review directory because access is defined by an exact allowlist. The collector requires absolute paths on the machine where it runs.

```json
{
  "schema_version": 2,
  "request_id": "review-example-01",
  "adviser": "opus",
  "input_manifest_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "output_directory": "/absolute/owning-project/docs/reviews",
  "report_file": "review-example-01.opus.report.md",
  "completion_file": "review-example-01.opus.completion.json",
  "findings_file": null,
  "findings_required": false,
  "sentinel": "OPUS55_ULTRACODE_RESULT_review-example-01_freshnonce",
  "dispatch_state": "SENT",
  "generation_stopped": true,
  "unresolved_approval": false
}
```

These final observation values are not defaults: start `NOT_SENT`, write `UNKNOWN` before the single Send action, and record `SENT` only after visible submission. Set generation/approval fields from current UI evidence, not from the completion file. The session may also contain model, binding, timestamps, exposure and conversation metadata.

## Local collection

After visible generation stop and complete delivery, run:

```text
python3 scripts/collect_delivery.py --session /absolute/review-example-01.opus.session.json --receipt-file /absolute/review-example-01.opus.receipt.json --stable-seconds 1
```

On Windows substitute the available Python executable. The command creates a receipt only; it does not send data or edit the report. It reads only exact named outputs, validates identity/schema/final sentinel, compares stable bytes twice, and creates SHA-256 receipt metadata. An identical retry preserves the receipt. Changed reports or conflicting/partial receipts fail; never repair an adviser report merely to force PASS.

`PASS` means protocol integrity only. It does not prove the selected model, stopped UI, complete artifact access or factual correctness; those require independent controller observations. This helper is not a sandbox against an actively hostile concurrent process.

The collector rejects symlink/reparse/hardlink outputs, path traversal, alternate streams, unsafe names, oversize files, controller/output overlap, duplicate JSON keys, changed files and incomplete identities. Use intentionally verified canonical local paths. On macOS, system temporary aliases such as `/tmp` can resolve to `/private/tmp`; choose the canonical path before writing a controller record, and do not blindly resolve untrusted adviser paths. Network/UNC locations and OneDrive reparse-backed files may require moving the **review outputs only** to an approved ordinary local directory; do not clone a repository as a workaround.

Schema 1 remains supported only for recovering existing fixed-name sessions with `--snapshot-dir`. Do not rename a sent request or send it again for migration. New requests use schema 2.

## Fallback

If native file capability fails, preserve the original full answer from the same conversation via supported export or full UI text. Do not resend, ask for a rewrite-as-export, or inspect hidden stores. If the complete answer cannot be recovered once, report collection incomplete and retain partial evidence. A substantive follow-up gets a fresh ID.

## Optional findings schema

Set `findings_file` to an exact authorized basename in both session and completion; set `findings_required` true only when needed. The JSON contains schema_version, request_id, adviser, input_manifest_sha256, recommendation (string), findings (array), evidence_read (string array), and unknowns (string array). Each finding contains id, severity (`info`, `low`, `medium`, `high`, `critical`), claim, file (string/null), line (positive integer/null), trigger, evidence_kind, counterevidence and suggested_check. Use null locations for non-code findings; do not invent source lines.
