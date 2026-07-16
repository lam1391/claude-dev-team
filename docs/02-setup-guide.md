# 02 — Setup Guide: Steps in Order

Follow these steps in order to go from zero to a working multi-agent pipeline.

## Step 1 — Clone and create a virtual environment

```bash
git clone https://github.com/YOUR_USERNAME/claude-dev-team.git
cd claude-dev-team
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

## Step 2 — Install dependencies

```bash
pip install -r requirements.txt
```

This installs the `anthropic` SDK plus `fastapi`, `uvicorn`, `pytest`, and `httpx` (needed so the orchestrator can execute the generated app's tests locally).

## Step 3 — Dry run in mock mode (zero cost)

```bash
MOCK=1 python orchestrator.py
```

Mock mode runs the **entire orchestration** — validation, file writing, real pytest execution — using canned agent responses instead of API calls. Expected output ends with:

```
✅ PIPELINE COMPLETE
```

If this works, the plumbing is verified before you spend a single token.

## Step 4 — Configure your API key

Create a key at https://console.anthropic.com, then:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Rules:
- Never hardcode the key in source files.
- Never commit it — `.gitignore` already excludes `.env` in case you use one.
- For a persistent setup, add the export to your `~/.bashrc` / `~/.zshrc`.

## Step 5 — Run the real pipeline

```bash
python orchestrator.py "Build a REST API for a todo list with create, list, and delete endpoints"
```

Watch the console: each stage prints its validation result, retries (if any), and saved artifacts. The test round shows real pytest output.

Other tasks that work well at POC size:

```bash
python orchestrator.py "Build an API that converts CSV uploads to JSON"
python orchestrator.py "Build a URL shortener API with in-memory storage"
```

## Step 6 — Inspect the outputs

```
pipeline_output/
├── planner_output.json     # the plan
├── developer_output.json   # the code (as JSON)
├── tester_output.json      # tests + criteria coverage map
├── deployer_output.json    # deployment artifacts
├── test_run_1.log          # actual pytest output
└── app/                    # the ready-to-run application
    ├── main.py
    ├── test_main.py
    ├── Dockerfile
    └── requirements.txt
```

Review `planner_output.json` first — if a run went wrong, the root cause is usually an ambiguous plan.

## Step 7 — (Optional) Deploy the generated app

```bash
cd pipeline_output/app
docker build -t poc-app .
docker run -d -p 8000:8000 poc-app
curl http://localhost:8000/todos    # healthcheck
```

## Step 8 — Tune the pipeline

All knobs are constants at the top of `orchestrator.py`:

| Constant | Default | Meaning |
|---|---|---|
| `MODEL` | `claude-sonnet-4-6` | Model used by all agents |
| `MAX_TOKENS` | `8000` | Max output per agent call |
| `MAX_RETRIES` | `2` | Retries per stage on validation failure |
| `MAX_TEST_FIX_LOOPS` | `2` | Dev↔test feedback iterations |

To customize agent behavior, edit the system prompts in `agents.py`. To make handoffs stricter, extend the `validate_*` functions.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `anthropic.AuthenticationError` | `ANTHROPIC_API_KEY` not set in this shell, or invalid key |
| Stage fails after all retries | Task too ambiguous — make the task string more specific; read the stage's JSON artifact |
| Tests keep failing after fix loops | Check `test_run_*.log`; sometimes the *test* is wrong, not the code. This hard stop exists precisely so a human reviews it |
| `ModuleNotFoundError` during tests | Re-run Step 2 inside the active virtualenv |
