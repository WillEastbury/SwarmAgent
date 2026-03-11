"""Main agent loop: discover work → claim → reason → act → signal complete → exit."""

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

        if config.personas_file:
            self.composer.load_personas_json(config.personas_file)

    async def run(self) -> None:
        """Execute the full agent lifecycle.

        When KEDA scales up this pod, no specific issue is assigned.
        The agent discovers unclaimed work, claims it, processes it,
        signals completion, and exits cleanly.
        """
        try:
            config = self.config

            if config.discover_work:
                config = await self._discover_and_claim()
                if config is None:
                    logger.info("No unclaimed work found — exiting cleanly")
                    return
                # Rebind clients to the discovered target
                self.config = config
                self.github = GitHubClient(config)

            logger.info(
                "Agent starting: persona=%s, repo=%s, target=%s #%s",
                config.persona,
                config.repo,
                config.target_type,
                config.target_ref,
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

    async def _discover_and_claim(self) -> Config | None:
        """Find and claim an unclaimed issue. Returns updated Config or None."""
        logger.info("Discovering unclaimed work for persona=%s", self.config.persona)
        issue_number = await self.github.find_unclaimed_issue(self.config.persona)
        if issue_number is None:
            return None

        claimed = await self.github.claim_issue(issue_number, self.config.persona)
        if not claimed:
            return None

        logger.info("Claimed issue #%d", issue_number)
        return self.config.with_issue(issue_number)

    def _build_system_prompt(self) -> str:
        """Compose system prompt — prefers JSON personas if loaded."""
        if self.config.personas_file and self.config.persona in (
            self.composer.get_persona_ids()
        ):
            issue_ctx = None
            if self.config.issue_number is not None:
                issue_ctx = {"number": self.config.issue_number}
            return self.composer.compose_from_json(
                self.config.persona, issue_context=issue_ctx
            )

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
            ctx = await self.github.get_issue_context(self.config.issue_number)
            parts.append(f"Issue #{ctx['number']}: {ctx.get('title', '')}")
            parts.append(f"Body:\n{ctx.get('body', '(empty)')}")
            labels = [lb["name"] for lb in ctx.get("labels", [])]
            if labels:
                parts.append(f"Labels: {', '.join(labels)}")
            comments = ctx.get("comments", [])
            if comments:
                recent = comments[-8:]
                comment_text = "\n".join(
                    f"- {c.get('author', {}).get('login', '?')}: "
                    f"{(c.get('body', '') or '')[:1200]}"
                    for c in recent
                )
                parts.append(f"Recent comments:\n{comment_text}")

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

        Posts the response as a comment on the target PR/issue.
        Future: parse structured responses for file edits, label changes, etc.
        """
        logger.info("Agent response length: %d chars", len(response))
        await self.github.add_comment(
            f"🤖 **{self.config.persona}** agent response:\n\n{response}"
        )
