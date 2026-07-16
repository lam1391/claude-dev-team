# Design: Dependency Installation + Code Review Agent

**Date:** 2026-07-15
**Status:** Approved
**Goal:** Fix the two gaps that mislead the POC demo: (1) generated app dependencies are never installed before tests run, so missing modules masquerade as code bugs; (2) the team has no code reviewer, the highest-value missing role.

## Scope

In scope:

1. Install the generated app's dependencies into an isolated venv before running tests.
2. Add a fifth agent, the Code Review Agent, between developer and tester — in both the Python pipeline and the Claude Code subagent variant.
3. Update mock mode, README, and docs to match.

Out of scope (stays on the roadmap in `docs/05-next-steps.md`): sandboxing beyond the venv, Docker build verification, human-in-the-loop gates, structured outputs, per-stage models, existing-codebase support.

## Fix 1: Dependency installation

**Developer contract change** (`agents.py`):

- `DEVELOPER_PROMPT` requires the `files` list to include a `requirements.txt` at the app root, pinning at least major versions, covering every import the app and its tests need (pytest itself is installed by the orchestrator).
- `validate_developer` rejects output whose `files` contain no `requirements.txt` path.

**Orchestrator change** (`orchestrator.py`):

- New helper `setup_venv()` — creates `pipeline_output/app/.venv` with `python -m venv` (recreated fresh each run), then installs `requirements.txt` plus `pytest` into it. If the install fails, the pip error is fed back to the developer once (bad requirements are a developer-output problem, mirroring the existing retry pattern); if it fails again, the pipeline stops loudly.
- `run_tests()` uses the venv's Python (`.venv/bin/python -m pytest`) instead of `sys.executable`.
- Because the developer may rewrite `requirements.txt` during fix loops, dependencies are re-installed after each developer iteration (pip is idempotent; cost is seconds).

This also isolates generated code's imports from the project venv.

## Fix 2: Code Review Agent

**New agent** (`agents.py`), inserted between developer and tester in `PIPELINE`:

- **Input:** the plan JSON + the developer's files JSON.
- **Output schema:**

```json
{
  "approved": true,
  "issues": [
    {"file": "main.py", "severity": "high|medium|low", "description": "..."}
  ],
  "summary": "one-paragraph review verdict"
}
```

- `validate_reviewer` requires `approved` (bool) and `summary`; `issues` must be a list (may be empty only when approved).

**Orchestrator logic** (`main()`):

- After the developer stage (and before writing test files): run the reviewer.
- If `approved` is false: send the issues back to the developer using the existing feedback pattern, then re-review. Bounded by `MAX_REVIEW_LOOPS = 1`.
- If still rejected after the loop: print a loud warning listing the open issues and proceed — reviewers advise, tests decide. No hard stop.
- Reviewer output is saved as an artifact like every other stage (`reviewer_output.json`).

**Claude Code variant** — new `claude-code-alternative/.claude/agents/reviewer.md`:

- Frontmatter: `name: reviewer`, description says "Use AFTER developer, BEFORE tester", `tools: Read, Glob, Grep` (read-only, least privilege).
- Body: review the implemented code against `plan.md`; report issues by file with severity; do NOT modify code; approve or request changes from the developer agent.

## Mock mode

`mock_response()` gains a canned reviewer response (`approved: true`, empty issues) keyed on the reviewer system-prompt prefix, so `MOCK=1 python orchestrator.py` exercises all five stages. Venv setup runs in mock mode too, proving the plumbing end to end (the mock developer response gains a requirements.txt with fastapi + uvicorn so the install is real).

## Docs

- README: architecture diagram becomes 5 stages; supervision table gains the review loop row; pipeline_output listing gains `reviewer_output.json`.
- `docs/04-claude-code-alternative.md`: mention the reviewer subagent and the updated example prompt.

## Testing

- `MOCK=1 python orchestrator.py` must run all five stages, create the venv, install deps, and pass the mock tests.
- Manual check: temporarily break the mock developer response (drop requirements.txt) and confirm validation rejects it.
