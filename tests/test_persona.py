"""Tests for persona/prompt composition."""

import pytest

from swarm_agent.persona import PromptComposer


@pytest.fixture()
def composer(tmp_path):
    """Create a composer with test prompt templates."""
    persona_dir = tmp_path / "persona"
    persona_dir.mkdir()
    (persona_dir / "tester.md").write_text("You are {{ persona_name }}. Repo: {{ repo }}")

    instr_dir = tmp_path / "instructions"
    instr_dir.mkdir()
    (instr_dir / "check.md").write_text("Check {{ target_type }} #{{ target_ref }}")

    return PromptComposer(prompts_dir=tmp_path)


class TestPromptComposer:
    def test_load_persona(self, composer):
        result = composer.load_persona("tester", persona_name="Bot", repo="org/repo")
        assert "Bot" in result
        assert "org/repo" in result

    def test_load_instruction(self, composer):
        result = composer.load_instruction("check", target_type="pr", target_ref="42")
        assert "pr" in result
        assert "42" in result

    def test_compose(self, composer):
        result = composer.compose(
            "tester", "check",
            repo="org/repo",
            target_type="issue", target_ref="7",
        )
        assert "org/repo" in result
        assert "issue" in result
        assert "---" in result  # separator between persona and instructions

    def test_missing_template(self, composer):
        with pytest.raises(FileNotFoundError):
            composer.load_persona("nonexistent")
