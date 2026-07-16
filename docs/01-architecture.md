# 01 — Analysis & Architecture

## The problem

Build an AI "development team" where four specialized agents collaborate on a software task:

1. **Analysis & Planning Agent** — turns a requirement into an executable plan
2. **Development Agent** — implements the plan as working code
3. **Testing Agent** — writes tests that verify the acceptance criteria
4. **Deployment Agent** — produces deployment artifacts (Dockerfile, steps)

Each agent's **output is the next agent's input** (sequential handoff), and an **orchestrator agent supervises** all of them.

## Approaches considered

| Approach | Pros | Cons | Verdict |
|---|---|---|---|
| **Claude Code subagents** | No code; fits Claude Code workflows; subagents get isolated contexts and scoped tools | Orchestration is prompt-driven, harder to enforce validate/retry deterministically | Included as alternative (`claude-code-alternative/`) |
| **Python + Claude API** | Full control; validation/retry is real code; easy to log, audit and debug; cheapest way to learn the pattern | You write the plumbing yourself | ✅ **Chosen for the POC** |
| **Claude Agent SDK** | Production-grade: built-in tools, sessions, subagent orchestration | More surface area than a POC needs | Recommended next step |

The deciding factor: the requirement *"validate each stage, retry on failure"* is deterministic control-flow logic. That belongs in code you own, not in prompts you hope are followed.

## Final architecture

```
                        ORCHESTRATOR (orchestrator.py)
                        validates · retries · routes · audits
        ┌──────────────┬──────────────┬──────────────┐
        ▼              ▼              ▼              ▼
 ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
 │ 1. Analysis │ │ 2. Develop- │ │ 3. Testing  │ │ 4. Deploy-  │
 │  & Planning │─►│    ment     │─►│             │─►│    ment     │
 └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘
   plan (JSON)     code files      pytest files    Dockerfile +
                       ▲                │           deploy steps
                       └── fix loop ────┘
                        (orchestrator runs pytest;
                         failures go back to dev)
```

## Key design decisions

**One agent = one API call with a specialized system prompt.** There is no magic: an "agent" here is a role description (system prompt) plus an input. Specialization comes from the prompt; coordination comes from the orchestrator.

**JSON contracts between agents.** Every agent must output a single JSON object matching a declared schema. This makes handoffs machine-checkable — the same reason data pipelines enforce schemas between stages. Free-text handoffs cannot be validated.

**The orchestrator never trusts, it verifies.** It parses and validates every output. Most importantly, it executes the generated tests with `pytest` itself. An LLM claiming "tests pass" is not evidence; a real exit code 0 is.

**Failures produce feedback, not silence.** A rejected output is retried with the exact validation error appended. A failed test run is sent back to the Development Agent with the failure log. After bounded retries, the pipeline stops loudly (`RuntimeError`) for human review — a hard stop is a feature, not a bug.

**Audit trail on disk.** Every stage output and every test run is saved under `pipeline_output/`, so any run can be reviewed after the fact.

## Component map

| File | Role |
|---|---|
| `orchestrator.py` | Supervisor: stage sequencing, validation, retries, test execution, dev↔test loop, artifacts |
| `agents.py` | The four agents: system prompts, JSON schemas, validator functions |
| `claude-code-alternative/.claude/agents/*.md` | Same team as Claude Code subagents |
| `docs/` | This documentation |
