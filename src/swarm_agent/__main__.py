"""Entrypoint: python -m swarm_agent"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from swarm_agent.agent import Agent
from swarm_agent.config import Config
from swarm_agent.telemetry import configure_logging


def main() -> None:
    log_format = os.environ.get("SWARM_LOG_FORMAT", "text")
    configure_logging(log_format)

    try:
        config = Config.from_env()
    except OSError as e:
        logging.error("Configuration error: %s", e)
        sys.exit(1)

    agent = Agent(config)
    asyncio.run(agent.run())
    # Exit 0 so KEDA can scale down the pod
    sys.exit(0)


if __name__ == "__main__":
    main()
