# Development Guide

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Project Structure

```
src/second_brain/
├── main.py              # Entry point — orchestrates the full pipeline
├── core/
│   ├── config.py        # Pydantic Settings: loads .env + config.yaml
│   ├── models.py        # Shared data structures (Message, Category, RunResult)
│   └── timeutil.py      # Timezone-aware today()/yesterday() helpers
├── agent/
│   ├── agent.py         # LangGraph ReAct agent construction + invocation
│   ├── llm.py           # OpenRouter LLM factory (ChatOpenAI wrapper)
│   └── prompts.py       # System prompt template for the agent
├── utils/
│   └── parser.py        # Parses dump file into Message objects
├── services/
│   └── drive.py         # Google Drive CRUD via OAuth user credentials
└── tools/
    └── drive_tools.py   # LangChain @tool wrappers over drive.py
```

### Layer Responsibilities

| Layer | Purpose | LangChain Aware? |
|-------|---------|------------------|
| `core/` | Config and shared models used by all layers | No |
| `services/` | Raw API clients (Drive, future: Telegram, Calendar) | No |
| `tools/` | LangChain `@tool` wrappers that the agent can invoke | Yes |
| `agent/` | LLM factory, prompt engineering, agent construction | Yes |
| `utils/` | Pure utility functions (parsing, formatting) | No |

## Running Tests

```bash
# All tests
pytest

# Verbose with test names
pytest -v

# Single test file
pytest tests/test_parser.py

# Single test
pytest tests/test_parser.py::test_single_message
```

## Test Structure

```
tests/
├── conftest.py            # Shared fixtures (sample dump path/text)
├── test_parser.py         # Dump file parser unit tests
├── test_drive_service.py  # Drive API client tests (mocked Google API)
├── test_drive_tools.py    # LangChain tool tests (mocked DriveService)
├── test_agent.py          # Prompt, LLM factory, and agent wiring tests
├── test_pipeline.py       # End-to-end pipeline tests (all deps mocked)
├── test_timeutil.py       # Timezone-aware date helper tests
└── fixtures/
    └── sample_dump.md     # Sample dump file used by parser tests
```

All external dependencies (Google Drive API, OpenRouter) are mocked in tests. No credentials needed to run the test suite.

## Running Locally

```bash
# Copy and fill in your credentials
cp .env.example .env

# Single run for today (in APP_TIMEZONE)
python -m second_brain.main

# Specific date
python -m second_brain.main --date 2026-03-01

# Yesterday (in APP_TIMEZONE) — what run_yesterday.sh uses for the nightly job
python -m second_brain.main --date yesterday

# Ad-hoc query instead of processing a dump file
python -m second_brain.main --prompt "list all projects"

# Rebuild Directory.yaml files across the knowledge base
python -m second_brain.main --index
python -m second_brain.main --index --changed path/to/file1.md path/to/file2.md

# Skip all Drive writes (dry run)
python -m second_brain.main --dry-run

# Debug logging (agent reasoning steps) to the console
python -m second_brain.main --verbose
```

There is no `--schedule` flag — the CLI is a one-shot invocation. Scheduling is handled
externally (see the launchd setup in `AGENTS.md`, or `run_yesterday.sh`).

Two settings tune runtime behavior without code changes (see `core/config.py`):

- `APP_TIMEZONE` (env, default `Asia/Singapore`) — the IANA timezone used to resolve
  "today" (when `--date` is omitted) and `--date yesterday`.
- `SUMMARIZER_LOG_DIR` (env, default `tmp`) — where the per-run DEBUG log file is written,
  relative to the repo root. Set to an empty string to log to stdout only.

## Google Drive Setup

This project authenticates as **your own Google account** via OAuth (a user token), not a
service account.

1. Create an [OAuth client ID](https://console.cloud.google.com/apis/credentials) of type
   "Desktop app" in Google Cloud Console
2. Enable the Google Drive API for the project
3. Download the client credentials JSON and save it as `client_secret.json` in the repo root
4. Create two Google Drive folders (input and output) in your own Drive
5. On first run (no `token.json` present), the app opens a browser for the OAuth consent
   flow and writes the resulting token to `token.json`. In CI/headless environments, set the
   `GOOGLE_TOKEN_JSON` env var to the token JSON content instead
6. Copy the folder IDs (from the URL: `drive.google.com/drive/folders/{THIS_IS_THE_ID}`) into `.env`

## Dump File Format

Files in the input folder must be named `YYYY-MM-DD.md` and use this delimiter format:

```markdown
<!-- msg_id: unique-id-001 -->
Message content goes here. Can be multiple lines.

<!-- msg_id: unique-id-002 -->
Another message.
```

The `msg_id` values should be unique within a file. Content between delimiters is captured as-is (whitespace stripped).

## Swapping the LLM

Change the model in `config.yaml`:

```yaml
llm:
  model: "openai/gpt-4o"          # or any OpenRouter-supported model
  temperature: 0.3
  max_tokens: 4096
```

No code changes needed. See [OpenRouter models](https://openrouter.ai/models) for available options.

## Adding a New Integration

Follow the two-layer pattern:

1. **Add a client** in `services/` (e.g., `services/telegram.py`) — raw API wrapper, no LangChain awareness
2. **Add tools** in `tools/` (e.g., `tools/telegram_tools.py`) — LangChain `@tool` functions wrapping the client
3. **Register tools** in `agent/agent.py` by including them in the tools list

The agent autonomously decides when to invoke tools based on message content during its reasoning loop.

## Docker

```bash
# Build
docker build -t second-brain .

# Run once
docker run --env-file .env \
  -v ./token.json:/app/token.json \
  second-brain

# Run for yesterday's dump
docker run --env-file .env \
  -v ./token.json:/app/token.json \
  second-brain --date yesterday
```
