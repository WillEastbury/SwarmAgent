"""Tests for config module."""

import pytest

from swarm_agent.config import Config


@pytest.fixture()
def _env_vars(monkeypatch):
    """Set required environment variables."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_token")
    monkeypatch.setenv("SWARM_PERSONA", "reviewer")
    monkeypatch.setenv("SWARM_TASK", "review")
    monkeypatch.setenv("SWARM_REPO", "org/repo")


@pytest.mark.usefixtures("_env_vars")
class TestConfig:
    def test_from_env_loads_required(self):
        config = Config.from_env()
        assert config.openai_api_key == "sk-test-key"
        assert config.github_token == "ghp_test_token"
        assert config.persona == "reviewer"
        assert config.task == "review"
        assert config.repo == "org/repo"

    def test_from_env_defaults(self):
        config = Config.from_env()
        assert config.pr_number is None
        assert config.issue_number is None
        assert config.openai_model == "gpt-4o"

    def test_from_env_with_pr(self, monkeypatch):
        monkeypatch.setenv("SWARM_PR_NUMBER", "42")
        config = Config.from_env()
        assert config.pr_number == 42
        assert config.target_type == "pr"
        assert config.target_ref == "42"
        assert config.discover_work is False

    def test_from_env_with_issue(self, monkeypatch):
        monkeypatch.setenv("SWARM_ISSUE_NUMBER", "7")
        config = Config.from_env()
        assert config.issue_number == 7
        assert config.target_type == "issue"
        assert config.discover_work is False

    def test_from_env_missing_vars(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY")
        with pytest.raises(OSError, match="OPENAI_API_KEY"):
            Config.from_env()

    def test_repo_clone_url(self):
        config = Config.from_env()
        assert "ghp_test_token" in config.repo_clone_url
        assert "org/repo.git" in config.repo_clone_url

    def test_target_type_repo_level(self):
        config = Config.from_env()
        assert config.target_type == "repo"
        assert config.target_ref == "org/repo"

    def test_discover_work_when_no_issue_or_pr(self):
        config = Config.from_env()
        assert config.discover_work is True

    def test_task_not_required(self, monkeypatch):
        """SWARM_TASK is optional — defaults to 'review'."""
        monkeypatch.delenv("SWARM_TASK", raising=False)
        config = Config.from_env()
        assert config.task == "review"

    def test_with_issue(self):
        config = Config.from_env()
        new_config = config.with_issue(99)
        assert new_config.issue_number == 99
        assert new_config.target_type == "issue"
        assert new_config.discover_work is False
        assert new_config.persona == config.persona
        assert new_config.repo == config.repo

    def test_with_pr(self):
        config = Config.from_env()
        new_config = config.with_pr(55)
        assert new_config.pr_number == 55
        assert new_config.issue_number is None
        assert new_config.target_type == "pr"
        assert new_config.discover_work is False
        assert new_config.persona == config.persona
