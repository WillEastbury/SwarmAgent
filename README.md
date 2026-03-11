# SwarmAgent

Autonomous AI agent for the [swarmymcswarmface](https://github.com/WillEastbury/swarmymcswarmface) swarm. Runs in a container, adopts a configurable persona, discovers unclaimed GitHub issues, and takes action — scaled by KEDA.

See [.github/copilot-instructions.md](.github/copilot-instructions.md) for architecture and detailed usage.

## Quick Start

```bash
pip install -e ".[dev]"
python -m swarm_agent
```

## How It Works

1. KEDA external scaler detects new GitHub issues → scales up `swarm-agent` Deployment
2. Agent pod discovers an unclaimed issue (no `review:started:<persona>` label)
3. Claims the issue, processes it via OpenAI, posts results as comments
4. Signals `review:complete:<persona>` and exits cleanly

## Observability

```bash
# Structured JSON logs
SWARM_LOG_FORMAT=json python -m swarm_agent

# OpenTelemetry tracing (install extras first)
pip install -e ".[otel]"
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317 python -m swarm_agent

# Swarm dashboard — see all agents in real-time
python -m swarm_agent.dashboard owner/repo --watch
```

Each agent posts a timing breakdown comment on the issue/PR when it completes.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes | OpenAI API key |
| `GITHUB_TOKEN` | Yes | PAT for repo access and `gh` CLI |
| `SWARM_PERSONA` | Yes | Persona ID (e.g., `backend-engineer`) |
| `SWARM_REPO` | Yes | Target repo (owner/name) |
| `SWARM_TASK` | No | Instruction template name (default: `review`) |
| `SWARM_PR_NUMBER` | No | Specific PR to operate on |
| `SWARM_ISSUE_NUMBER` | No | Specific issue to operate on |
| `SWARM_PERSONAS_FILE` | No | Path to `full-lifecycle-personas.json` |
| `SWARM_LOG_FORMAT` | No | `text` (default) or `json` for structured logs |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | No | OTLP endpoint for distributed tracing |
