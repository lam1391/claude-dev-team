# 03 — How the Orchestration Works

This document walks through the supervision mechanics in `orchestrator.py`.

## The pipeline loop

`main()` executes the stages in order and wires each output to the next input:

1. **Planner** ← raw user task string
2. **Developer** ← the plan as JSON
3. **Tester** ← acceptance criteria + the developer's files
4. *(orchestrator runs pytest — see feedback loop below)*
5. **Deployer** ← the verified files + run instructions

The handoff is literal: `run_stage()` returns a dict, and that dict is serialized into the next agent's user message.

## Stage supervision: `run_stage()`

Every stage goes through the same supervised cycle:

```
call agent → parse JSON → validate against schema
   │              │              │
   │       JSONDecodeError   validation error
   │              │              │
   │              └──────┬───────┘
   │                     ▼
   │       retry: same input + "YOUR PREVIOUS OUTPUT WAS
   │       REJECTED. Reason: <exact error>. Fix it."
   │                     │
   └── valid ──► save artifact, return data
```

- Parsing tolerates stray markdown fences (`parse_json_response`).
- Validators live next to the agent definitions in `agents.py` and return `(ok, error_message)` — the error message becomes the retry feedback, so retries are targeted, not blind.
- After `MAX_RETRIES` failures the stage raises `RuntimeError` and the pipeline stops. Exhausted retries mean the task or the prompt needs human attention; silently continuing would ship garbage downstream.

## The dev ↔ test feedback loop

This is the most important supervision feature. After the Testing Agent delivers its test files, the orchestrator:

1. Writes app files + test files to `pipeline_output/app/`
2. Executes `pytest` there as a subprocess (`run_tests()`)
3. On green: proceeds to deployment
4. On red: builds a fix request containing the original plan, the current code, and **the last 3000 characters of the real pytest output**, and sends it back to the **Development Agent**
5. Repeats up to `MAX_TEST_FIX_LOOPS` times, then hard-stops

Why the orchestrator runs the tests instead of asking the Testing Agent whether they pass: an LLM's claim is not evidence. A subprocess exit code is. This "ground truth injection" is what turns a chain of prompts into a supervised system.

## Trust boundaries

The orchestrator treats agent outputs as **untrusted data**:

- Outputs are parsed and schema-validated, never `eval`'d
- Generated code is only executed in the explicit, sandbox-able test step — run this POC inside a container or VM if you point it at tasks you don't fully control
- The API key is read from the environment, never from files in the repo

## Cost and model notes

- A clean run makes ~4–6 API calls; retries and fix loops add more. Bound the worst case: `stages × (1 + MAX_RETRIES) + MAX_TEST_FIX_LOOPS` calls.
- `MODEL` applies to all agents. A natural optimization is per-stage models: a stronger model for planning (hardest reasoning), a cheaper one for deployment (most mechanical). Add a `model` key per stage in `agents.py` and read it in `call_agent()`.
- Newer models handle "respond only with JSON" well, but the retry loop exists precisely for the times they don't. The API's structured outputs feature can enforce schemas at the API level — see `docs/05-next-steps.md`.

## Extending the pattern

- **New stage** (e.g., a Security Review Agent between developer and tester): add an entry to `PIPELINE` in `agents.py` with a prompt + validator, then wire its input in `main()`.
- **Parallel stages**: replace sequential calls with `asyncio.gather` using `anthropic.AsyncAnthropic`; the orchestrator merges results before the next handoff.
- **Human approval gates**: insert `input("Approve plan? [y/N] ")` after the planning stage — cheap insurance before development tokens are spent.
