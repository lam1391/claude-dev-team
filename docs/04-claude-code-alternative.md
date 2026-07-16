# 04 — Alternative: Claude Code Subagents

The folder `claude-code-alternative/.claude/agents/` contains the same four-agent team defined as **Claude Code subagents**. In this variant, Claude Code itself plays the orchestrator role.

## How subagents work

Each `.md` file in `.claude/agents/` defines one subagent:

```markdown
---
name: tester
description: Testing Agent. Use AFTER developer. Writes and RUNS pytest tests...
tools: Read, Write, Bash, Glob, Grep
---

You are the Testing Agent. ...
```

- **`name` / `description`** — Claude Code uses the description to decide *when* to delegate to this subagent, so the descriptions encode the pipeline order ("Use FIRST", "Use AFTER developer", "Use LAST, only after tests pass").
- **`tools`** — least-privilege tool scoping. The planner can only read and write (no Bash); the tester can run Bash to execute pytest; the deployer cannot edit application code by convention.
- **Isolated context** — each subagent runs in its own context window, so the developer's long code output does not pollute the planner's context. The handoff medium is the **filesystem** (`plan.md`, source files, test results) instead of JSON messages.

## Using it

1. Copy the `.claude/` folder into any project directory:

   ```bash
   cp -r claude-code-alternative/.claude  /path/to/your/project/
   ```

2. Open Claude Code in that project:

   ```bash
   cd /path/to/your/project
   claude
   ```

3. Ask for the pipeline:

   > Use the planner, developer, tester and deployer agents in sequence to build
   > a REST API for a todo list. Do not deploy until all tests pass. If tests
   > fail, send the failures back to the developer agent.

4. Useful commands while it runs:
   - `/agents` — list and manage the subagents
   - Plan Mode (Shift+Tab) — review Claude Code's intended steps before it executes

## Comparison with the API orchestrator

| Aspect | Python orchestrator (this repo's core) | Claude Code subagents |
|---|---|---|
| Setup effort | Write/maintain Python | Drop in 4 markdown files |
| Validation & retries | Deterministic, in code | Prompt-driven, best-effort |
| Handoff medium | JSON contracts | Files in the working directory |
| Test execution | Orchestrator runs pytest itself | Tester subagent runs pytest via Bash |
| Auditability | JSON artifacts per stage | Conversation transcript + files |
| Best for | Learning the pattern; CI/automation | Interactive daily development |

Both are valid; they answer different needs. For unattended or repeatable runs (automation, CI), the code orchestrator wins. For interactive development sessions, the subagents version is more natural.

Docs: https://docs.claude.com/en/docs/claude-code/overview
