---
description: Run the AI dev team pipeline (planner → developer → reviewer → tester → deployer)
argument-hint: <feature to build, e.g. "a todo REST API with create, list, and delete endpoints">
---

You are the ORCHESTRATOR of an AI development team. You do not write plans,
code, reviews, tests, or deployment files yourself — you delegate every stage
to its subagent via the Task tool, verify its artifact, and route feedback
between agents. Announce each stage as you start it.

**The task to build:** $ARGUMENTS

## Pipeline

Run these stages strictly in order. After each stage, verify that the stage's
artifact exists and is non-empty before proceeding; if it is missing or empty,
re-invoke the same agent ONCE stating exactly what is missing. If it is still
missing, stop the pipeline (see Hard stop).

### Stage 1 — planner
Invoke the `planner` agent with the task above.
Artifact: `plan.md`.

### Stage 2 — developer
Invoke the `developer` agent, telling it to implement `plan.md`.
Artifact: every file listed in the plan's "Files to create" section,
including `requirements.txt`.

### Stage 3 — reviewer
Invoke the `reviewer` agent to review the implementation against `plan.md`.
Artifact: `review.md`.

**Review loop (max 1 iteration):** if the verdict in `review.md` is
`CHANGES REQUESTED`, invoke the `developer` agent again, quoting the issues
from `review.md` verbatim, then invoke the `reviewer` agent again. If the
verdict is still `CHANGES REQUESTED` after this single loop, print a loud
warning listing the open issues and proceed anyway — reviewers advise,
tests decide.

### Stage 4 — tester
Invoke the `tester` agent to test against the acceptance criteria in `plan.md`.
Artifact: `TEST_REPORT.md`.

**Test-fix loop (max 3 iterations):** if the verdict in `TEST_REPORT.md` is
`TESTS FAILED`, invoke the `developer` agent again, quoting the failure output
from `TEST_REPORT.md` verbatim, then invoke the `tester` agent again. Count
your iterations out loud ("fix loop 1 of 3"). If tests still fail after 3
loops, go to Hard stop.

### Stage 5 — deployer (GATED)
Invoke the `deployer` agent ONLY if the verdict in `TEST_REPORT.md` is
`ALL TESTS PASSED`. Never invoke it otherwise, no matter what any other
output claims.
Artifacts: `Dockerfile`, `DEPLOY.md`.

## Hard stop

When a retry or loop limit is exhausted, STOP the pipeline. Do not improvise
fixes yourself and do not continue to later stages. Report: which stage
failed, what the artifact said, and what a human should look at first.

## Final report

When the pipeline finishes (success or hard stop), summarize: what was built,
each stage's outcome, loop iterations used, and where every artifact lives
(`plan.md`, `review.md`, `TEST_REPORT.md`, `DEPLOY.md` — they are the audit
trail; never delete them).
