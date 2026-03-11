"""Persona and instruction prompt loading and composition."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, TemplateNotFound

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


class PromptComposer:
    """Loads and composes persona + instruction prompts into a system prompt."""

    def __init__(self, prompts_dir: Path | None = None) -> None:
        self.prompts_dir = prompts_dir or PROMPTS_DIR
        self.env = Environment(
            loader=FileSystemLoader(str(self.prompts_dir)),
            keep_trailing_newline=True,
        )
        self._personas_cache: dict[str, dict[str, Any]] = {}

    def load_persona(self, name: str, **kwargs: str) -> str:
        """Load a persona prompt template by name."""
        return self._load_template(f"persona/{name}.md", **kwargs)

    def load_instruction(self, name: str, **kwargs: str) -> str:
        """Load an instruction prompt template by name."""
        return self._load_template(f"instructions/{name}.md", **kwargs)

    def compose(self, persona_name: str, instruction_name: str, **kwargs: str) -> str:
        """Compose a full system prompt from persona + instruction layers."""
        persona = self.load_persona(persona_name, **kwargs)
        instruction = self.load_instruction(instruction_name, **kwargs)
        return f"{persona}\n\n---\n\n{instruction}"

    # ── swarmymcswarmface JSON persona support ──

    def load_personas_json(self, filepath: str | Path) -> None:
        """Load personas from a swarmymcswarmface full-lifecycle-personas.json file."""
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Personas file not found: {path}")

        data = json.loads(path.read_text())
        template = data.get("agent_instruction_template", {})

        for persona in data.get("personas", []):
            persona_id = persona["id"]
            self._personas_cache[persona_id] = {
                "prompt": persona.get("prompt", ""),
                "goal": persona.get("goal", ""),
                "phase": persona.get("phase", ""),
                "agent_instructions": persona.get("agent_instructions", {}),
                "operating_rules": template.get("operating_rules", []),
                "output_contract": template.get("output_contract", {}),
            }

        logger.info("Loaded %d personas from %s", len(self._personas_cache), path)

    def get_persona_ids(self) -> list[str]:
        """Return list of loaded persona IDs from JSON."""
        return list(self._personas_cache.keys())

    def compose_from_json(
        self, persona_id: str, issue_context: dict | None = None
    ) -> str:
        """Build a system prompt from a JSON-loaded persona and issue context."""
        if persona_id not in self._personas_cache:
            raise KeyError(
                f"Persona '{persona_id}' not found. "
                f"Available: {', '.join(self._personas_cache.keys())}"
            )

        p = self._personas_cache[persona_id]
        instructions = p.get("agent_instructions", {})
        phase = p["phase"]

        parts = [
            p["prompt"],
            "",
            f"GOAL: {p['goal']}",
            f"PHASE: {phase}",
            "",
            "OPERATING RULES:",
            *[f"- {rule}" for rule in p.get("operating_rules", [])],
        ]

        if instructions.get("workflow_steps"):
            parts.append("")
            parts.append("WORKFLOW STEPS:")
            for step in instructions["workflow_steps"]:
                parts.append(f"- {step}")

        if instructions.get("inputs"):
            parts.append("")
            parts.append("EXPECTED INPUTS:")
            for inp in instructions["inputs"]:
                parts.append(f"- {inp}")

        if instructions.get("outputs"):
            parts.append("")
            parts.append("EXPECTED OUTPUTS:")
            for out in instructions["outputs"]:
                parts.append(f"- {out}")

        contract = p.get("output_contract", {})
        if contract:
            parts.append("")
            parts.append("OUTPUT CONTRACT:")
            for key, desc in contract.items():
                parts.append(f"- {key}: {desc}")

        # Inject issue/PR context into the prompt
        if issue_context:
            parts.append("")
            parts.append("CURRENT WORK ITEM:")
            if issue_context.get("number"):
                parts.append(f"- Number: #{issue_context['number']}")
            if issue_context.get("title"):
                parts.append(f"- Title: {issue_context['title']}")
            if issue_context.get("labels"):
                parts.append(f"- Labels: {', '.join(issue_context['labels'])}")
            if issue_context.get("type"):
                parts.append(f"- Type: {issue_context['type']}")

        # Add response format instructions based on persona phase
        parts.append("")
        parts.append("RESPONSE FORMAT:")
        if phase in (
            "implementation", "secure-sdlc", "testing", "delivery"
        ):
            parts.append(
                "You may propose code changes. When you do, use this format "
                "for each file you want to create or modify:"
            )
            parts.append("")
            parts.append("```file:path/to/file.py")
            parts.append("<full file contents>")
            parts.append("```")
            parts.append("")
            parts.append(
                "Include a SUMMARY section at the end with a one-line "
                "commit message and a brief explanation."
            )
        else:
            parts.append(
                "Provide your analysis as structured text. Do NOT propose "
                "code changes unless explicitly asked."
            )

        return "\n".join(parts)

    def get_persona_phase(self, persona_id: str) -> str | None:
        """Return the phase for a loaded JSON persona, or None."""
        p = self._personas_cache.get(persona_id)
        return p["phase"] if p else None

    def _load_template(self, template_path: str, **kwargs: str) -> str:
        try:
            template = self.env.get_template(template_path)
            return template.render(**kwargs)
        except TemplateNotFound:
            raise FileNotFoundError(
                f"Prompt template not found: {self.prompts_dir / template_path}"
            )
