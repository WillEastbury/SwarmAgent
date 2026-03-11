# Copilot Instructions — SwarmAgent

## What This Is

SwarmAgent is an autonomous AI agent that runs in a container. It adopts a configurable persona, reasons over a GitHub repository, and takes actions (comments, tags, code changes) according to a given task. It calls the OpenAI API for inference and interacts with GitHub via its API.

**Key constraints:**
- The agent may commit to a PR and push code, but must **never merge** code.
- Behavior is driven by two prompts: a **persona prompt** (who the agent is) and an **instruction sub-prompt** (what to do).
- It runs unattended in a container — all configuration comes from environment variables and prompt files.

## Architecture

```
SwarmAgent/
├── src/
│   ├── agent.py          # Main agent loop: read task → reason → act
│   ├── persona.py         # Persona prompt loading and management
│   ├── llm.py             # OpenAI REST API client (no SDK — raw HTTP)
│   ├── github_client.py   # GitHub operations via `gh` CLI wrapper
│   └── config.py          # Environment-based configuration
├── prompts/
│   ├── persona/           # Persona prompt templates
│   └── instructions/      # Instruction sub-prompt templates
├── tests/
├── Dockerfile
├── requirements.txt
└── pyproject.toml
```

## Tech Stack & Conventions

- **Language:** Python 3.12+
- **HTTP client:** `httpx` for async calls to OpenAI and GitHub APIs
- **OpenAI integration:** Direct REST API calls (not the openai SDK). The API key is passed via `OPENAI_API_KEY` env var.
- **GitHub integration:** The agent clones/pulls repos using a PAT token via HTTPS (`https://<token>@github.com/owner/repo.git`) and uses the `gh` CLI (authenticated with the same PAT) for all GitHub operations — PRs, comments, tags, etc. No direct REST API calls to GitHub.
- **Configuration:** All config via environment variables — no config files at runtime.
- **Containerization:** Single-stage Dockerfile. The container runs `python -m swarm_agent` as its entrypoint.

## Build & Run

```bash
# Install dependencies
pip install -e ".[dev]"

# Run the agent locally
python -m swarm_agent

# Run tests
pytest

# Run a single test
pytest tests/test_llm.py::test_api_call

# Lint
ruff check src/ tests/
ruff format --check src/ tests/

# Build container
docker build -t swarm-agent .
```

## Key Patterns

### Prompt Composition
The agent composes its system prompt from two layers:
1. **Persona prompt** — defines personality, tone, and role identity
2. **Instruction sub-prompt** — defines the specific task and constraints

These are combined before each LLM call. Keep them in the `prompts/` directory as plain text or Jinja2 templates.

### File-Level Reasoning
When proposing code changes, the agent reasons at the **file level** — it reads files, decides what to change, and writes complete file contents. It does not do line-level diffs.

### "Good Enough" Signal
The agent has a concept of **"good enough"** — when it determines the task is satisfactorily complete, it signals this to the swarm and shuts down cleanly. Signaling is done via **GitHub labels** on the PR or issue (whichever the agent is operating on):

- **`review:started:<persona>`** — applied when the agent begins working
- **`review:complete:<persona>`** — applied when the agent is satisfied with the results and shutting down

Other agents in the swarm watch for these labels to know when a persona has finished and they can proceed.

### Agent Roles
Not all agents write code. Some personas are focused on **issue refinement and prioritization** (triaging, adding labels, clarifying requirements, breaking down work) rather than code changes. The agent loop and GitHub interactions should support both modes — operating on PRs for code work and on issues for triage/planning work.

### Safety Rails
- Never merge PRs — only create/update them and add comments.
- All GitHub write operations should be logged before execution.
- The agent should fail loudly (raise, don't swallow exceptions) when API calls fail.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes | OpenAI API key for inference |
| `GITHUB_TOKEN` | Yes | PAT for cloning repos and authenticating `gh` CLI |
| `SWARM_PERSONA` | Yes | Name of persona prompt to load |
| `SWARM_TASK` | Yes | Task instruction or instruction prompt name |
| `SWARM_REPO` | Yes | Target GitHub repo (owner/name) |
| `SWARM_PR_NUMBER` | No | PR number to operate on (if applicable) |
| `SWARM_ISSUE_NUMBER` | No | Issue number to operate on (if applicable) |
