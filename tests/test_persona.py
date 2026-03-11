"""Tests for persona/prompt composition."""

import json

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


@pytest.fixture()
def personas_json(tmp_path):
    """Create a swarmymcswarmface-style personas JSON file."""
    data = {
        "version": "1.0",
        "agent_instruction_template": {
            "operating_rules": [
                "Stay within role scope.",
                "Escalate blockers early.",
            ],
            "output_contract": {
                "summary": "Short outcome.",
                "risks": "Top risks.",
            },
        },
        "personas": [
            {
                "id": "backend-engineer",
                "phase": "implementation",
                "goal": "Implement backend changes.",
                "prompt": "You are a backend engineer.",
                "agent_instructions": {
                    "inputs": ["issue body", "repo structure"],
                    "outputs": ["code changes", "test results"],
                    "workflow_steps": [
                        "analyze the issue",
                        "implement changes",
                        "run tests",
                    ],
                },
            },
            {
                "id": "qa-lead",
                "phase": "testing",
                "goal": "Ensure quality.",
                "prompt": "You are a QA lead.",
                "agent_instructions": {
                    "inputs": ["PR diff"],
                    "workflow_steps": ["review test coverage"],
                },
            },
        ],
    }
    filepath = tmp_path / "personas.json"
    filepath.write_text(json.dumps(data))
    return filepath


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
        assert "---" in result

    def test_missing_template(self, composer):
        with pytest.raises(FileNotFoundError):
            composer.load_persona("nonexistent")


class TestJsonPersonas:
    def test_load_personas_json(self, composer, personas_json):
        composer.load_personas_json(personas_json)
        ids = composer.get_persona_ids()
        assert "backend-engineer" in ids
        assert "qa-lead" in ids
        assert len(ids) == 2

    def test_compose_from_json(self, composer, personas_json):
        composer.load_personas_json(personas_json)
        result = composer.compose_from_json("backend-engineer")
        assert "You are a backend engineer." in result
        assert "GOAL: Implement backend changes." in result
        assert "PHASE: implementation" in result
        assert "Stay within role scope." in result
        assert "analyze the issue" in result
        assert "code changes" in result

    def test_compose_from_json_includes_output_contract(self, composer, personas_json):
        composer.load_personas_json(personas_json)
        result = composer.compose_from_json("qa-lead")
        assert "OUTPUT CONTRACT:" in result
        assert "summary:" in result

    def test_compose_from_json_unknown_persona(self, composer, personas_json):
        composer.load_personas_json(personas_json)
        with pytest.raises(KeyError, match="nonexistent"):
            composer.compose_from_json("nonexistent")

    def test_load_personas_json_missing_file(self, composer):
        with pytest.raises(FileNotFoundError):
            composer.load_personas_json("/nonexistent/path.json")
