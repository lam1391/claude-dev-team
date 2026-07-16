"""
Orchestrator (Supervisor) Agent for the Claude Dev Team POC.

Responsibilities:
  1. Run the pipeline stages in order: planner -> developer -> tester -> deployer
  2. Pass each agent's output as the next agent's input (sequential handoff)
  3. VALIDATE every agent's output against its schema
  4. RETRY a stage (with the error fed back) when validation fails
  5. Actually EXECUTE the tests written by the Testing Agent — if they fail,
     send the failure log back to the Development Agent (feedback loop)
  6. Save every artifact to ./pipeline_output/ for auditing

Usage:
  export ANTHROPIC_API_KEY=sk-ant-...
  python orchestrator.py "Build a REST API for a todo list"

  # Dry run without an API key (canned responses, verifies the plumbing):
  MOCK=1 python orchestrator.py
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from agents import PIPELINE, parse_json_response

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MODEL = "claude-sonnet-4-6"     # good balance of capability and cost
MAX_TOKENS = 8000
MAX_RETRIES = 2                  # per stage, on validation failure
MAX_TEST_FIX_LOOPS = 2           # dev<->test feedback iterations
OUTPUT_DIR = Path("pipeline_output")
APP_DIR = OUTPUT_DIR / "app"     # where generated code + tests are written
VENV_DIR = APP_DIR / ".venv"    # isolated env for the GENERATED app's deps
VENV_PYTHON = VENV_DIR / "bin" / "python"
PIP_TIMEOUT = 300                # seconds for dependency installation
MOCK = os.environ.get("MOCK") == "1"

DEFAULT_TASK = "Build a minimal REST API for a todo list with endpoints to create, list, and delete todos."


# ---------------------------------------------------------------------------
# LLM call (one function = one agent invocation)
# ---------------------------------------------------------------------------
def call_agent(system_prompt: str, user_input: str) -> str:
    if MOCK:
        return mock_response(system_prompt)

    import anthropic  # imported here so MOCK mode needs no dependency
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_input}],
    )
    # concatenate all text blocks (thinking summaries are not text blocks)
    return "".join(b.text for b in message.content if b.type == "text")


# ---------------------------------------------------------------------------
# Orchestrator core: run one stage with validation + retry
# ---------------------------------------------------------------------------
def run_stage(stage: dict, user_input: str) -> dict:
    """Run one agent. Retry with error feedback if its output is invalid."""
    print(f"\n{'=' * 60}\n▶ {stage['title']}\n{'=' * 60}")

    feedback = ""
    for attempt in range(1, MAX_RETRIES + 2):  # first try + retries
        prompt = user_input if not feedback else (
            f"{user_input}\n\n"
            f"YOUR PREVIOUS OUTPUT WAS REJECTED. Reason: {feedback}\n"
            f"Fix the problem and output valid JSON again."
        )
        raw = call_agent(stage["system_prompt"], prompt)

        try:
            data = parse_json_response(raw)
        except json.JSONDecodeError as e:
            feedback = f"Invalid JSON: {e}"
            print(f"  ✗ Attempt {attempt}: {feedback}")
            continue

        ok, error = stage["validate"](data)
        if ok:
            print(f"  ✓ Attempt {attempt}: output valid")
            save_artifact(stage["name"], data)
            return data

        feedback = error
        print(f"  ✗ Attempt {attempt}: validation failed — {error}")

    raise RuntimeError(
        f"Stage '{stage['name']}' failed after {MAX_RETRIES + 1} attempts. "
        f"Last error: {feedback}"
    )


# ---------------------------------------------------------------------------
# Helpers: artifacts, writing files, running tests
# ---------------------------------------------------------------------------
def save_artifact(name: str, data: dict) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / f"{name}_output.json"
    path.write_text(json.dumps(data, indent=2))
    print(f"  ↳ artifact saved: {path}")


def write_files(files: list[dict], base: Path) -> None:
    base.mkdir(parents=True, exist_ok=True)
    for f in files:
        target = base / f["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f["content"])
        print(f"  ↳ wrote {target}")


def setup_venv() -> None:
    """Create a fresh venv for the generated app (once per run)."""
    if VENV_DIR.exists():
        shutil.rmtree(VENV_DIR)
    subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
    print(f"  ↳ created venv: {VENV_DIR}")


def install_deps() -> tuple[bool, str]:
    """Install the generated requirements.txt + pytest into the app venv."""
    # Use absolute path to venv python (not .resolve() which follows symlinks)
    venv_python = str(VENV_DIR.resolve() / "bin" / "python")
    result = subprocess.run(
        [venv_python, "-m", "pip", "install", "-q",
         "-r", str(APP_DIR / "requirements.txt"), "pytest"],
        capture_output=True, text=True, timeout=PIP_TIMEOUT,
    )
    output = result.stdout + result.stderr
    return result.returncode == 0, output


def install_with_dev_fix(code: dict, dev_input: str, developer: dict) -> dict:
    """Install deps; on failure, send the pip error back to the developer once."""
    ok, output = install_deps()
    if ok:
        print("  ↳ dependencies installed")
        return code
    print(f"  ✗ dependency install failed:\n{output[-1500:]}")
    fix_input = (
        f"{dev_input}\n\nYOUR PREVIOUS CODE:\n{json.dumps(code['files'], indent=2)}"
        f"\n\nDEPENDENCY INSTALL FAILED — fix requirements.txt:\n{output[-3000:]}"
    )
    code = run_stage(developer, fix_input)
    write_files(code["files"], APP_DIR)
    ok, output = install_deps()
    if not ok:
        raise RuntimeError(f"Dependency install still failing:\n{output[-2000:]}")
    print("  ↳ dependencies installed")
    return code


def run_tests() -> tuple[bool, str]:
    """Execute pytest against the generated app. Returns (passed, output)."""
    # Use absolute path to venv python (not .resolve() which follows symlinks)
    venv_python = str(VENV_DIR.resolve() / "bin" / "python")
    result = subprocess.run(
        [venv_python, "-m", "pytest", "-x", "-q", "--no-header"],
        cwd=APP_DIR, capture_output=True, text=True, timeout=120,
    )
    output = result.stdout + result.stderr
    return result.returncode == 0, output


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------
def main() -> None:
    task = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TASK
    planner, developer, tester, deployer = PIPELINE
    print(f"🎯 Task: {task}")
    if MOCK:
        print("⚠ MOCK mode: using canned responses, no API calls")

    # Stage 1: Planning — input is the raw user task
    plan = run_stage(planner, task)

    # Stage 2 & 3: Development + Testing with a supervised feedback loop
    dev_input = f"PLAN:\n{json.dumps(plan, indent=2)}"
    code = run_stage(developer, dev_input)
    write_files(code["files"], APP_DIR)
    setup_venv()
    code = install_with_dev_fix(code, dev_input, developer)

    tester_input = (
        f"ACCEPTANCE CRITERIA:\n{json.dumps(plan['acceptance_criteria'], indent=2)}\n\n"
        f"APPLICATION FILES:\n{json.dumps(code['files'], indent=2)}"
    )
    tests = run_stage(tester, tester_input)
    write_files(tests["test_files"], APP_DIR)

    # Orchestrator supervises: actually run the tests, loop back on failure
    for loop in range(1, MAX_TEST_FIX_LOOPS + 2):
        print(f"\n🧪 Running tests (round {loop})...")
        passed, output = run_tests()
        (OUTPUT_DIR / f"test_run_{loop}.log").write_text(output)
        if passed:
            print("  ✓ All tests passed")
            break
        print(f"  ✗ Tests failed:\n{output[-1500:]}")
        if loop > MAX_TEST_FIX_LOOPS:
            raise RuntimeError("Tests still failing after max fix loops — human review needed.")
        # Feedback loop: send the failure back to the Development Agent
        fix_input = (
            f"{dev_input}\n\nYOUR PREVIOUS CODE:\n{json.dumps(code['files'], indent=2)}"
            f"\n\nTEST FAILURES TO FIX:\n{output[-3000:]}"
        )
        code = run_stage(developer, fix_input)
        write_files(code["files"], APP_DIR)
        code = install_with_dev_fix(code, dev_input, developer)

    # Stage 4: Deployment — input is the verified code
    deploy_input = (
        f"VERIFIED APPLICATION FILES:\n{json.dumps(code['files'], indent=2)}\n\n"
        f"HOW TO RUN: {code.get('how_to_run', 'unknown')}"
    )
    deployment = run_stage(deployer, deploy_input)
    write_files(deployment["files"], APP_DIR)

    # Final report
    print(f"\n{'=' * 60}\n✅ PIPELINE COMPLETE\n{'=' * 60}")
    print(f"App code + tests + deployment files: {APP_DIR}/")
    print(f"Stage artifacts and test logs:       {OUTPUT_DIR}/")
    print("Deploy steps:")
    for step in deployment["deploy_steps"]:
        print(f"  $ {step}")


# ---------------------------------------------------------------------------
# MOCK mode: canned responses so the plumbing can be tested with no API key
# ---------------------------------------------------------------------------
def mock_response(system_prompt: str) -> str:
    if system_prompt.startswith("You are the Analysis & Planning Agent"):
        return json.dumps({
            "summary": "A minimal in-memory todo REST API using FastAPI.",
            "tech_stack": ["python", "fastapi"],
            "files_to_create": [{"path": "main.py", "purpose": "FastAPI app"}],
            "acceptance_criteria": [
                "POST /todos creates a todo and returns it with an id",
                "GET /todos returns all todos",
                "DELETE /todos/{id} removes a todo",
            ],
            "out_of_scope": ["persistence", "auth"],
        })
    if system_prompt.startswith("You are the Development Agent"):
        return json.dumps({
            "files": [{"path": "main.py", "content": (
                "from fastapi import FastAPI, HTTPException\n"
                "from pydantic import BaseModel\n\n"
                "app = FastAPI()\n"
                "todos: dict[int, dict] = {}\n"
                "counter = {\"next\": 1}\n\n"
                "class TodoIn(BaseModel):\n    title: str\n\n"
                "@app.post('/todos')\n"
                "def create(todo: TodoIn):\n"
                "    tid = counter['next']; counter['next'] += 1\n"
                "    todos[tid] = {'id': tid, 'title': todo.title}\n"
                "    return todos[tid]\n\n"
                "@app.get('/todos')\n"
                "def list_all():\n    return list(todos.values())\n\n"
                "@app.delete('/todos/{tid}')\n"
                "def delete(tid: int):\n"
                "    if tid not in todos:\n"
                "        raise HTTPException(404)\n"
                "    return todos.pop(tid)\n"
            )},
            {"path": "requirements.txt",
             "content": "fastapi>=0.115\nuvicorn>=0.30\nhttpx>=0.27\n"}],
            "how_to_run": "uvicorn main:app",
            "notes": "in-memory storage",
        })
    if system_prompt.startswith("You are the Testing Agent"):
        return json.dumps({
            "test_files": [{"path": "test_main.py", "content": (
                "from fastapi.testclient import TestClient\n"
                "from main import app, todos\n\n"
                "client = TestClient(app)\n\n"
                "def test_create():\n"
                "    r = client.post('/todos', json={'title': 'a'})\n"
                "    assert r.status_code == 200 and r.json()['id']\n\n"
                "def test_list():\n"
                "    client.post('/todos', json={'title': 'b'})\n"
                "    assert len(client.get('/todos').json()) >= 1\n\n"
                "def test_delete():\n"
                "    tid = client.post('/todos', json={'title': 'c'}).json()['id']\n"
                "    assert client.delete(f'/todos/{tid}').status_code == 200\n"
            )}],
            "criteria_coverage": [
                {"criterion": "POST creates", "test_name": "test_create"},
                {"criterion": "GET lists", "test_name": "test_list"},
                {"criterion": "DELETE removes", "test_name": "test_delete"},
            ],
        })
    # Deployment Agent
    return json.dumps({
        "files": [
            {"path": "Dockerfile", "content": (
                "FROM python:3.12-slim\nWORKDIR /app\nCOPY requirements.txt .\n"
                "RUN pip install --no-cache-dir -r requirements.txt\nCOPY . .\n"
                "EXPOSE 8000\nCMD [\"uvicorn\", \"main:app\", \"--host\", \"0.0.0.0\"]\n"
            )},
            {"path": "requirements.txt", "content": "fastapi>=0.115\nuvicorn>=0.30\n"},
        ],
        "deploy_steps": [
            "docker build -t todo-api .",
            "docker run -d -p 8000:8000 todo-api",
        ],
        "healthcheck": "curl http://localhost:8000/todos",
    })


if __name__ == "__main__":
    main()
