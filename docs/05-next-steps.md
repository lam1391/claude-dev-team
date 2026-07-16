# 05 — Next Steps & Roadmap

Ideas for evolving this POC, roughly in order of effort.

## 1. Human-in-the-loop gates (small)

Add an approval prompt after planning, before any development tokens are spent:

```python
plan = run_stage(planner, task)
print(json.dumps(plan, indent=2))
if input("Approve plan? [y/N] ").lower() != "y":
    sys.exit("Plan rejected — refine the task and rerun.")
```

## 2. Per-stage models (small)

Use a stronger model where reasoning is hardest and a cheaper one where the work is mechanical. Add a `"model"` key to each stage in `agents.py` and read it in `call_agent()` — e.g., `claude-opus-4-8` for the planner, `claude-sonnet-4-6` for development/testing, `claude-haiku-4-5` for deployment.

## 3. Structured outputs (small–medium)

The prompts currently *ask* for JSON and the orchestrator validates after the fact. Recent models support API-enforced structured outputs, which guarantee schema-conformant responses and can replace part of the retry machinery. See the structured outputs section of the API docs: https://platform.claude.com/docs

## 4. A security-review stage (medium)

Insert a fifth agent between development and testing that reviews the generated code for obvious issues (injection, unsafe deserialization, secrets in code) and either approves or returns findings to the developer. This exercises the pattern of a **gate that can reject backwards**, which the test loop already demonstrates.

## 5. Parallel fan-out (medium)

Not everything is sequential. Planning could fan out to parallel specialists (API design + data model + security requirements) whose outputs the orchestrator merges into one plan. Implementation: `anthropic.AsyncAnthropic` + `asyncio.gather`.

## 6. Migrate to the Claude Agent SDK (larger)

When the POC outgrows a script, the Agent SDK provides programmatic agents with built-in tools (file access, bash), session management, and subagent orchestration in Python/TypeScript. The system prompts in `agents.py` port over directly; what you replace is the hand-written plumbing. Start here: https://platform.claude.com/docs

## 7. Adapt it to data engineering (the interesting one)

The orchestration skeleton is domain-agnostic. A data-pipeline variant:

| Agent | Software POC | Data engineering variant |
|---|---|---|
| Planner | Feature plan | Reads a model/spec, plans SQL transformations and DAG changes |
| Developer | FastAPI code | Writes Snowflake SQL / dbt models |
| Tester | pytest | Runs data-quality checks (row counts, null rates, schema drift) against a dev database |
| Deployer | Dockerfile | Generates the promotion artifacts / migration scripts for INT → PROD |

The validators change (SQL linting, dry-run `EXPLAIN`, data-quality thresholds instead of pytest exit codes), but `run_stage()`, the retry loop, and the feedback loop stay identical.

## Operational hardening checklist (before anything production-like)

- [ ] Run generated code only in a sandbox/container
- [ ] Add timeouts and cost caps (track `usage` from API responses; abort past a budget)
- [ ] Log every request/response pair for audit
- [ ] Pin the model version and re-test prompts when upgrading models
- [ ] Keep the hard-stop behavior — never auto-deploy on ambiguous results
