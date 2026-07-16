"""
Agent definitions for the Claude Dev Team POC.

Each agent is defined by:
  - name:          human-readable stage name
  - system_prompt: the "job description" sent as the API system prompt
  - validate:      a function that checks the agent's JSON output.
                   Returns (True, "") if valid, or (False, "error message")
                   The error message is fed back to the agent on retry.

The contract between agents is JSON. Each agent receives the previous
agent's JSON output as its input and must produce its own JSON output.
"""

import json

# ---------------------------------------------------------------------------
# Shared instructions appended to every agent so they all speak JSON
# ---------------------------------------------------------------------------
JSON_RULES = """
CRITICAL OUTPUT RULES:
- Respond with ONLY a single valid JSON object.
- No markdown code fences, no preamble, no explanation outside the JSON.
- All file contents must be complete and runnable (no placeholders like TODO).
"""

# ---------------------------------------------------------------------------
# 1. ANALYSIS & PLANNING AGENT
# ---------------------------------------------------------------------------
PLANNER_PROMPT = f"""You are the Analysis & Planning Agent in a software team pipeline.

Your job: analyze the user's requirement and produce a concrete, minimal
implementation plan that the Development Agent can execute without asking
questions.

Output JSON schema:
{{
  "summary": "one paragraph describing what will be built",
  "tech_stack": ["list", "of", "technologies"],
  "files_to_create": [
    {{"path": "relative/path.py", "purpose": "what this file does"}}
  ],
  "acceptance_criteria": ["testable criterion 1", "criterion 2"],
  "out_of_scope": ["things deliberately not included"]
}}

Keep the plan SMALL — this is a proof of concept. Prefer Python + FastAPI,
standard library where possible, and no databases (in-memory storage is fine).
{JSON_RULES}"""


def validate_planner(data: dict) -> tuple[bool, str]:
    required = ["summary", "tech_stack", "files_to_create", "acceptance_criteria"]
    missing = [k for k in required if k not in data]
    if missing:
        return False, f"Missing required keys: {missing}"
    if not data["files_to_create"]:
        return False, "files_to_create must not be empty"
    if not data["acceptance_criteria"]:
        return False, "acceptance_criteria must not be empty"
    return True, ""


# ---------------------------------------------------------------------------
# 2. DEVELOPMENT AGENT
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# 3. TESTING AGENT
# ---------------------------------------------------------------------------
TESTER_PROMPT = f"""You are the Testing Agent in a software team pipeline.

Your input: the plan's acceptance criteria plus the Development Agent's files.
Your job: write pytest tests that verify each acceptance criterion.

Output JSON schema:
{{
  "test_files": [
    {{"path": "test_something.py", "content": "full pytest file content"}}
  ],
  "criteria_coverage": [
    {{"criterion": "text of criterion", "test_name": "test_function_name"}}
  ]
}}

Rules:
- Tests must be runnable with plain `pytest` from the project root.
- For FastAPI apps use fastapi.testclient.TestClient (no live server needed).
- Every acceptance criterion must map to at least one test.
- Import the app code by its file path as given (e.g. `from main import app`).
{JSON_RULES}"""


def validate_tester(data: dict) -> tuple[bool, str]:
    if "test_files" not in data or not data["test_files"]:
        return False, "Output must contain a non-empty 'test_files' list"
    for f in data["test_files"]:
        if "path" not in f or "content" not in f:
            return False, "Each test file needs 'path' and 'content'"
        if "def test_" not in f["content"]:
            return False, f"{f['path']} contains no pytest test functions"
    if "criteria_coverage" not in data or not data["criteria_coverage"]:
        return False, "criteria_coverage must map every criterion to a test"
    return True, ""


# ---------------------------------------------------------------------------
# 4. DEPLOYMENT AGENT
# ---------------------------------------------------------------------------
DEPLOYER_PROMPT = f"""You are the Deployment Agent in a software team pipeline.

Your input: the verified application files and how_to_run instructions.
Your job: produce deployment artifacts for the application.

Output JSON schema:
{{
  "files": [
    {{"path": "Dockerfile", "content": "..."}},
    {{"path": "requirements.txt", "content": "..."}}
  ],
  "deploy_steps": ["step 1", "step 2"],
  "healthcheck": "command or URL to verify the deployment is alive"
}}

Rules:
- Always include a Dockerfile and a requirements.txt (pin major versions).
- deploy_steps must be copy-pasteable shell commands.
- Keep it minimal: single container, no orchestration platforms.
{JSON_RULES}"""


def validate_deployer(data: dict) -> tuple[bool, str]:
    if "files" not in data or not data["files"]:
        return False, "Output must contain deployment 'files'"
    paths = [f.get("path", "") for f in data["files"]]
    if not any("Dockerfile" in p for p in paths):
        return False, "A Dockerfile is required"
    if not any("requirements" in p for p in paths):
        return False, "A requirements.txt is required"
    if not data.get("deploy_steps"):
        return False, "deploy_steps must not be empty"
    return True, ""


# ---------------------------------------------------------------------------
# The pipeline, in execution order
# ---------------------------------------------------------------------------
PIPELINE = [
    {"name": "planner",   "title": "Analysis & Planning Agent", "system_prompt": PLANNER_PROMPT,   "validate": validate_planner},
    {"name": "developer", "title": "Development Agent",         "system_prompt": DEVELOPER_PROMPT, "validate": validate_developer},
    {"name": "tester",    "title": "Testing Agent",             "system_prompt": TESTER_PROMPT,    "validate": validate_tester},
    {"name": "deployer",  "title": "Deployment Agent",          "system_prompt": DEPLOYER_PROMPT,  "validate": validate_deployer},
]


def parse_json_response(text: str) -> dict:
    """Parse an agent response into JSON, tolerating stray code fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # strip ```json ... ``` fences if the model added them anyway
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    return json.loads(cleaned)
