"""Environment-based configuration for SwarmAgent."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Immutable agent configuration loaded from environment variables."""

    openai_api_key: str
    github_token: str
    persona: str
    task: str
    repo: str
    pr_number: int | None = None
    issue_number: int | None = None
    openai_model: str = "gpt-4o"
    openai_base_url: str = "https://api.openai.com/v1"
    workdir: str = "/tmp/swarm-agent-workspace"

    @classmethod
    def from_env(cls) -> Config:
        """Load configuration from environment variables. Raises on missing required vars."""
        missing = [
            v
            for v in ("OPENAI_API_KEY", "GITHUB_TOKEN", "SWARM_PERSONA", "SWARM_TASK", "SWARM_REPO")
            if not os.environ.get(v)
        ]
        if missing:
            raise OSError(f"Missing required environment variables: {', '.join(missing)}")

        pr = os.environ.get("SWARM_PR_NUMBER")
        issue = os.environ.get("SWARM_ISSUE_NUMBER")

        return cls(
            openai_api_key=os.environ["OPENAI_API_KEY"],
            github_token=os.environ["GITHUB_TOKEN"],
            persona=os.environ["SWARM_PERSONA"],
            task=os.environ["SWARM_TASK"],
            repo=os.environ["SWARM_REPO"],
            pr_number=int(pr) if pr else None,
            issue_number=int(issue) if issue else None,
            openai_model=os.environ.get("OPENAI_MODEL", "gpt-4o"),
            openai_base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            workdir=os.environ.get("SWARM_WORKDIR", "/tmp/swarm-agent-workspace"),
        )

    @property
    def repo_clone_url(self) -> str:
        return f"https://x-access-token:{self.github_token}@github.com/{self.repo}.git"

    @property
    def target_type(self) -> str:
        """Whether this agent is operating on a PR, issue, or repo-level."""
        if self.pr_number is not None:
            return "pr"
        if self.issue_number is not None:
            return "issue"
        return "repo"

    @property
    def target_ref(self) -> str:
        """GitHub reference for the target (e.g., '42' for PR #42)."""
        if self.pr_number is not None:
            return str(self.pr_number)
        if self.issue_number is not None:
            return str(self.issue_number)
        return self.repo
