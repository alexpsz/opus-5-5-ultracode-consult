# CLI capture and native file delivery

Choose the protocol belonging to the original route. Never convert a CLI failure into a newly sent native review, or fabricate an adviser completion file from controller-extracted text.

## Official CLI capture

`scripts/run_consult.py` creates one directory containing frozen `prompt.txt`, `run.json`, exact `stdout.raw`/`stderr.raw`, and `answer.md` when the native final event includes nonempty answer text. `run.json` is a controller receipt, not an adviser-written completion declaration. The runner saves prompt/output hashes and exact argv; preserve every original file. It does not use `collect_delivery.py`, its schema-2 completion format, or a native `.session.json`.

Treat receipt fields independently:

- `dispatch_state`: `UNKNOWN` is persisted before launch; only native response evidence moves it to `SENT`. Process failure or missing output does not reset it to `NOT_SENT`.
- `process_status`: success, error, interruption or timeout describes the owned process. It does not establish a complete answer.
- `delivery_status=COMPLETE`: requires successful process exit, a successful native final event, nonempty final text, matching sentinel when supplied, and no observed native error or denial. Always supply a request-specific `--sentinel` for consultation.
- `target_verification`: `CONFIGURED` identifies matching reported model configuration with incomplete effort/workflow evidence. `VERIFIED_NATIVE_METADATA` requires the runner's native fields, not model prose. `MISMATCH` and `UNKNOWN_UNVERIFIED` stay explicit even when delivery is complete. Metadata is local CLI evidence, not backend-signed attestation.
- `requested_effort`, `effective_effort`, `ultracode_requested` and `actual_workflow`: keep request and observation separate. Missing effective fields remain null/unknown; an Opus answer alone does not verify Ultracode.

The controller should compare the native model events, read/tool results, packet marker and complete answer with the approved scope. A claimed Read or echoed path alone is insufficient. Do not edit `answer.md` or raw output to force acceptance. Timeout, authentication failure, denied required reads, incomplete final text or missing sentinel calls for inspecting the same run; the create-only run directory prevents accidental repeat dispatch. Recover the existing CLI session by its recorded native ID when supported. A substantive new follow-up has a new ID and is not an independent first review.

## Native exact-file delivery

New requests on the native route use schema 2. The adviser writes its complete report first and completion JSON last, only to the two named paths. The report includes its request ID, actual evidence, limitations and full answer; its final nonempty line is the exact sentinel without trailing spaces. Structured findings are optional. The rest of this section applies only to native delivery and existing native recovery.

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

Replace the illustrative digest. Keep controller session, receipt and original-answer archive outside the adviser's exact read/write allowlist, even when sharing its directory.

The session uses the same identity and includes absolute `output_directory`, exact `report_file`, `completion_file`, nullable `findings_file`, `findings_required`, `sentinel`, `dispatch_state`, `generation_stopped` and `unresolved_approval`. Start `NOT_SENT`, false, false; set approval state from actual prompts. `UNKNOWN` is required before controller Send or manual handoff. Only observed submission permits `SENT`. Set stopped/approval fields from current UI, never from output-file existence.

After complete delivery and visible generation stop:

```text
python3 scripts/collect_delivery.py --session /absolute/review-example-01.opus.session.json --receipt-file /absolute/review-example-01.opus.receipt.json --stable-seconds 1
```

Use the available Python executable. The schema 2 command validates named outputs and automatically preserves their exact original bytes in the sibling `<receipt-file>.archive` directory, writing `.archive-receipt.json` inside it last. Optional `--archive-dir /canonical/other-directory` selects another canonical archive. Only then accept the integrity receipt. Other advisers' files are irrelevant; collection validates stable bytes, schema, identity and final sentinel. Never edit adviser output to force PASS.

`NOT_SENT` and `DISPATCH_UNKNOWN` are distinct failures, not instructions to send. Recover the original conversation for UNKNOWN. Invalid state values are schema errors. An identical retry preserves its archive/receipt; partial or conflicting archives are never overwritten. Investigate changed outputs or records. `PASS` is protocol integrity only; UI/model evidence, input access and material claims remain independently assessed.

Use verified canonical local paths. Link/reparse/hardlink outputs, traversal, alternate streams, unsafe/duplicate names, oversized files, controller overlap and duplicate JSON keys are rejected. On macOS prefer `/private/tmp` over its `/tmp` alias when using temporary storage. An unsuitable network or sync-backed directory may require moving approved review outputs, not cloning the repository. The helper is not protection against a hostile concurrent process.

Schema 1 is only for recovery of existing fixed-name deliveries with `--snapshot-dir`; do not rename or resend an existing request to migrate it.

If native writes fail, recover the original complete answer once through supported export or full UI text in that same conversation. Preserve any partial result and report incomplete if recovery fails. A new substantive follow-up has a fresh ID.

Optional findings: authorize an exact `findings_file` in session/completion; require it only when needed. Its schema contains schema_version, request_id, adviser, input_manifest_sha256, recommendation, findings, evidence_read and unknowns. Each finding has id, severity (`info`, `low`, `medium`, `high`, `critical`), claim, file, line, trigger, evidence_kind, counterevidence and suggested_check. Use null locations for non-code claims.
