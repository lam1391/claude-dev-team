# Design: No-Code Dev Team (pure Claude Code configuration)

**Date:** 2026-07-15
**Status:** Approved
**Goal:** Recreate the multi-agent dev team pipeline with zero code — only Claude Code agent/command configuration. Each agent runs on a different model, and each agent's output artifact is the next agent's input.

## Decision: orchestration mechanism

Three mechanisms were analyzed:

1. **Slash command orchestrator (chosen).** A `/dev-team <task>` command in `.claude/commands/dev-team.md`. Pure markdown, explicitly invoked, encodes the full sequence, the loops, and the "no deploy until tests pass" gate. The main Claude Code session acts as the orchestrator only when invoked.
2. **CLAUDE.md instructions.** Always-on orchestration rules. Rejected: loads into every session with no per-request opt-out, and is easier to ignore than an explicit command.
3. **Hooks.** Rejected as the orchestration mechanism for two reasons: (a) every hook executes a shell command — that is code, violating the constraint; (b) hooks cannot route data between agents or choose the next agent — they only allow/block/inject at fixed events. They remain a valid *optional hardening* layer (e.g., a `PreToolUse` gate that blocks the deployer when `TEST_REPORT.md` shows failures) for anyone willing to accept shell one-liners in `settings.json`.

Per-agent models require no mechanism at all: subagent frontmatter supports `model: opus | sonnet | haiku | inherit`.

## Folder structure

```
claude-dev-team-nocode/
├── README.md                     # what it is, install, usage, why not hooks
└── .claude/
    ├── commands/
    │   └── dev-team.md           # the orchestrator — /dev-team <task>
    └── agents/
        ├── planner.md
        ├── developer.md
        ├── reviewer.md
        ├── tester.md
        └── deployer.md
```

100% markdown. No settings.json, no hooks, no scripts.

## Agents

The file column is the output→input chain — the no-code equivalent of the JSON contracts in `agents.py`. Each agent's markdown body states its job, its input file(s), its output file(s), and what it must NOT do.

| Agent | Model | Rationale | Tools (least privilege) | Writes → next agent reads |
|---|---|---|---|---|
| planner | `opus` | hardest reasoning | Read, Glob, Grep, Write | `plan.md` |
| developer | `sonnet` | best coding value | Read, Write, Edit, Glob, Grep, Bash | source files + `requirements.txt` |
| reviewer | `opus` | judgment-heavy | Read, Glob, Grep, Write | `review.md` |
| tester | `sonnet` | writes + runs pytest | Read, Write, Bash, Glob, Grep | `TEST_REPORT.md` |
| deployer | `haiku` | most mechanical | Read, Write, Bash, Glob | `Dockerfile`, `DEPLOY.md` |

Carried over from the approved deps-install spec: the developer must produce a `requirements.txt` covering every import; the tester creates a fresh `.venv`, installs `requirements.txt` plus pytest into it, and runs tests with the venv's Python — so missing dependencies never masquerade as code bugs.

## Orchestrator (`/dev-team <task>`)

The command instructs the main session to run the five agents in sequence via the Task tool, enforcing the same supervision as `orchestrator.py`:

- **Artifact validation:** before proceeding past any stage, verify the expected artifact exists and is non-empty; if not, re-invoke the agent once with the specific gap (prompt-driven version of the `validate_*` functions).
- **Review loop:** if `review.md` says CHANGES REQUESTED, send the issues back to the developer, then re-review. Max 1 loop; if still rejected, warn loudly and proceed — reviewers advise, tests decide.
- **Test-fix loop:** if `TEST_REPORT.md` shows failures, send the failure output back to the developer, then re-test. Max 3 loops.
- **Deploy gate:** the deployer runs only when `TEST_REPORT.md` shows all tests passing.
- **Hard stop:** when loops are exhausted, stop loudly and summarize the open problems for human review.
- **Audit trail:** all artifacts (`plan.md`, `review.md`, `TEST_REPORT.md`, `DEPLOY.md`) stay on disk — the no-code `pipeline_output/`.

## Testing

Copy `claude-dev-team-nocode/.claude/` into a scratch project, run `/dev-team build a todo REST API with create, list, and delete endpoints`, and verify: all five agents run in order on their configured models, artifacts appear, tests actually execute, and the deployer only runs after a passing report.

## Known limits (documented in README)

- Supervision is prompt-driven, not code-enforced — the orchestrator can drift. The hooks add-on (rejected above as default) is the escape hatch if determinism becomes mandatory.
- Loop limits are honor-system: the orchestrator counts, nothing external enforces it.
