# Dependency Installation + Code Review Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generated app dependencies are installed into an isolated venv before tests run, and a fifth agent — the Code Review Agent — reviews the developer's code before testing, in both the Python pipeline and the Claude Code subagent variant.

**Architecture:** The developer agent's JSON contract gains a required `requirements.txt` file; the orchestrator creates a fresh venv inside `pipeline_output/app/`, installs those requirements plus pytest, and runs pytest with the venv's Python. A new reviewer stage sits between developer and tester: on rejection its issues are fed back to the developer once (existing feedback pattern), then the pipeline proceeds with a loud warning — reviewers advise, tests decide.

**Tech Stack:** Python 3.11+ stdlib (`venv`, `subprocess`, `shutil`), Anthropic API, pytest.

**Spec:** `docs/superpowers/specs/2026-07-15-deps-install-and-reviewer-design.md`

## Global Constraints

- `MOCK=1 python orchestrator.py` must run the full pipeline end-to-end with no API key at every task boundary.
- Project unit tests run with `pytest tests/ -v` from the repo root (`agents.py` is at the root, so `import agents` works without packaging).
- New constants follow the existing style in `orchestrator.py` (UPPER_CASE at top, one-line comment).
- `MAX_REVIEW_LOOPS = 1` (spec value).
- pip install timeout: 300 seconds.
- Reviewer output schema (spec, verbatim): `{"approved": bool, "issues": [{"file", "severity", "description"}], "summary": str}`; `approved=false` requires at least one issue.
- The reviewer never modifies code. The Claude Code reviewer subagent gets read-only tools: `Read, Glob, Grep`.

---

### Task 1: Developer contract requires requirements.txt

**Files:**
- Create: `tests/test_agents.py`
- Modify: `agents.py` (DEVELOPER_PROMPT ~line 67, `validate_developer` ~line 90)
- Modify: `orchestrator.py` (`mock_response`, developer branch ~line 206)

