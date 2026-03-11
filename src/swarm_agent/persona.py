"""Persona and instruction prompt loading and composition."""

from __future__ import annotations

import logging
from pathlib import Path

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

    def _load_template(self, template_path: str, **kwargs: str) -> str:
        try:
            template = self.env.get_template(template_path)
            return template.render(**kwargs)
        except TemplateNotFound:
            raise FileNotFoundError(
                f"Prompt template not found: {self.prompts_dir / template_path}"
            )
