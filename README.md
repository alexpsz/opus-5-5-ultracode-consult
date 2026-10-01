# Opus 5.5 Ultracode Consult

A portable Agent Skill for an independent review in Claude desktop Code. It verifies the requested model and effort, shares bounded project evidence, sends once, and collects the original report into the same project.

The model and effort names are requested UI targets, not a claim of universal availability or affiliation with Anthropic. This project contains instructions and offline Python helpers; it does not bundle Claude, computer-control tools, account data or credentials.

## Install

Download or clone this repository so the directory is named `opus-5-5-ultracode-consult`. Copy the **whole directory**, including references and scripts, into your agent's configured skills directory. For Codex, use its configured `$CODEX_HOME/skills` directory, or `~/.codex/skills` when unset. Hosts using the shared Agent Skills location may instead use `~/.agents/skills`; follow that host's current documentation. Avoid installing duplicate copies in several locations.

On macOS/Linux, `~` is your home directory; on Windows, use your actual home and configured Codex location. The package contains no fixed user path. Refresh skill discovery or restart the host if it requires that. Invoke:

```text
Use $opus-5-5-ultracode-consult to review the current project's proposed design.
```

The agent will need the exact target in the account's picker, a signed-in native Claude Code workspace and a supported native computer-control tool. It reads the current host's tool documentation rather than assuming the Windows interface exists on a Mac.

## Portability and limitations

| Component | Windows | macOS | Linux |
| --- | --- | --- | --- |
| Skill and references | Portable text | Portable text | Portable text |
| Python helpers | Tested on this release host | Designed for Python 3.10+; not executed here | Designed for Python 3.10+; not executed here |
| Native desktop consultation | Workflow supported when tools and exact target exist; no release-specific end-to-end run | Requires Mac native tools; **not end-to-end verified** | No native app/control availability claim |

Python scripts use only the standard library and have no network calls. Resolve current-host paths before dispatch. Keep reports and packets private unless their owner explicitly authorizes publication. Installing this skill does not publish or upload them.

## Tests

From the repository root:

```text
python3 -m unittest discover -s scripts -p "test_*.py" -v
```

Use `python` or an available full Python executable path on Windows. Tests use only synthetic evidence and credential-shaped fixtures. They do not contact models or verify native UI behavior. See [publication check](PUBLICATION_CHECK.md) for the recorded scope and remaining limitations.

## Contents

- [SKILL.md](SKILL.md): entry point and narrow workflow.
- [Native workflow](references/native-workflow.md): host routing, model verification and bounded UI recovery.
- [Packet template](references/context-packet-template.md): neutral common evidence and short dispatch.
- [Delivery protocol](references/delivery-protocol.md): shared-directory report collection and integrity receipt.
- `scripts/check_packet_safety.py`: offline credential heuristic, not a privacy guarantee.
- `scripts/collect_delivery.py`: exact-output, create-only receipt validation.

The package follows the directory/frontmatter conventions of the [Agent Skills specification](https://agentskills.io/specification). Compliance with a file format is not certification by a marketplace. MIT licensed; see [LICENSE](LICENSE).
