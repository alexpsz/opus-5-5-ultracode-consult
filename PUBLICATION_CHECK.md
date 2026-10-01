# Publication check

Checked 2026-10-01. This record describes the public package, not any private consultation or applicant artifact.

## Packaging and privacy

- Entry point name matches the package directory; YAML frontmatter includes a scoped description, MIT license and explicit runtime limits.
- Public instructions were rewritten to remove user-specific paths, account names, private repository names, personal artifacts, conversation locators and historical consultation examples.
- No screenshots, app sessions, account data, private reports, credentials, source media or third-party computer-control implementations are bundled.
- All bundled test data is synthetic. Credential-shaped strings are assembled as synthetic test fixtures; they are not usable secrets.
- Source skill directory contained no third-party license or attribution files. The owner's reusable instructions and standard-library helpers are published under the bundled MIT license. Provider names identify required interfaces and imply no endorsement.
- The file layout and frontmatter were checked against the public [Agent Skills specification](https://agentskills.io/specification); this is format conformance, not marketplace certification.

## Interaction walkthrough

These are document-level scenario checks. They are not a live model call or a claim of a Mac UI test.

| Scenario | Expected and reviewed behavior |
| --- | --- |
| Mac host lacks the Windows native library | Discover and read the Mac native tool documentation; never import or imitate Windows calls. If no native tool exists, retain the packet and report capability unavailable. |
| Opus is available but current effort is Extra | Select the labelled Ultracode control and read it back immediately before Send; no inference from maximum slider position. |
| Requested model is not in the current picker | Reopen once, report observed choices, do not substitute another model or app. |
| Existing project UI exposes only a basename | Try at most two direct path surfaces, then use an exact uniquely identified packet read as bounded corroboration when the root is unambiguous. Report the weaker binding evidence explicitly. |
| File manager permission times out | Do not keep reopening it or change security settings; continue independent preparation and use the bounded alternative where permitted. |
| Two projects share the same basename | Treat binding as unresolved; do not rely on implicit project context until the exact intended packet/root is established. |
| Tool errors just after clicking Send | Keep UNKNOWN and recover the same conversation; never resend blindly. |
| The user presses Escape to stop computer control | Checkpoint and stop native actions; do not retry through another tool. Resume only after user direction. |
| Another adviser writes into the shared review directory | Read only this request's named outputs; preserve the other files and do not leak prior opinions into the first packet. |
| Completion JSON arrives while generation continues | Wait for visible stopped generation and no pending approval; do not accept the file alone. |
| Native report writes fail after submission | Collect the complete original from the same chat; do not ask for a reconstructed report or duplicate the request. |
| An automatic skill match occurs without a user consultation request | Do not transmit private evidence merely because the skill was loaded. |

## Fixes included

1. Replaced the fixed Windows-only route and historical plugin path with current-host native-tool discovery.
2. Replaced unbounded absolute-path exploration with a bounded native check and accurately labelled exact-packet corroboration.
3. Clarified that target model/effort names require live verification and are not guaranteed available.
4. Clarified that automatic skill discovery does not itself authorize an external transmission.
5. Canonicalized controller-created temporary test roots so the suite does not mistake macOS system temp aliases for untrusted delivery symlinks. Delivery symlink rejection remains unchanged.
6. Added schema 2 regressions covering each identity field, malformed/duplicate JSON, case aliases, reserved names, controller overlap, partial receipts, hardlinks, file and directory symlinks, boolean schema versions and UNKNOWN/approval states.

## Executed checks

Executed on Windows with Python 3.12.14: **63 tests passed, 0 skipped**. This includes actual hardlink, file-symlink and directory-symlink creation followed by expected collector refusal, as well as shared-directory isolation, malformed inputs, identity, stable bytes, receipt preservation, and synthetic credential-scanner checks.

Only local Python and static checks are run for this release. A full end-to-end native consultation on Windows, macOS or Linux is **not performed** here; Mac migration still requires observing the actual installed app, model/effort labels, native-tool permissions and file access on that Mac.

The outgoing Markdown/YAML files passed the bundled credential heuristic with zero findings. A targeted private-identifier/path scan found no matches. Manual inspection excluded local run records and account artifacts. Neither scan alone proves that arbitrary future packets are safe to publish.

The optional skill-creator validator initially required PyYAML not present in the runtime. Release validation supplies that dependency in an external temporary validation directory; it is not included as a runtime dependency or vendored into this package. The publisher records the final validator result separately.

## Final publisher validation

The bundled skill-creator `quick_validate.py` passed on the final package after its PyYAML dependency was supplied outside the package. Requirements are in the body for compatibility with older validators; the package retains valid Agent Skills frontmatter. Independent instruction-level interaction review found no blocking issue. This does not establish live native/browser behavior on macOS or a marketplace certification.

## v0.1.1 dispatch-state correction

The collector previously reported every non-SENT state as `NOT_SENT`. That made an unresolved submission indistinguishable from a confirmed unsent request and could mislead recovery into sending a duplicate. The correction keeps `NOT_SENT` unchanged, returns FAIL / `DISPATCH_UNKNOWN` with `dispatch_state: "UNKNOWN"` for unresolved submission, and rejects missing, non-string or unrecognized states as `INVALID_SESSION_SCHEMA`. Invalid arbitrary values are not echoed in CLI output. Neither the session nor adviser outputs are modified, and no receipt is created for those failures.

Regression coverage now exercises both legacy and shared-directory CLI paths, state preservation even when a complete report already exists, continued acceptance of SENT, invalid strings/types and missing state, and absence of unintended output reads or writes. The complete scripts suite passed on Windows / Python 3.12.14: **66 tests passed, 0 skipped**. Existing identity, sentinel, stable-byte, path/link, approval and receipt checks remain in force.

This patch was validated with synthetic local files only. No native app, model, sending action, Mac UI end-to-end consultation, commit, push or release was performed as part of these tests. `DISPATCH_UNKNOWN` requires recovery of the original conversation; it never authorizes resending or resetting the state to NOT_SENT.
