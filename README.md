# Opus 5.5 Ultracode Consult

Independent review through official Claude Code CLI, requesting Opus 5.5 with Ultracode while retaining the normal account/project harness. Each request has bounded evidence, one submission and its original response. Existing native Desktop Code consultations stay on their original route. This package does not install Claude, authenticate an account or supply computer-control tools.

Copy the whole directory into your configured skills location, usually `~/.codex/skills/opus-5-5-ultracode-consult`, and refresh skill discovery. Avoid duplicate installations. Invoke:

```text
Use $opus-5-5-ultracode-consult to review this project's proposed design.
```

Use [CLI workflow](references/cli-workflow.md) for new requests. A live CLI 2.1.286 probe completed packet reading and an Opus 5.5 response; effective effort/Ultracode fields were absent, so workflow activation remains unverified. Native Desktop Code previously delivered report/completion files with manual assistance; autonomous native controls remained unreliable. Neither observation proves broad end-to-end reliability or factual correctness.

Python helpers require 3.10+ and the standard library. `run_consult.py` launches the installed official CLI and sends the frozen prompt when invoked. Relevant web search and page reading are enabled by default through `--allowedTools WebSearch WebFetch` with `dontAsk`; explicit offline requests and existing policy restrictions remain binding. These grants preserve the normal tool inventory and do not eliminate every tool approval. The packet scanner, native state helper and file collector are offline. `dontAsk` is not a read-only sandbox. Consult per-run events for network validation; earlier file-reading probes did not test this change.

Instructions load progressively from [SKILL.md](SKILL.md). Reuse existing authorization, observations and request IDs. CLI run directories prevent duplicate launches; `SENT`/`UNKNOWN` requests retain their route and conversation. Native fallback is for explicitly chosen native work or a request proven unsent, with one UI owner and one bounded recovery before manual handoff. No CUA is required for normal CLI execution.

Run offline checks from this package directory:

```text
python3 -m unittest discover -s scripts -p "test_*.py" -v
```

These tests do not establish live authentication, target availability, UI reliability or factual accuracy. Keep packets/reports private unless publication is authorized. MIT licensed; see [LICENSE](LICENSE). [Publication check](PUBLICATION_CHECK.md) distinguishes the current revision from earlier release evidence.

For native Windows installation, profile creation and a first live test, follow [Windows CLI setup](references/windows-setup.md). Fixed runtime profiles are generated locally and must not be committed. On Windows use `py -3` in place of `python3` in the offline commands above.
