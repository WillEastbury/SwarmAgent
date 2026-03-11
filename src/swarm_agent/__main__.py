"""Entrypoint: python -m swarm_agent"""

from __future__ import annotations

import asyncio
import logging
import sys

from swarm_agent.agent import Agent
from swarm_agent.config import Config


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    try:
        config = Config.from_env()
    except OSError as e:
        logging.error("Configuration error: %s", e)
        sys.exit(1)

    agent = Agent(config)
    asyncio.run(agent.run())


if __name__ == "__main__":
    main()
