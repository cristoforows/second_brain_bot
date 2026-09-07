# Second Brain Summarizer

AI agent that reads daily message dumps from Google Drive, then summarizes, categorizes, and organizes them into a living knowledge base using the PARA method.

Built with LangChain + LangGraph for agentic reasoning, OpenRouter for model-agnostic LLM access, and your Google account's OAuth token (`token.json`) for Drive file I/O.

## How It Works

1. Fetches today's dump file (`YYYY-MM-DD.md`) from an input Google Drive folder
2. Parses messages delimited by `<!-- msg_id: {id} -->` markers
3. An AI agent reads the existing knowledge base structure, then autonomously:
   - Classifies each message into a PARA section (to-do, projects, areas, resources, archives)
   - Routes messages to the appropriate topic folder within that section
   - Merges new content with existing notes (read-before-write)
   - Updates each section's `directory.md` after every write
   - Updates the root `directory.md` when the top-level structure changes

## Output Structure

The knowledge base uses a 3-level PARA hierarchy:

```
Output Drive Folder/
├── directory.md              # Root index of all 5 sections
├── to-do/
│   ├── directory.md          # Lists topic folders in this section
│   └── shopping/
│       └── groceries.md
├── projects/
│   ├── directory.md
│   └── dashboard-redesign/
│       └── notes.md
├── areas/
│   ├── directory.md
│   └── health/
│       └── running-log.md
├── resources/
│   ├── directory.md
│   └── books/
│       └── data-intensive-applications.md
└── archives/
    └── directory.md
```

## Prerequisites

- Python 3.11+
- [OpenRouter](https://openrouter.ai/) API key
- A Google Cloud OAuth client (Desktop app) with the Drive API enabled, downloaded as `client_secret.json`
- Two Google Drive folders (input and output) accessible to the Google account you authorize during the OAuth flow

## Quick Start

```bash
# Clone and set up
git clone <repo-url>
cd second_brain_summarizer
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Configure
cp .env.example .env
# Edit .env with your credentials

# Run
python -m second_brain.main                                # Process today's dump (in APP_TIMEZONE)
python -m second_brain.main --date 2026-03-01               # Process a specific date
python -m second_brain.main --date yesterday                # Process yesterday's dump (in APP_TIMEZONE)
python -m second_brain.main --prompt "list all projects"    # Ad-hoc query
python -m second_brain.main --index                         # Rebuild Directory.yaml files
python -m second_brain.main --dry-run                       # Run without writing to Drive
python -m second_brain.main --verbose                       # Debug logging (agent reasoning steps)
```

There is no built-in scheduler — the pipeline is a one-shot CLI invocation. Trigger it on a
schedule with `cron`, `launchd` (see `AGENTS.md`), or similar. `run_yesterday.sh` wraps
`second-brain --date yesterday` for exactly this purpose.

## Configuration

Secrets go in `.env`:

| Variable | Description |
|----------|-------------|
| `OPENROUTER_API_KEY` | Your OpenRouter API key |
| `GOOGLE_SERVICE_REFRESH_TOKEN` | Path to the OAuth token JSON file (default `./token.json`) |
| `GOOGLE_TOKEN_JSON` | Optional: the OAuth token JSON *content* itself, instead of a file — used in CI/headless environments where writing `token.json` to disk isn't practical |
| `INPUT_DRIVE_FOLDER_ID` | Google Drive folder ID containing dump files |
| `OUTPUT_DRIVE_FOLDER_ID` | Google Drive folder ID for the knowledge base |
| `APP_TIMEZONE` | IANA timezone used to resolve "today" and `--date yesterday` (default `Asia/Singapore`) |
| `SUMMARIZER_LOG_DIR` | Directory for per-run debug log files, relative to the repo root (default `tmp`); set to an empty string for stdout-only logging |

The first time you run without a `token.json` present, the app opens an interactive OAuth
consent flow using `client_secret.json` and saves the resulting token to `token.json`.

Non-secrets go in `config.yaml`:

```yaml
llm:
  model: ""  # Any OpenRouter model
  temperature: 0.3
  max_tokens: 4096

seed_categories:
  - name: "work"
    description: "Work-related tasks, meetings, projects"
  - name: "personal"
    description: "Personal notes, reminders, ideas"
```

## Dump File Format

Place markdown files named `YYYY-MM-DD.md` in the input folder. Messages are delimited by HTML comments:

```markdown
<!-- msg_id: msg-001 -->
Had a productive meeting with the design team today.

<!-- msg_id: msg-002 -->
Finished reading chapter 5 on replication.
```

## Docker

```bash
docker build -t second-brain .
docker run --env-file .env -v ./token.json:/app/token.json second-brain
docker run --env-file .env -v ./token.json:/app/token.json second-brain --date yesterday
```

## Architecture

```
src/second_brain/
├── main.py          # Pipeline orchestrator + CLI
├── core/            # Config (Pydantic Settings) and shared data models
├── agent/           # LLM factory, system prompt, LangGraph ReAct agent
├── utils/           # Dump file parser
├── services/        # Google Drive API client (raw wrapper)
└── tools/           # LangChain @tool definitions (agent-facing)
```

The `services/` + `tools/` two-layer pattern is extensible: future integrations (Telegram, Google Calendar, etc.) add a new client in `services/` and corresponding tools in `tools/`. The agent decides when to invoke them.
