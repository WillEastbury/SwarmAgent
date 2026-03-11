"""Swarm Dashboard — queries GitHub to show real-time agent status."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass

LABEL_RE = re.compile(r"^review:(started|complete):(.+)$")


@dataclass
class AgentStatus:
    """Status of a single agent persona on a specific work item."""

    persona: str
    target_type: str  # "issue" or "pr"
    target_number: int
    target_title: str
    state: str  # "active" or "complete"


@dataclass
class SwarmSummary:
    """Aggregate summary of swarm activity."""

    active: list[AgentStatus]
    completed: list[AgentStatus]
    unclaimed_issues: int
    unclaimed_prs: int
    total_issues: int
    total_prs: int


class SwarmDashboard:
    """Queries GitHub via gh CLI to show swarm agent status."""

    def __init__(self, repo: str) -> None:
        self.repo = repo
        self._env = {**os.environ, "GH_TOKEN": os.environ.get("GITHUB_TOKEN", "")}

    def _run_gh(self, args: list[str]) -> str:
        """Run a gh CLI command and return stdout."""
        cmd = ["gh", *args, "--repo", self.repo]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=self._env,
        )
        if result.returncode != 0:
            raise RuntimeError(f"gh command failed: {' '.join(cmd)}\n{result.stderr}")
        return result.stdout.strip()

    def gather(self) -> SwarmSummary:
        """Query GitHub for current swarm status."""
        issues_raw = self._run_gh([
            "issue", "list", "--state", "open",
            "--json", "number,title,labels", "--limit", "100",
        ])
        prs_raw = self._run_gh([
            "pr", "list", "--state", "open",
            "--json", "number,title,labels", "--limit", "100",
        ])

        issues = json.loads(issues_raw) if issues_raw else []
        prs = json.loads(prs_raw) if prs_raw else []

        active: list[AgentStatus] = []
        completed: list[AgentStatus] = []
        unclaimed_issues = 0
        unclaimed_prs = 0

        for issue in issues:
            statuses = self._extract_statuses(issue, "issue")
            if not statuses:
                unclaimed_issues += 1
            for s in statuses:
                if s.state == "active":
                    active.append(s)
                else:
                    completed.append(s)

        for pr in prs:
            statuses = self._extract_statuses(pr, "pr")
            if not statuses:
                unclaimed_prs += 1
            for s in statuses:
                if s.state == "active":
                    active.append(s)
                else:
                    completed.append(s)

        return SwarmSummary(
            active=active,
            completed=completed,
            unclaimed_issues=unclaimed_issues,
            unclaimed_prs=unclaimed_prs,
            total_issues=len(issues),
            total_prs=len(prs),
        )

    def _extract_statuses(
        self, item: dict, target_type: str
    ) -> list[AgentStatus]:
        """Extract agent statuses from an item's labels."""
        labels = [lb["name"] for lb in item.get("labels", [])]
        statuses: list[AgentStatus] = []
        personas_started: set[str] = set()
        personas_complete: set[str] = set()

        for label in labels:
            m = LABEL_RE.match(label)
            if m:
                action, persona = m.group(1), m.group(2)
                if action == "started":
                    personas_started.add(persona)
                else:
                    personas_complete.add(persona)

        for persona in personas_complete:
            statuses.append(AgentStatus(
                persona=persona,
                target_type=target_type,
                target_number=item["number"],
                target_title=item.get("title", ""),
                state="complete",
            ))

        for persona in personas_started - personas_complete:
            statuses.append(AgentStatus(
                persona=persona,
                target_type=target_type,
                target_number=item["number"],
                target_title=item.get("title", ""),
                state="active",
            ))

        return statuses

    def show(self, fmt: str = "table") -> None:
        """Print the current swarm status."""
        summary = self.gather()
        if fmt == "json":
            self._print_json(summary)
        else:
            self._print_table(summary)

    def watch(self, interval: int = 10, fmt: str = "table") -> None:
        """Continuously refresh and display swarm status."""
        while True:
            # Clear screen
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.write(
                f"🐝 Swarm Dashboard — {self.repo} "
                f"(refreshing every {interval}s, Ctrl+C to quit)\n\n"
            )
            try:
                self.show(fmt=fmt)
            except RuntimeError as e:
                sys.stdout.write(f"⚠️  Error: {e}\n")
            sys.stdout.flush()
            time.sleep(interval)

    def _print_table(self, summary: SwarmSummary) -> None:
        """Print a human-readable table."""
        # Overview
        print(f"📊 Open: {summary.total_issues} issues, {summary.total_prs} PRs")
        print(
            f"🔓 Unclaimed: {summary.unclaimed_issues} issues, "
            f"{summary.unclaimed_prs} PRs"
        )
        print()

        # Active agents
        if summary.active:
            print("🟢 ACTIVE AGENTS")
            print(f"{'Persona':<25} {'Type':<6} {'#':<6} {'Title'}")
            print("─" * 70)
            for s in summary.active:
                title = s.target_title[:35] if s.target_title else ""
                print(f"{s.persona:<25} {s.target_type:<6} {s.target_number:<6} {title}")
        else:
            print("🟢 No active agents")
        print()

        # Completed
        if summary.completed:
            print(f"✅ COMPLETED ({len(summary.completed)} reviews)")
            print(f"{'Persona':<25} {'Type':<6} {'#':<6} {'Title'}")
            print("─" * 70)
            for s in summary.completed:
                title = s.target_title[:35] if s.target_title else ""
                print(f"{s.persona:<25} {s.target_type:<6} {s.target_number:<6} {title}")
        else:
            print("✅ No completed reviews")

    def _print_json(self, summary: SwarmSummary) -> None:
        """Print JSON output."""
        data = {
            "repo": self.repo,
            "overview": {
                "total_issues": summary.total_issues,
                "total_prs": summary.total_prs,
                "unclaimed_issues": summary.unclaimed_issues,
                "unclaimed_prs": summary.unclaimed_prs,
            },
            "active": [
                {
                    "persona": s.persona,
                    "target_type": s.target_type,
                    "target_number": s.target_number,
                    "target_title": s.target_title,
                }
                for s in summary.active
            ],
            "completed": [
                {
                    "persona": s.persona,
                    "target_type": s.target_type,
                    "target_number": s.target_number,
                    "target_title": s.target_title,
                }
                for s in summary.completed
            ],
        }
        print(json.dumps(data, indent=2))
