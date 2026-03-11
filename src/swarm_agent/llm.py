"""OpenAI REST API client using httpx — no SDK dependency."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from swarm_agent.config import Config

logger = logging.getLogger(__name__)


class LLMClient:
    """Async client for OpenAI chat completions via raw REST API."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._client = httpx.AsyncClient(
            base_url=config.openai_base_url,
            headers={
                "Authorization": f"Bearer {config.openai_api_key}",
                "Content-Type": "application/json",
            },
            timeout=120.0,
        )

    async def chat(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        """Send a chat completion request and return the assistant's response text."""
        payload: dict[str, Any] = {
            "model": self.config.openai_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        logger.info(
            "LLM request: model=%s, prompt_len=%d",
            self.config.openai_model,
            len(user_message),
        )
        response = await self._client.post("/chat/completions", json=payload)
        response.raise_for_status()

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        logger.info("LLM response: tokens=%s", data.get("usage", {}).get("total_tokens", "?"))
        return content

    async def close(self) -> None:
        await self._client.aclose()
