# SwarmAgent

Autonomous AI agent that runs in a container, adopts a configurable persona, and reasons over GitHub repositories as part of a swarm.

See [.github/copilot-instructions.md](.github/copilot-instructions.md) for architecture and usage details.

## Quick Start

```bash
pip install -e ".[dev]"
python -m swarm_agent
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes | OpenAI API key |
| `GITHUB_TOKEN` | Yes | PAT for repo access and `gh` CLI |
| `SWARM_PERSONA` | Yes | Persona prompt name |
| `SWARM_TASK` | Yes | Task instruction |
| `SWARM_REPO` | Yes | Target repo (owner/name) |
| `SWARM_PR_NUMBER` | No | PR number to operate on |
| `SWARM_ISSUE_NUMBER` | No | Issue number to operate on |
