# Copilot Instructions — SwarmAgent

## What This Is

SwarmAgent is an autonomous AI agent that runs in a container as part of the [swarmymcswarmface](https://github.com/WillEastbury/swarmymcswarmface) swarm. It adopts a configurable persona, discovers unclaimed work on GitHub, reasons over the repository, and takes actions (comments, labels, code changes). It calls the OpenAI API for inference and uses the `gh` CLI for all GitHub operations.

**Key constraints:**
- The agent may commit to a PR and push code, but must **never merge** code.
- Behavior is driven by a **persona** (from swarmymcswarmface's `full-lifecycle-personas.json` or local Jinja2 templates).
- It runs unattended in a container — KEDA scales the Deployment from 0 when GitHub issues arrive.
- When no specific issue/PR is assigned, the agent **discovers unclaimed work** automatically.

## Architecture

```
SwarmAgent/
├── src/swarm_agent/
│   ├── agent.py          # Main loop: discover → claim → reason → act → complete → exit
│   ├── persona.py         # Prompt loading (Jinja2 templates + swarmymcswarmface JSON)
│   ├── llm.py             # OpenAI REST API client (no SDK — raw HTTP via httpx)
│   ├── github_client.py   # GitHub operations via `gh` CLI (labels, comments, PRs, work discovery)
│   ├── config.py          # Environment-based configuration
│   └── idea_factory/      # Web UI for submitting ideas as GitHub issues
│       ├── app.py         # Flask app with basic auth
│       └── templates/     # HTML templates
├── prompts/
│   ├── persona/           # Jinja2 persona templates (fallback)
│   └── instructions/      # Jinja2 instruction templates (fallback)
├── k8s/
│   ├── deployment.yaml    # SwarmAgent Deployment + ScaledObject
│   └── idea-factory.yaml  # Idea Factory Deployment + Service
├── tests/
├── Dockerfile                 # SwarmAgent container
├── idea-factory.Dockerfile    # Idea Factory container
├── requirements.txt
└── pyproject.toml
```

## KEDA Integration

SwarmAgent is the **scale target** for the swarmymcswarmface KEDA external scaler:

1. GitHub issue webhook → KEDA external scaler increments `pendingCount`
2. KEDA scales up the `swarm-agent` Deployment (replicas: 0 → N)
3. Each pod boots, **discovers** an unclaimed open issue (no `review:started:<persona>` label)
4. Pod **claims** the issue by adding `review:started:<persona>` label
5. Pod processes the issue (LLM reasoning + GitHub actions)
6. Pod adds `review:complete:<persona>` label and exits cleanly (code 0)
7. KEDA scales the Deployment back down

The ScaledObject in `k8s/deployment.yaml` points to `github-issue-external-scaler.keda.svc.cluster.local:9090`.

## Tech Stack & Conventions

- **Language:** Python 3.12+
- **HTTP client:** `httpx` for async OpenAI REST API calls (no SDK)
- **GitHub integration:** `gh` CLI for all GitHub operations. Repos cloned via PAT over HTTPS.
- **Personas:** Supports swarmymcswarmface `full-lifecycle-personas.json` format (30 personas with id, phase, goal, prompt, agent_instructions). Falls back to local Jinja2 templates in `prompts/`.
- **Configuration:** All config via environment variables — no config files at runtime.
- **Containerization:** Single-stage Dockerfile with `gh` CLI installed. Entrypoint: `python -m swarm_agent`.

## Build & Run

```bash
# Install dependencies
pip install -e ".[dev]"

# Run the agent locally (needs env vars set)
python -m swarm_agent

# Run tests
pytest

# Run a single test
pytest tests/test_persona.py::TestJsonPersonas::test_compose_from_json

# Lint
ruff check src/ tests/
ruff format --check src/ tests/

# Build container
docker build -t swarm-agent .
```

## Key Patterns

### Work Discovery
When KEDA scales the pod up without a specific `SWARM_ISSUE_NUMBER` or `SWARM_PR_NUMBER`, the agent:
1. Queries open issues (or PRs for `quality-gate` phase personas) via `gh`
2. Filters for items without `review:started:<persona>` or `review:complete:<persona>` labels
3. **Claims** the item using a check-after-label pattern (label → wait → verify) to prevent duplicate claims across pods
4. Falls back to PRs if no issues found, or vice versa
5. If no unclaimed work exists, exits cleanly (code 0) so KEDA can scale down

### Persona-Aware Behavior
The agent's behavior changes based on the persona's **phase** from `full-lifecycle-personas.json`:

- **Code phases** (`implementation`, `secure-sdlc`, `testing`, `delivery`): The LLM is instructed to produce `\`\`\`file:path\`\`\`` blocks. The agent parses these, writes files, commits, pushes to a branch, and creates a PR.
- **Non-code phases** (`planning`, `ideation`, `architecture`, etc.): The agent posts analysis as a comment — no code changes.
- **PR review phases** (`quality-gate`): The agent discovers open PRs instead of issues.

### Response Parsing
The agent parses structured LLM responses:
- **File blocks** (`\`\`\`file:path/to/file.py\n...\`\`\``) — extracted and written to the repo
- **SUMMARY section** — used as the commit message
- If file blocks are present and the persona is a code phase, the agent: writes files → commits → pushes → creates PR → comments with link

### Persona Loading
Two modes:
1. **swarmymcswarmface JSON** — set `SWARM_PERSONAS_FILE` to a `full-lifecycle-personas.json` path. The agent loads personas by `id` and builds system prompts with goal, prompt, agent_instructions, operating_rules, output_contract, and **issue/PR context**.
2. **Jinja2 templates** — fallback. Templates in `prompts/persona/` and `prompts/instructions/`.

### "Good Enough" Signal
Signaling is done via **GitHub labels** on the PR or issue:
- **`review:started:<persona>`** — applied when the agent begins working
- **`review:complete:<persona>`** — applied when the agent is satisfied and shutting down

Other agents in the swarm watch for these labels to coordinate.

### Agent Roles
Not all agents write code. The 30 swarmymcswarmface personas span ideation, design, architecture, implementation, testing, delivery, operations, and growth. Some personas focus on **issue refinement and prioritization** rather than code changes.

### Safety Rails
- Never merge PRs — only create/update them and add comments.
- All GitHub write operations are logged before execution.
- The agent fails loudly (raises exceptions) when API calls fail.

## Observability

### Structured Logging
Set `SWARM_LOG_FORMAT=json` for machine-parseable JSON logs. Each log entry includes timestamp, level, logger, message, and (for lifecycle events) an `event` object with stage, duration, persona, and metadata.

### OpenTelemetry Tracing
Set `OTEL_EXPORTER_OTLP_ENDPOINT` to enable distributed tracing. Spans are emitted for each lifecycle stage: `discover_work`, `clone_repo`, `gather_context`, `llm_reasoning`, `act_on_response`. Install the `otel` extras: `pip install swarm-agent[otel]`.

### Lifecycle Metrics
The agent automatically posts a timing breakdown as a collapsible comment on the issue/PR when it completes, showing duration for each stage (discovery, clone, context gathering, LLM reasoning, action).

### Swarm Dashboard
A CLI tool to view real-time swarm status across all agents:

```bash
# One-shot status
python -m swarm_agent.dashboard owner/repo

# Watch mode (refreshes every 10s)
python -m swarm_agent.dashboard owner/repo --watch

# JSON output (for scripting)
python -m swarm_agent.dashboard owner/repo --format json
```

Shows active agents, completed reviews, unclaimed issues/PRs, and per-persona status by reading `review:started:*` and `review:complete:*` labels.

## Idea Factory

A minimal Flask web app (`src/swarm_agent/idea_factory/`) behind HTTP basic auth. It presents a single text box where users submit ideas, which are created as GitHub issues with the `idea` label. The PM persona in the swarm then picks up and evaluates these issues.

```bash
# Run locally
IDEA_FACTORY_USERNAME=admin IDEA_FACTORY_PASSWORD=secret \
  SWARM_REPO=owner/repo GITHUB_TOKEN=ghp_xxx \
  python -m swarm_agent.idea_factory

# Build container
docker build -f idea-factory.Dockerfile -t idea-factory .
```

Deployed via `k8s/idea-factory.yaml` (Deployment + Service + Secrets).

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes | OpenAI API key for inference |
| `GITHUB_TOKEN` | Yes | PAT for cloning repos and authenticating `gh` CLI |
| `SWARM_PERSONA` | Yes | Persona ID (e.g., `backend-engineer`, `qa-lead`, `reviewer-agent`) |
| `SWARM_REPO` | Yes | Target GitHub repo (owner/name) |
| `SWARM_TASK` | No | Instruction template name (default: `review`) |
| `SWARM_PR_NUMBER` | No | PR number to operate on — disables work discovery |
| `SWARM_ISSUE_NUMBER` | No | Issue number to operate on — disables work discovery |
| `SWARM_PERSONAS_FILE` | No | Path to swarmymcswarmface `full-lifecycle-personas.json` |
| `OPENAI_MODEL` | No | OpenAI model (default: `gpt-4o`) |
| `OPENAI_BASE_URL` | No | OpenAI API base URL |
| `SWARM_LOG_FORMAT` | No | `text` (default) or `json` for structured JSON logging |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | No | OTLP endpoint for OpenTelemetry tracing (e.g., `http://otel-collector:4317`) |

### Idea Factory only

| Variable | Required | Description |
|---|---|---|
| `IDEA_FACTORY_USERNAME` | Yes | Basic auth username |
| `IDEA_FACTORY_PASSWORD` | Yes | Basic auth password |
| `IDEA_FACTORY_SECRET_KEY` | No | Flask secret key (auto-generated if unset) |
| `GITHUB_TOKEN` | Yes | PAT for creating issues |
| `SWARM_REPO` | Yes | Target repo for issue creation |
