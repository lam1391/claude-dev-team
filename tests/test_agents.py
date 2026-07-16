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


def test_developer_rejects_non_root_requirements():
    ok, err = agents.validate_developer(
        _dev_output([
            {"path": "main.py", "content": "x = 1"},
            {"path": "sub/requirements.txt", "content": "fastapi>=0.115\n"},
        ])
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
