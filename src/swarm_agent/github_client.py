"""GitHub operations via the `gh` CLI."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from swarm_agent.config import Config

logger = logging.getLogger(__name__)


class GitHubClient:
    """Wraps the `gh` CLI and git for GitHub operations."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._env = {
            **os.environ,
            "GH_TOKEN": config.github_token,
            "GIT_TERMINAL_PROMPT": "0",
        }

    async def _run(self, cmd: list[str], cwd: str | Path | None = None) -> str:
        """Run a command and return stdout. Raises on non-zero exit."""
        cmd_str = " ".join(cmd)
        logger.info("Running: %s", cmd_str)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env,
            cwd=cwd,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"Command failed ({proc.returncode}): {cmd_str}\n{stderr.decode()}"
            )
        return stdout.decode().strip()

    # ── Work discovery ──

    async def find_unclaimed_issue(self, persona: str) -> int | None:
        """Find an open issue not yet claimed by this persona.

        Returns the issue number, or None if no unclaimed work exists.
        Looks for open issues that do NOT have the review:started:<persona> label.
        """
        started_label = f"review:started:{persona}"
        complete_label = f"review:complete:{persona}"

        result = await self._run([
            "gh", "issue", "list",
            "--repo", self.config.repo,
            "--state", "open",
            "--json", "number,labels",
            "--limit", "50",
        ])

        if not result:
            return None

        issues = json.loads(result)
        for issue in issues:
            label_names = [lb["name"] for lb in issue.get("labels", [])]
            if started_label not in label_names and complete_label not in label_names:
                return issue["number"]

        return None

    async def claim_issue(self, issue_number: int, persona: str) -> bool:
        """Attempt to claim an issue by adding the started label.

        Returns True if claim succeeded. This is not perfectly atomic
        but provides best-effort deduplication across swarm pods.
        """
        label = f"review:started:{persona}"
        try:
            await self._run([
                "gh", "issue", "edit", str(issue_number),
                "--repo", self.config.repo,
                "--add-label", label,
            ])
            logger.info("Claimed issue #%d with label '%s'", issue_number, label)
            return True
        except RuntimeError:
            logger.warning("Failed to claim issue #%d", issue_number)
            return False

    # ── Repository operations ──

    async def clone_repo(self) -> Path:
        """Clone the target repo into the workspace directory."""
        workdir = Path(self.config.workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        repo_dir = workdir / self.config.repo.split("/")[-1]
        if repo_dir.exists():
            logger.info("Repo already cloned, pulling latest")
            await self._run(["git", "pull"], cwd=repo_dir)
        else:
            await self._run(
                ["git", "clone", self.config.repo_clone_url, str(repo_dir)]
            )
        return repo_dir

    # ── Label operations ──

    async def add_label(self, label: str) -> None:
        """Add a label to the target PR or issue."""
        target_type = self.config.target_type
        if target_type == "repo":
            logger.warning("No PR/issue target — skipping label: %s", label)
            return
        ref = self.config.target_ref
        logger.info("Adding label '%s' to %s #%s", label, target_type, ref)
        await self._run([
            "gh", target_type, "edit", ref,
            "--repo", self.config.repo,
            "--add-label", label,
        ])

    async def signal_started(self) -> None:
        """Signal that this persona has started working."""
        await self.add_label(f"review:started:{self.config.persona}")

    async def signal_complete(self) -> None:
        """Signal that this persona is satisfied and shutting down."""
        await self.add_label(f"review:complete:{self.config.persona}")

    # ── Comment operations ──

    async def add_comment(self, body: str) -> None:
        """Add a comment to the target PR or issue."""
        target_type = self.config.target_type
        if target_type == "repo":
            logger.warning("No PR/issue target — skipping comment")
            return
        ref = self.config.target_ref
        logger.info("Adding comment to %s #%s", target_type, ref)
        await self._run([
            "gh", target_type, "comment", ref,
            "--repo", self.config.repo,
            "--body", body,
        ])

    # ── PR operations ──

    async def create_pr(
        self, title: str, body: str, branch: str, base: str = "main"
    ) -> str:
        """Create a pull request. Returns the PR URL."""
        logger.info("Creating PR: %s (%s → %s)", title, branch, base)
        return await self._run([
            "gh", "pr", "create",
            "--repo", self.config.repo,
            "--title", title,
            "--body", body,
            "--head", branch,
            "--base", base,
        ])

    # ── Git operations (run inside cloned repo) ──

    async def commit_and_push(
        self, repo_dir: Path, message: str, branch: str
    ) -> None:
        """Stage all changes, commit, and push to a branch."""
        await self._run(["git", "checkout", "-B", branch], cwd=repo_dir)
        await self._run(["git", "add", "-A"], cwd=repo_dir)
        await self._run(["git", "commit", "-m", message], cwd=repo_dir)
        logger.info("Pushing to branch: %s", branch)
        await self._run(
            ["git", "push", "-u", "origin", branch, "--force"], cwd=repo_dir
        )

    # ── Read operations ──

    async def get_issue_context(self, issue_number: int) -> dict:
        """Get full issue context including body, labels, and comments."""
        result = await self._run([
            "gh", "issue", "view", str(issue_number),
            "--repo", self.config.repo,
            "--json", "number,title,body,labels,comments",
        ])
        return json.loads(result)

    async def get_issue_body(self, issue_number: int) -> str:
        """Get the body of an issue."""
        return await self._run([
            "gh", "issue", "view", str(issue_number),
            "--repo", self.config.repo,
            "--json", "body",
            "--jq", ".body",
        ])

    async def get_pr_body(self, pr_number: int) -> str:
        """Get the body of a pull request."""
        return await self._run([
            "gh", "pr", "view", str(pr_number),
            "--repo", self.config.repo,
            "--json", "body",
            "--jq", ".body",
        ])

    async def get_pr_diff(self, pr_number: int) -> str:
        """Get the diff of a pull request."""
        return await self._run([
            "gh", "pr", "diff", str(pr_number),
            "--repo", self.config.repo,
        ])
