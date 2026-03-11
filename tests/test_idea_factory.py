"""Tests for the Idea Factory web app."""

from base64 import b64encode
from unittest.mock import patch

import pytest

from swarm_agent.idea_factory.app import create_app


@pytest.fixture()
def app_env(monkeypatch):
    monkeypatch.setenv("IDEA_FACTORY_USERNAME", "testuser")
    monkeypatch.setenv("IDEA_FACTORY_PASSWORD", "testpass")
    monkeypatch.setenv("SWARM_REPO", "org/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("IDEA_FACTORY_SECRET_KEY", "testsecret")


@pytest.fixture()
def client(app_env):
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _auth_header(username="testuser", password="testpass"):
    creds = b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {creds}"}


class TestIdeaFactory:
    def test_healthz_no_auth(self, client):
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.data == b"ok"

    def test_index_requires_auth(self, client):
        resp = client.get("/")
        assert resp.status_code == 401

    def test_index_wrong_password(self, client):
        resp = client.get("/", headers=_auth_header("testuser", "wrong"))
        assert resp.status_code == 401

    def test_index_success(self, client):
        resp = client.get("/", headers=_auth_header())
        assert resp.status_code == 200
        assert b"Idea Factory" in resp.data

    def test_submit_requires_auth(self, client):
        resp = client.post("/submit", data={"title": "test"})
        assert resp.status_code == 401

    def test_submit_empty_title_redirects(self, client):
        resp = client.post(
            "/submit",
            data={"title": "", "body": "desc"},
            headers=_auth_header(),
            follow_redirects=True,
        )
        assert b"Title is required" in resp.data

    @patch("swarm_agent.idea_factory.app.subprocess.run")
    def test_submit_creates_issue(self, mock_run, client):
        mock_run.return_value.stdout = "https://github.com/org/repo/issues/1\n"
        mock_run.return_value.returncode = 0

        resp = client.post(
            "/submit",
            data={"title": "My Idea", "body": "Some details"},
            headers=_auth_header(),
            follow_redirects=True,
        )

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "gh" in cmd
        assert "issue" in cmd
        assert "create" in cmd
        assert "My Idea" in cmd
        assert b"Idea submitted" in resp.data

    @patch("swarm_agent.idea_factory.app.subprocess.run")
    def test_submit_gh_failure(self, mock_run, client):
        from subprocess import CalledProcessError

        mock_run.side_effect = CalledProcessError(1, "gh", stderr="auth failed")

        resp = client.post(
            "/submit",
            data={"title": "My Idea", "body": ""},
            headers=_auth_header(),
            follow_redirects=True,
        )
        assert b"Failed to create issue" in resp.data

    def test_missing_env_vars_raises(self, monkeypatch):
        monkeypatch.delenv("IDEA_FACTORY_USERNAME", raising=False)
        monkeypatch.delenv("IDEA_FACTORY_PASSWORD", raising=False)
        monkeypatch.setenv("SWARM_REPO", "org/repo")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
        with pytest.raises(RuntimeError, match="IDEA_FACTORY_USERNAME"):
            create_app()
