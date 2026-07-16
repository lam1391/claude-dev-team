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