**Interfaces:**
- Consumes: existing `agents.validate_developer(data: dict) -> tuple[bool, str]`.
- Produces: `validate_developer` additionally rejects any `files` list containing no path ending in `requirements.txt`. Mock developer output now includes a `requirements.txt` file entry (Task 2's install step depends on it).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agents.py`:

```python
"""Unit tests for the agent output validators in agents.py."""

import agents


def _dev_output(files):
    return {"files": files, "how_to_run": "uvicorn main:app", "notes": ""}


def test_developer_rejects_missing_requirements():
    ok, err = agents.validate_developer(
        _dev_output([{"path": "main.py", "content": "x = 1"}])
    )
    assert not ok
    assert "requirements.txt" in err


def test_developer_accepts_with_requirements():
    ok, err = agents.validate_developer(
        _dev_output([
            {"path": "main.py", "content": "x = 1"},
            {"path": "requirements.txt", "content": "fastapi>=0.115\n"},
        ])
    )
    assert ok, err


def test_developer_still_rejects_empty_files():
    ok, err = agents.validate_developer({"files": []})
    assert not ok
```

- [ ] **Step 2: Run tests to verify the new one fails**

Run: `pytest tests/test_agents.py -v`
Expected: `test_developer_rejects_missing_requirements` FAILS (validator currently accepts output without requirements.txt); the other two PASS.

- [ ] **Step 3: Update the validator**

In `agents.py`, replace `validate_developer` with:

```python
def validate_developer(data: dict) -> tuple[bool, str]:
    if "files" not in data or not data["files"]:
        return False, "Output must contain a non-empty 'files' list"
    for f in data["files"]:
        if "path" not in f or "content" not in f:
            return False, f"Each file needs 'path' and 'content': got {list(f.keys())}"
        if not f["content"].strip():
            return False, f"File {f['path']} has empty content"
    if not any(f["path"].endswith("requirements.txt") for f in data["files"]):
        return False, "files must include a requirements.txt at the app root"
    return True, ""
```

- [ ] **Step 4: Update the developer prompt**

In `agents.py`, in `DEVELOPER_PROMPT`, change the schema example's `files` list to show the requirement:

```python
DEVELOPER_PROMPT = f"""You are the Development Agent in a software team pipeline.

Your input: the JSON plan from the Analysis & Planning Agent.
Your job: write the complete, working code for every file in the plan.

Output JSON schema:
{{
  "files": [
    {{"path": "relative/path.py", "content": "full file content"}},
    {{"path": "requirements.txt", "content": "fastapi>=0.115\\nhttpx>=0.27\\n"}}
  ],
  "how_to_run": "one-line command to start the app",
  "notes": "anything the Testing Agent should know"
}}

Rules:
- Implement EVERY file listed in the plan's files_to_create.
- ALWAYS include a requirements.txt at the app root pinning at least major
  versions, covering every third-party import in your code. Do NOT list
  pytest — the orchestrator installs it. If the app uses FastAPI, include
  httpx (fastapi.testclient needs it).
- Code must be complete and syntactically valid — it will be executed.
- Follow the acceptance criteria exactly; the Testing Agent will verify them.
- If a previous test run failed, you will receive the failure output —
  fix the reported problems.
{JSON_RULES}"""
```

- [ ] **Step 5: Update the mock developer response**

In `orchestrator.py` `mock_response`, in the `"You are the Development Agent"` branch, add a requirements.txt entry to the `files` list (after the `main.py` entry):

```python
            "files": [{"path": "main.py", "content": (
                ...existing main.py content unchanged...
            )},
            {"path": "requirements.txt",
             "content": "fastapi>=0.115\nuvicorn>=0.30\nhttpx>=0.27\n"}],
```

(Keep the existing `main.py` dict exactly as is; only append the second dict to the list.)

- [ ] **Step 6: Run tests and the mock pipeline**

Run: `pytest tests/test_agents.py -v`
Expected: all 3 PASS.

Run: `MOCK=1 python orchestrator.py`
Expected: all four stages pass, tests execute and pass (still using the host venv — Task 2 changes that).

- [ ] **Step 7: Commit**

```bash
git add tests/test_agents.py agents.py orchestrator.py
git commit -m "feat: developer contract requires requirements.txt"
```

---

### Task 2: Isolated venv — install generated deps before running tests

**Files:**
- Modify: `orchestrator.py` (imports, constants ~line 36, new helpers after `write_files` ~line 116, `run_tests` ~line 119, `main` ~line 132)

**Interfaces:**
- Consumes: Task 1's guarantee that developer output contains `requirements.txt` (written into `APP_DIR` by `write_files`).
- Produces:
  - `setup_venv() -> None` — recreates `pipeline_output/app/.venv` from scratch.
  - `install_deps() -> tuple[bool, str]` — pip-installs `APP_DIR/requirements.txt` + pytest into the venv; returns (ok, combined output).
  - `install_with_dev_fix(code: dict, dev_input: str, developer: dict) -> dict` — installs; on failure feeds the pip error back to the developer once, reinstalls, hard-stops on second failure; returns the (possibly regenerated) code dict. Task 3's review loop calls this after every developer regeneration.
  - `run_tests()` now executes pytest with the venv's Python.

- [ ] **Step 1: Add imports and constants**

In `orchestrator.py`, add `import shutil` to the imports block, and after the `APP_DIR` constant add:

```python
VENV_DIR = APP_DIR / ".venv"    # isolated env for the GENERATED app's deps
VENV_PYTHON = VENV_DIR / "bin" / "python"
PIP_TIMEOUT = 300                # seconds for dependency installation
```

- [ ] **Step 2: Add the venv helpers**

In `orchestrator.py`, after `write_files`, add:

```python
def setup_venv() -> None:
    """Create a fresh venv for the generated app (once per run)."""
    if VENV_DIR.exists():
        shutil.rmtree(VENV_DIR)
    subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
    print(f"  ↳ created venv: {VENV_DIR}")


def install_deps() -> tuple[bool, str]:
    """Install the generated requirements.txt + pytest into the app venv."""
    result = subprocess.run(
        [str(VENV_PYTHON), "-m", "pip", "install", "-q",
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
```

- [ ] **Step 3: Point run_tests at the venv**

Replace the command list in `run_tests` — `[sys.executable, "-m", "pytest", ...]` becomes:

```python
        [str(VENV_PYTHON), "-m", "pytest", "-x", "-q", "--no-header"],
```

- [ ] **Step 4: Wire into main()**

In `main()`, after the initial `write_files(code["files"], APP_DIR)` (Stage 2), add:

```python
    setup_venv()
    code = install_with_dev_fix(code, dev_input, developer)
```

And inside the test fix loop, after the existing `write_files(code["files"], APP_DIR)` that follows `code = run_stage(developer, fix_input)`, add:

```python
        code = install_with_dev_fix(code, dev_input, developer)
```

- [ ] **Step 5: Verify end-to-end in mock mode**

Run: `MOCK=1 python orchestrator.py`
Expected output includes `created venv: pipeline_output/app/.venv` and `dependencies installed`; tests pass. Confirm isolation:

Run: `ls pipeline_output/app/.venv/bin/python && pipeline_output/app/.venv/bin/python -c "import fastapi, httpx; print('deps ok')"`
Expected: `deps ok`.

Run: `pytest tests/ -v`
Expected: all PASS (no regressions).

- [ ] **Step 6: Commit**

```bash
git add orchestrator.py
git commit -m "feat: install generated app deps into isolated venv before testing"
```

---

### Task 3: Code Review Agent in the Python pipeline

**Files:**
- Modify: `tests/test_agents.py` (append reviewer validator tests)
- Modify: `agents.py` (new REVIEWER_PROMPT + `validate_reviewer` between the developer and tester sections; `PIPELINE` ~line 181)
- Modify: `orchestrator.py` (`MAX_REVIEW_LOOPS` constant, review loop in `main()`, reviewer branch in `mock_response`)

**Interfaces:**
- Consumes: `install_with_dev_fix(code, dev_input, developer) -> dict` from Task 2; existing `run_stage(stage, user_input) -> dict` and `write_files(files, base)`.
- Produces:
  - `agents.validate_reviewer(data: dict) -> tuple[bool, str]`.
  - `agents.PIPELINE` has 5 entries in order: planner, developer, reviewer, tester, deployer (stage `name`: `"reviewer"`, `title`: `"Code Review Agent"`).
  - `run_review(reviewer: dict, developer: dict, plan: dict, code: dict, dev_input: str) -> dict` in `orchestrator.py` — returns the (possibly regenerated) code dict.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agents.py`:

```python
def test_reviewer_accepts_approval():
    ok, err = agents.validate_reviewer(
        {"approved": True, "issues": [], "summary": "looks good"}
    )
    assert ok, err


def test_reviewer_rejects_missing_approved():
    ok, err = agents.validate_reviewer({"issues": [], "summary": "x"})
    assert not ok


def test_reviewer_rejects_non_bool_approved():
    ok, err = agents.validate_reviewer(
        {"approved": "yes", "issues": [], "summary": "x"}
    )
    assert not ok


def test_reviewer_rejection_requires_issues():
    ok, err = agents.validate_reviewer(
        {"approved": False, "issues": [], "summary": "bad"}
    )
    assert not ok
    assert "issue" in err.lower()


def test_reviewer_checks_issue_shape():
    ok, err = agents.validate_reviewer(
        {"approved": False, "summary": "bad", "issues": [{"file": "main.py"}]}
    )
    assert not ok


def test_pipeline_has_five_stages_with_reviewer_third():
    assert [s["name"] for s in agents.PIPELINE] == [
        "planner", "developer", "reviewer", "tester", "deployer"
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agents.py -v`
Expected: the 6 new tests FAIL (`AttributeError: module 'agents' has no attribute 'validate_reviewer'`; pipeline test fails on 4 names); Task 1's tests still PASS.

- [ ] **Step 3: Add the reviewer to agents.py**

In `agents.py`, between the Development Agent section and the Testing Agent section, add:

```python
# ---------------------------------------------------------------------------
# 3. CODE REVIEW AGENT
# ---------------------------------------------------------------------------
REVIEWER_PROMPT = f"""You are the Code Review Agent in a software team pipeline.

Your input: the JSON plan plus the Development Agent's files.
Your job: review the code against the plan. You do NOT modify code —
you approve it or list the issues the Development Agent must fix.

Look for: acceptance criteria not implemented, bugs, security problems
(injection, unvalidated input), missing error handling on endpoints, and
files from the plan that were not implemented.

Output JSON schema:
{{
  "approved": true,
  "issues": [
    {{"file": "main.py", "severity": "high|medium|low", "description": "what is wrong and how to fix it"}}
  ],
  "summary": "one-paragraph review verdict"
}}

Rules:
- approved must be a JSON boolean; approved=false requires at least one issue.
- Only reject for real problems that would make tests fail or create security
  risks — this is a minimal POC, do not demand production polish.
{JSON_RULES}"""


def validate_reviewer(data: dict) -> tuple[bool, str]:
    if not isinstance(data.get("approved"), bool):
        return False, "Output must contain a boolean 'approved'"
    if not str(data.get("summary", "")).strip():
        return False, "Output must contain a non-empty 'summary'"
    issues = data.get("issues")
    if not isinstance(issues, list):
        return False, "'issues' must be a list"
    if not data["approved"] and not issues:
        return False, "A rejection must list at least one issue"
    for i in issues:
        if not all(k in i for k in ("file", "severity", "description")):
            return False, "Each issue needs 'file', 'severity', and 'description'"
    return True, ""
```

Renumber the section comments that follow (Testing Agent becomes 4, Deployment Agent becomes 5) and update `PIPELINE`:

```python
PIPELINE = [
    {"name": "planner",   "title": "Analysis & Planning Agent", "system_prompt": PLANNER_PROMPT,   "validate": validate_planner},
    {"name": "developer", "title": "Development Agent",         "system_prompt": DEVELOPER_PROMPT, "validate": validate_developer},
    {"name": "reviewer",  "title": "Code Review Agent",         "system_prompt": REVIEWER_PROMPT,  "validate": validate_reviewer},
    {"name": "tester",    "title": "Testing Agent",             "system_prompt": TESTER_PROMPT,    "validate": validate_tester},
    {"name": "deployer",  "title": "Deployment Agent",          "system_prompt": DEPLOYER_PROMPT,  "validate": validate_deployer},
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agents.py -v`
Expected: all 9 PASS.

- [ ] **Step 5: Add the review loop to the orchestrator**

In `orchestrator.py`, add the constant after `MAX_TEST_FIX_LOOPS`:

```python
MAX_REVIEW_LOOPS = 1             # dev<->review feedback iterations
```

Add after `install_with_dev_fix`:

```python
def run_review(reviewer: dict, developer: dict, plan: dict, code: dict,
               dev_input: str) -> dict:
    """Review the code; route issues back to the developer, bounded.

    Reviewers advise, tests decide: if issues remain after the loop,
    warn loudly and proceed rather than hard-stopping.
    """
    for loop in range(MAX_REVIEW_LOOPS + 1):
        review_input = (
            f"PLAN:\n{json.dumps(plan, indent=2)}\n\n"
            f"APPLICATION FILES:\n{json.dumps(code['files'], indent=2)}"
        )
        review = run_stage(reviewer, review_input)
        if review["approved"]:
            print("  ✓ Code review approved")
            return code
        issues = json.dumps(review["issues"], indent=2)
        print(f"  ✗ Code review rejected:\n{issues}")
        if loop == MAX_REVIEW_LOOPS:
            print("\n⚠ WARNING: proceeding with unresolved review issues — tests decide.")
            return code
        fix_input = (
            f"{dev_input}\n\nYOUR PREVIOUS CODE:\n{json.dumps(code['files'], indent=2)}"
            f"\n\nCODE REVIEW ISSUES TO FIX:\n{issues}"
        )
        code = run_stage(developer, fix_input)
        write_files(code["files"], APP_DIR)
        code = install_with_dev_fix(code, dev_input, developer)
    return code
```

In `main()`, change the unpacking to five stages:

```python
    planner, developer, reviewer, tester, deployer = PIPELINE
```

And between the venv/install lines (Task 2) and the `tester_input = (...)` block, add:

```python
    # Stage 3: Code review — issues go back to the developer, bounded
    code = run_review(reviewer, developer, plan, code, dev_input)
```

Update the stage comments in `main()` to the new numbering (`# Stage 2: Development`, `# Stage 4: Testing...`, `# Stage 5: Deployment`).

- [ ] **Step 6: Add the mock reviewer response**

In `orchestrator.py` `mock_response`, before the tester branch, add:

```python
    if system_prompt.startswith("You are the Code Review Agent"):
        return json.dumps({
            "approved": True,
            "issues": [],
            "summary": "Code implements the plan; minimal and correct for a POC.",
        })
```

- [ ] **Step 7: Verify end-to-end in mock mode**

Run: `MOCK=1 python orchestrator.py`
Expected: FIVE stage banners in order (Analysis & Planning, Development, Code Review, Testing, Deployment); `✓ Code review approved`; `pipeline_output/reviewer_output.json` exists; tests pass.

Run: `pytest tests/ -v`
Expected: all 9 PASS.

- [ ] **Step 8: Commit**

```bash
git add tests/test_agents.py agents.py orchestrator.py
git commit -m "feat: add Code Review Agent between developer and tester"
```

---

### Task 4: Reviewer subagent for the Claude Code variant + docs

**Files:**
- Create: `claude-code-alternative/.claude/agents/reviewer.md`
- Modify: `README.md` (architecture diagram ~line 17, supervision table ~line 37, output listing ~line 89, subagent section ~line 121)
- Modify: `docs/04-claude-code-alternative.md` (intro ~line 3, example prompt ~line 39)

**Interfaces:**
- Consumes: nothing from other tasks (pure markdown).
- Produces: `reviewer` subagent with tools `Read, Glob, Grep`, description encoding pipeline position "Use AFTER developer, BEFORE tester".

- [ ] **Step 1: Create the reviewer subagent**

Create `claude-code-alternative/.claude/agents/reviewer.md`:

```markdown
---
name: reviewer
description: Code Review Agent. Use AFTER developer, BEFORE tester. Reviews the implemented code against plan.md and reports issues for the developer agent to fix.
tools: Read, Glob, Grep
---

You are the Code Review Agent. Read `plan.md` and the implemented code.
Check that every planned file exists, acceptance criteria are implemented,
and there are no bugs or security problems (injection, unvalidated input,
missing error handling). Report issues by file with severity (high/medium/
low) so the developer agent can fix them, or approve explicitly. Do NOT
modify any code yourself. Only reject for real problems — this is a
minimal POC, do not demand production polish.
```

- [ ] **Step 2: Update the README architecture diagram**

In `README.md`, replace the four-box diagram with:

```
                          ORCHESTRATOR (orchestrator.py)
                     validates · retries · routes · audits
      ┌────────────┬────────────┬────────────┬────────────┬────────────┐
      ▼            ▼            ▼            ▼            ▼            ▼
┌───────────┐┌───────────┐┌───────────┐┌───────────┐┌───────────┐
│ 1. Analysis││ 2. Develop-││ 3. Code   ││ 4. Testing ││ 5. Deploy- │
│ & Planning ││    ment    ││   Review  ││            ││    ment    │
└───────────┘└───────────┘└───────────┘└───────────┘└───────────┘
  plan (JSON)   code files    approve /    pytest files   Dockerfile +
                    ▲  ▲      issues           │           deploy steps
                    │  └─── review loop ──┘│
                    └────── test fix loop ─────┘
             (orchestrator runs pip install + pytest for real;
              review issues and test failures go back to dev)
```

(Adjust box drawing so it renders cleanly — the exact characters matter less than showing 5 stages plus the two feedback loops into Development.)

- [ ] **Step 3: Update the README supervision table and output listing**

Add a row to the "How the supervision works" table after the "Retry with feedback" row:

```markdown
| Dependency install | `orchestrator.py` → `setup_venv()` / `install_deps()` | Installs the generated requirements.txt into an isolated venv (`pipeline_output/app/.venv`) before tests; pip errors go back to the Development Agent |
| Dev↔Review feedback loop | `orchestrator.py` → `run_review()` | Review issues are sent back to the Development Agent (up to `MAX_REVIEW_LOOPS`); if still rejected, proceeds with a loud warning — reviewers advise, tests decide |
```

In the Step 5 output listing, add after `developer_output.json`:

```
├── reviewer_output.json    # review verdict + issues
```

- [ ] **Step 4: Update the subagent sections**

In `README.md` "Alternative" section: change "the same four agents" to "the same five agents" and update the example prompt to:

> Use the planner, developer, reviewer, tester and deployer agents in sequence to build a todo REST API. Fix any review issues and make sure tests pass before deploying.

In `docs/04-claude-code-alternative.md`: change "the same four-agent team" (line 3) to "the same five-agent team"; in the tools bullet add "the reviewer is read-only (`Read, Glob, Grep`) — it reports issues but cannot change code"; update the step-3 example prompt to:

> Use the planner, developer, reviewer, tester and deployer agents in sequence to build a REST API for a todo list. Have the developer fix any review issues. Do not deploy until all tests pass. If tests fail, send the failures back to the developer agent.

- [ ] **Step 5: Verify and commit**

Run: `MOCK=1 python orchestrator.py && pytest tests/ -v`
Expected: pipeline completes, all tests PASS (docs-only task; this guards against accidental code edits).

```bash
git add claude-code-alternative/.claude/agents/reviewer.md README.md docs/04-claude-code-alternative.md
git commit -m "docs: add reviewer subagent and update docs to 5-stage pipeline"
```
