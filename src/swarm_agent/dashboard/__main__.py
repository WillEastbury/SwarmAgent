"""CLI entrypoint: python -m swarm_agent.dashboard"""

from __future__ import annotations

import argparse
import sys

from swarm_agent.dashboard.app import SwarmDashboard


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Swarm Dashboard — observe agent activity"
    )
    parser.add_argument("repo", help="GitHub repository (owner/repo)")
    parser.add_argument(
        "--watch", "-w",
        action="store_true",
        help="Continuously refresh (every 10s)",
    )
    parser.add_argument(
        "--interval", "-i",
        type=int,
        default=10,
        help="Refresh interval in seconds (default: 10)",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["table", "json"],
        default="table",
        help="Output format (default: table)",
    )
    args = parser.parse_args()

    dashboard = SwarmDashboard(args.repo)

    try:
        if args.watch:
            dashboard.watch(interval=args.interval, fmt=args.format)
        else:
            dashboard.show(fmt=args.format)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
