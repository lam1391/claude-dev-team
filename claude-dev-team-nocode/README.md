# Claude Dev Team — No-Code Edition

The same AI development team as the Python POC in the parent folder, rebuilt
with **zero code**: every agent, the orchestrator, the per-agent models, and
the output→input chaining are pure Claude Code configuration — seven markdown
files, nothing else.

```
claude-dev-team-nocode/
├── README.md
└── .claude/
    ├── commands/
    │   └── dev-team.md      # the orchestrator — /dev-team <task>
    └── agents/
        ├── planner.md       # opus   → writes plan.md
        ├── developer.md     # sonnet → writes source + requirements.txt
        ├── reviewer.md      # opus   → writes review.md
        ├── tester.md        # sonnet → runs pytest, writes TEST_REPORT.md
        └── deployer.md      # haiku  → writes Dockerfile + DEPLOY.md
```

## How to use

1. Copy the `.claude/` folder into any project (or start Claude Code inside
   this folder).
2. Run:

   ```
   /dev-team build a todo REST API with create, list, and delete endpoints
   ```

3. Watch the pipeline: planner → developer → reviewer → tester → deployer,
   with the orchestrator routing review issues and test failures back to the
   developer, and refusing to deploy until tests actually pass.

## How each requirement is met without code

**One model per agent.** Subagent frontmatter natively supports a `model:`
field — no hooks, no scripts:

| Agent | Model | Why |
|---|---|---|
| planner | `opus` | hardest reasoning in the pipeline |
| developer | `sonnet` | best coding capability per dollar |
| reviewer | `opus` | judgment-heavy, read-only |
| tester | `sonnet` | writes and executes pytest |
| deployer | `haiku` | most mechanical stage |

**Output of one agent = input of the next.** Subagents cannot call each
other, so the contract between them is **files on disk** — the no-code
equivalent of the JSON schemas in the Python version, and an audit trail
you can read after every run:

```
planner ──► plan.md ──► developer ──► source files ──► reviewer ──► review.md
                            ▲                                          │
                            └────────── issues / failures ◄────────────┤
                                                                       ▼
        DEPLOY.md + Dockerfile ◄── deployer ◄── TEST_REPORT.md ◄── tester
```

**Orchestration.** The `/dev-team` slash command turns the main Claude Code
session into the orchestrator: it delegates each stage to its subagent,
verifies the artifact exists before moving on, runs the review loop (max 1)
and the test-fix loop (max 3), gates the deployer on `ALL TESTS PASSED` in
`TEST_REPORT.md`, and stops loudly for human review when loops are exhausted
— the same supervision `orchestrator.py` does in Python, expressed as prose.

**Least privilege.** Each agent's `tools:` frontmatter grants only what its
job needs: the planner and reviewer cannot run Bash or edit code; only the
developer can Edit; only the tester and deployer run commands.

## Why not hooks?

Hooks were considered as the orchestration mechanism and rejected:

1. **Every hook executes a shell command.** Writing bash/jq in
   `settings.json` is code by another name — it breaks the no-code goal.
2. **Hooks can't orchestrate.** They fire at fixed events (before/after a
   tool call, on stop) and can only allow, block, or inject text. They cannot
   pass one agent's output to another or decide which agent runs next.

Hooks remain a good **optional hardening layer** if you later want
deterministic enforcement — e.g., a `PreToolUse` hook that blocks any
deployer invocation unless `TEST_REPORT.md` contains `ALL TESTS PASSED`.
That trades the no-code purity for a guarantee the model can't drift past.

## Honest limits vs. the Python version

- Supervision here is **prompt-driven**: the orchestrator follows written
  rules rather than executing validation functions. It is very reliable but
  not mechanically guaranteed — the hooks add-on above is the escape hatch.
- Loop limits (1 review loop, 3 test-fix loops) are counted by the
  orchestrator itself, not enforced externally.
- What is NOT weaker: test results. The tester runs pytest for real in a
  fresh venv and must report the actual output, and the deployer re-reads
  `TEST_REPORT.md` itself before agreeing to work.
