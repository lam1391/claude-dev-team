# Claude Dev Team — Multi-Agent Pipeline POC

A proof of concept for an AI development team built with the Claude API. Five specialized agents work in sequence — each one's output becomes the next one's input — while an **orchestrator** supervises the whole pipeline: it validates every output, retries failed stages, executes the generated tests for real, and routes both review issues and test failures back to the Development Agent for fixes.

## Documentation

| Document | Contents |
|---|---|
| [docs/01-architecture.md](docs/01-architecture.md) | Analysis, approaches considered, architecture, design decisions |
| [docs/02-setup-guide.md](docs/02-setup-guide.md) | Step-by-step setup and usage (steps 1–8) + troubleshooting |
| [docs/03-how-it-works.md](docs/03-how-it-works.md) | Orchestration internals: validation, retries, the dev↔test loop |
| [docs/04-claude-code-alternative.md](docs/04-claude-code-alternative.md) | The same team as Claude Code subagents |
| [docs/05-next-steps.md](docs/05-next-steps.md) | Roadmap: Agent SDK, parallelism, data-engineering variant |

## Architecture

```
                    ORCHESTRATOR (orchestrator.py)
               validates · retries · routes · audits

  ┌────────────┬────────────┬────────────┬────────────┬────────────┐
  ▼            ▼            ▼            ▼            ▼

┌────────────┐┌────────────┐┌────────────┐┌────────────┐┌────────────┐
│ 1. Plan    ││2. Develop  ││3. Review   ││4. Test     ││5. Deploy   │
│ & Analyze  ││            ││            ││            ││            │
└────────────┘└────────────┘└────────────┘└────────────┘└────────────┘
 plan (JSON)  code files    approve/    pytest files  Dockerfile +
                  ▲  ▲      issues          │        deploy steps
                  │  └───── review loop ──┘
                  └─────── test fix loop ───┘

     (orchestrator runs pip install + pytest for real;
      review issues and test failures go back to dev)
```

The key insight: each "agent" is simply **one API call with a specialized system prompt and a strict JSON output contract**. The intelligence of the pipeline lives in the orchestrator, which is plain Python you fully control — exactly like a DAG where each node happens to be an LLM call.

## How the supervision works

| Mechanism | Where | What it does |
|---|---|---|
| Schema validation | `agents.py` → `validate_*` functions | Checks every agent's JSON against its contract |
| Retry with feedback | `orchestrator.py` → `run_stage()` | On invalid output, re-prompts the agent with the exact error (up to `MAX_RETRIES`) |
| Dependency install | `orchestrator.py` → `setup_venv()` / `install_deps()` | Installs the generated requirements.txt into an isolated venv (`pipeline_output/app/.venv`) before tests; pip errors go back to the Development Agent |
| Dev↔Review feedback loop | `orchestrator.py` → `run_review()` | Review issues are sent back to the Development Agent (up to `MAX_REVIEW_LOOPS`); if still rejected, proceeds with a loud warning — reviewers advise, tests decide |
| Real test execution | `orchestrator.py` → `run_tests()` | Runs `pytest` on the generated code — no trusting the LLM's word |
| Dev↔Test feedback loop | `orchestrator.py` → `main()` | Test failures are sent back to the Development Agent with the failure log (up to `MAX_TEST_FIX_LOOPS`) |
| Audit trail | `pipeline_output/*.json`, `test_run_*.log` | Every stage output and test run is saved to disk |
| Hard stop | `RuntimeError` | If retries are exhausted, the pipeline stops loudly for human review |

## Setup — step by step

**Step 1 — Get the code and install dependencies**

