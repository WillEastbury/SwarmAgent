"""Main agent loop: discover work → claim → reason → act → signal complete → exit."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from swarm_agent.config import Config
from swarm_agent.github_client import GitHubClient
from swarm_agent.llm import LLMClient
from swarm_agent.persona import PromptComposer

logger = logging.getLogger(__name__)

# Phases where the persona is expected to produce code changes
CODE_PHASES = frozenset({
    "implementation", "secure-sdlc", "testing", "delivery",
})

# Phases where the persona reviews PRs rather than working on issues
PR_REVIEW_PHASES = frozenset({
    "quality-gate",
})

# Regex to extract file blocks from LLM response: ```file:path/to/file\n...\n```
FILE_BLOCK_RE = re.compile(
    r"```file:([^\n]+)\n(.*?)```",
    re.DOTALL,
)


def parse_file_blocks(response: str) -> list[tuple[str, str]]:
    """Extract (filepath, content) pairs from LLM response.

    Expected format:
        ```file:path/to/file.py
        <file contents>
        ```
    """
    return [
        (path.strip(), content)
        for path, content in FILE_BLOCK_RE.findall(response)
    ]


def extract_summary(response: str) -> str:
    """Extract the SUMMARY section from an LLM response, or fall back to first line."""
    match = re.search(
        r"(?:^|\n)#+\s*SUMMARY[:\s]*\n(.*?)(?:\n#|\Z)",
        response,
        re.DOTALL | re.IGNORECASE,
    )
    if match:
        return match.group(1).strip().split("\n")[0]
    # Fall back to first non-empty line outside code blocks
    in_fence = False
    for line in response.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and stripped:
            return stripped[:120]
    return "Agent changes"


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
        """Execute the full agent lifecycle."""
        try:
            config = self.config

            if config.discover_work:
                config = await self._discover_and_claim()
                if config is None:
                    logger.info("No unclaimed work found — exiting cleanly")
                    return
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
        """Find and claim unclaimed work (issues or PRs).

        PR-review personas look for PRs first. All others look for issues.
        """
        persona = self.config.persona
        phase = self.composer.get_persona_phase(persona)
        logger.info(
            "Discovering work: persona=%s, phase=%s", persona, phase
        )

        if phase in PR_REVIEW_PHASES:
            pr_number = await self.github.find_unclaimed_pr(persona)
            if pr_number is not None:
                if await self.github.claim_pr(pr_number, persona):
                    logger.info("Claimed PR #%d", pr_number)
                    return self.config.with_pr(pr_number)

        # All other personas (or fallback) discover issues
        issue_number = await self.github.find_unclaimed_issue(persona)
        if issue_number is None:
            # Last resort: try PRs even for non-review personas
            if phase not in PR_REVIEW_PHASES:
                pr_number = await self.github.find_unclaimed_pr(persona)
                if pr_number is not None:
                    if await self.github.claim_pr(pr_number, persona):
                        logger.info("Claimed PR #%d (fallback)", pr_number)
                        return self.config.with_pr(pr_number)
            return None

        if not await self.github.claim_issue(issue_number, persona):
            return None

        logger.info("Claimed issue #%d", issue_number)
        return self.config.with_issue(issue_number)

    def _build_system_prompt(self) -> str:
        """Compose system prompt — prefers JSON personas if loaded."""
        if self.config.personas_file and self.config.persona in (
            self.composer.get_persona_ids()
        ):
            issue_ctx = self._build_issue_context_for_prompt()
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

    def _build_issue_context_for_prompt(self) -> dict | None:
        """Build issue context dict for system prompt injection."""
        if self.config.issue_number is not None:
            return {
                "number": self.config.issue_number,
                "type": "issue",
            }
        if self.config.pr_number is not None:
            return {
                "number": self.config.pr_number,
                "type": "pr",
            }
        return None

    async def _gather_context(self, repo_dir: Path) -> str:
        """Gather context about the target for the LLM."""
        parts: list[str] = []
        parts.append(f"Repository: {self.config.repo}")

        if self.config.pr_number is not None:
            ctx = await self.github.get_pr_context(self.config.pr_number)
            parts.append(
                f"PR #{ctx['number']}: {ctx.get('title', '')}"
            )
            parts.append(f"Body:\n{ctx.get('body', '(empty)')}")
            labels = [lb["name"] for lb in ctx.get("labels", [])]
            if labels:
                parts.append(f"Labels: {', '.join(labels)}")
            if ctx.get("isDraft"):
                parts.append("Status: DRAFT")
            reviews = ctx.get("reviews", [])
            if reviews:
                review_text = "\n".join(
                    f"- {r.get('author', {}).get('login', '?')}: "
                    f"{r.get('state', '?')}"
                    for r in reviews[-5:]
                )
                parts.append(f"Reviews:\n{review_text}")
            diff = await self.github.get_pr_diff(self.config.pr_number)
            parts.append(f"Diff:\n{diff}")
        elif self.config.issue_number is not None:
            ctx = await self.github.get_issue_context(
                self.config.issue_number
            )
            parts.append(
                f"Issue #{ctx['number']}: {ctx.get('title', '')}"
            )
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
        """Parse LLM response and take appropriate action.

        For code personas: extract file blocks, write files, commit, push, create PR.
        For all personas: post the response as a comment.
        """
        logger.info("Agent response length: %d chars", len(response))

        file_blocks = parse_file_blocks(response)
        phase = self.composer.get_persona_phase(self.config.persona)

        if file_blocks and phase in CODE_PHASES:
            await self._apply_code_changes(
                response, file_blocks, repo_dir
            )
        else:
            await self.github.add_comment(
                f"🤖 **{self.config.persona}** agent response:\n\n{response}"
            )

    async def _apply_code_changes(
        self,
        response: str,
        file_blocks: list[tuple[str, str]],
        repo_dir: Path,
    ) -> None:
        """Write file changes, commit, push, and create a PR."""
        for filepath, content in file_blocks:
            target = repo_dir / filepath
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            logger.info("Wrote file: %s", filepath)

        if not await self.github.has_changes(repo_dir):
            logger.info("No actual changes after writing files — commenting only")
            await self.github.add_comment(
                f"🤖 **{self.config.persona}** reviewed but no changes needed."
            )
            return

        summary = extract_summary(response)
        ref = self.config.target_ref
        branch = f"swarm/{self.config.persona}/{ref}"

        await self.github.commit_and_push(repo_dir, summary, branch)

        pr_body = (
            f"🤖 Automated changes by **{self.config.persona}** agent.\n\n"
            f"Related to #{ref}\n\n"
            f"---\n\n{response}"
        )
        pr_url = await self.github.create_pr(
            title=f"[{self.config.persona}] {summary}",
            body=pr_body,
            branch=branch,
        )
        logger.info("Created PR: %s", pr_url)

        await self.github.add_comment(
            f"🤖 **{self.config.persona}** proposed changes in {pr_url}\n\n"
            f"Files modified: {', '.join(fp for fp, _ in file_blocks)}"
        )
