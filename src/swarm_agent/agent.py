"""Main agent loop: init → signal started → reason → act → signal complete."""

from __future__ import annotations

import logging
from pathlib import Path

from swarm_agent.config import Config
from swarm_agent.github_client import GitHubClient
from swarm_agent.llm import LLMClient
from swarm_agent.persona import PromptComposer

logger = logging.getLogger(__name__)


class Agent:
    """Autonomous agent that reasons over a GitHub repo and takes action."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.llm = LLMClient(config)
        self.github = GitHubClient(config)
        self.composer = PromptComposer()

    async def run(self) -> None:
        """Execute the full agent lifecycle."""
        try:
            logger.info(
                "Agent starting: persona=%s, repo=%s, target=%s",
                self.config.persona,
                self.config.repo,
                self.config.target_type,
            )
            await self.github.signal_started()

            repo_dir = await self.github.clone_repo()
            context = await self._gather_context(repo_dir)
            system_prompt = self._build_system_prompt()

            response = await self.llm.chat(system_prompt, context)
            await self._act_on_response(response, repo_dir)

            await self.github.signal_complete()
            logger.info("Agent finished — signaled 'good enough'")
        finally:
            await self.llm.close()

    def _build_system_prompt(self) -> str:
        """Compose system prompt from persona + task instruction."""
        return self.composer.compose(
            self.config.persona,
            self.config.task,
            repo=self.config.repo,
            target_type=self.config.target_type,
            target_ref=self.config.target_ref,
        )

    async def _gather_context(self, repo_dir: Path) -> str:
        """Gather context about the target for the LLM."""
        parts: list[str] = []
        parts.append(f"Repository: {self.config.repo}")

        if self.config.pr_number is not None:
            body = await self.github.get_pr_body(self.config.pr_number)
            diff = await self.github.get_pr_diff(self.config.pr_number)
            parts.append(f"PR #{self.config.pr_number} body:\n{body}")
            parts.append(f"PR diff:\n{diff}")
        elif self.config.issue_number is not None:
            body = await self.github.get_issue_body(self.config.issue_number)
            parts.append(f"Issue #{self.config.issue_number} body:\n{body}")

        repo_files = self._list_repo_files(repo_dir)
        parts.append(f"Repository file listing:\n{repo_files}")

        return "\n\n---\n\n".join(parts)

    def _list_repo_files(self, repo_dir: Path, max_files: int = 200) -> str:
        """List files in the repo (excluding .git) for context."""
        files: list[str] = []
        for p in sorted(repo_dir.rglob("*")):
            if ".git" in p.parts:
                continue
            if p.is_file():
                rel = p.relative_to(repo_dir)
                files.append(str(rel))
                if len(files) >= max_files:
                    files.append(f"... (truncated at {max_files} files)")
                    break
        return "\n".join(files)

    async def _act_on_response(self, response: str, repo_dir: Path) -> None:
        """Take action based on the LLM response.

        For now, the agent posts the response as a comment.
        Future: parse structured responses for file edits, label changes, etc.
        """
        logger.info("Agent response length: %d chars", len(response))
        await self.github.add_comment(
            f"🤖 **{self.config.persona}** agent response:\n\n{response}"
        )