```bash
cd claude-dev-team
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**Step 2 — Verify the plumbing without spending tokens (mock mode)**

```bash
MOCK=1 python orchestrator.py
```

This runs the entire pipeline with canned agent responses. You should see all five stages pass, tests actually execute, and files appear in `pipeline_output/app/`. This proves the orchestration logic before any API cost.

**Step 3 — Set your API key**

Get a key at https://console.anthropic.com, then:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Never hardcode the key or commit it to Git.

**Step 4 — Run the real pipeline**

```bash
python orchestrator.py "Build a REST API for a todo list with create, list, and delete endpoints"
```

Try your own tasks — anything small and API-shaped works well:

```bash
python orchestrator.py "Build an API that converts CSV uploads to JSON"
python orchestrator.py "Build a URL shortener API with in-memory storage"
```

**Step 5 — Inspect the results**

```
pipeline_output/
├── planner_output.json     # the plan (audit what was decided)
├── developer_output.json   # the code, as JSON
├── reviewer_output.json    # review verdict + issues
├── tester_output.json      # tests + criteria coverage map
├── deployer_output.json    # deployment artifacts
├── test_run_1.log          # actual pytest output
└── app/                    # ready-to-run application
    ├── main.py
    ├── test_main.py
    ├── Dockerfile
    └── requirements.txt
```

**Step 6 — (Optional) Deploy the result**

```bash
cd pipeline_output/app
docker build -t poc-app . && docker run -d -p 8000:8000 poc-app
curl http://localhost:8000/todos
```

## Design decisions worth understanding

**Why JSON contracts between agents?** Free-text handoffs are impossible to validate. A JSON schema per agent gives the orchestrator something concrete to check, and validation failures produce precise feedback for retries. (Same reason you enforce schemas between pipeline stages in Snowflake.)

**Why does the orchestrator run the tests itself?** An LLM claiming "tests pass" is not evidence. Executing pytest gives ground truth, and the failure log is the highest-quality feedback you can give the Development Agent.

**Why `claude-sonnet-4-6`?** Strong coding capability at a good price for a POC. You can mix models per stage — e.g., `claude-opus-4-8` for the planner (hardest reasoning) and `claude-haiku-4-5` for the deployer (most mechanical). Change `MODEL` in `orchestrator.py`, or make it per-stage in `agents.py`.

**Cost note:** one full run makes 4–8 API calls (more if retries trigger). With Sonnet, expect cents per run for tasks this size.

## Alternative: the same team as Claude Code subagents

The folder `claude-code-alternative/` contains the same five agents defined as Claude Code subagents (`.claude/agents/*.md`). Copy that `.claude/` folder into any project, open Claude Code, and say:

> Use the planner, developer, reviewer, tester and deployer agents in sequence to build a todo REST API. Fix any review issues and make sure tests pass before deploying.

Claude Code itself acts as the orchestrator: it delegates to each subagent, and each subagent runs in its own context window with only the tools listed in its frontmatter (note the tester can run Bash but the planner can't — least privilege). This is faster to set up but the supervision logic is prompt-driven rather than code-driven.

Docs: https://docs.claude.com/en/docs/claude-code/overview

## Where to take this next

1. **Claude Agent SDK** — when the POC outgrows a script, the Agent SDK gives you programmatic agents with built-in tools (file access, bash), session management, and subagent orchestration in Python/TypeScript. Your `agents.py` prompts port over directly. See https://platform.claude.com/docs
2. **Parallelism** — planning could fan out (e.g., a security-review agent and an architecture agent run in parallel, orchestrator merges). The sequential loop in `main()` becomes an `asyncio.gather`.
3. **Human-in-the-loop gates** — add an `input("Approve plan? [y/n] ")` after the planning stage before spending tokens on development.
4. **Structured outputs** — the API supports enforced structured outputs on recent models, which can replace the "respond only with JSON" prompting + manual parsing.
5. **Your domain** — swap the demo task: a planner that reads a dbt/Snowflake model spec, a developer that writes SQL transformations, a tester that runs data-quality checks, a deployer that promotes from INT to PROD. The orchestration skeleton is identical.

## Troubleshooting

- `anthropic.AuthenticationError` → `ANTHROPIC_API_KEY` not set or invalid.
- Stage fails after all retries → read `pipeline_output/<stage>_output.json` and the printed error; usually the task was too ambiguous. Make the task string more specific.
- Tests keep failing after fix loops → check `test_run_*.log`; sometimes the Testing Agent wrote a wrong test rather than the code being wrong. This is exactly the case that needs a human — the hard stop is a feature.
- Generated app won't import in tests → ensure `pytest` runs from `pipeline_output/app/` (the orchestrator already does this via `cwd=APP_DIR`).
