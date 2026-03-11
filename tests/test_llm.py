"""Tests for LLM client."""

import httpx
import pytest
import respx

from swarm_agent.config import Config
from swarm_agent.llm import LLMClient


@pytest.fixture()
def config():
    return Config(
        openai_api_key="sk-test",
        github_token="ghp_test",
        persona="reviewer",
        task="review",
        repo="org/repo",
    )


@pytest.fixture()
def llm(config):
    return LLMClient(config)


@respx.mock
@pytest.mark.asyncio
async def test_chat_success(llm):
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "Looks good!"}}],
                "usage": {"total_tokens": 100},
            },
        )
    )
    result = await llm.chat("You are a reviewer.", "Review this code.")
    assert result == "Looks good!"
    await llm.close()


@respx.mock
@pytest.mark.asyncio
async def test_chat_raises_on_error(llm):
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(500, json={"error": "server error"})
    )
    with pytest.raises(httpx.HTTPStatusError):
        await llm.chat("system", "user")
    await llm.close()
