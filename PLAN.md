# Second Brain Summarizer — Implementation Plan

## Context

Build a LangChain-based AI agent that runs daily (cron), reads a markdown dump file from Google Drive containing messages, then summarizes, categorizes, and organizes them into a living document structure on a separate Google Drive folder. The system uses OpenRouter for LLM access (model-agnostic) and Google Drive service account for file I/O. The architecture must be extensible for future agentic actions (Telegram, Google Calendar, etc.) but the MVP focuses on core summarization and categorization only.

### Key Decisions Made
- **Language**: Python (most mature LangChain SDK)
- **LLM**: OpenRouter API — model-agnostic, swappable via config
- **Storage**: Google Drive (service account auth) — input folder for dumps, separate output folder for organized docs
- **Trigger**: Daily cron schedule
- **Categorization**: Seed categories provided by user, AI can extend with new ones
- **Input format**: `<!-- msg_id: {message_id} -->\n{content}\n` — multiple messages per daily dump file
- **Output**: Living documents in category-based folder structure with summaries
- **MVP scope**: Core summarization/categorization only (no Telegram/Calendar yet)
- **Deployment**: Agnostic for now, Docker-friendly

---

## Project Structure

```
second_brain_summarizer/
├── pyproject.toml                  # Project metadata, dependencies, scripts
├── .env.example                    # Template for required env vars
├── config.yaml                     # Seed categories, Drive folder IDs, model settings
├── Dockerfile                      # For deployment-agnostic containerization
├── src/
│   └── second_brain/
│       ├── __init__.py
│       ├── main.py                 # Entry point — orchestrates the full pipeline
│       ├── config.py               # Pydantic Settings: loads .env + config.yaml
│       ├── parser.py               # Parses dump file into individual messages
│       ├── agent.py                # LangChain agent construction (ReAct agent + tools)
│       ├── prompts.py              # System prompt templates for the agent
│       ├── llm.py                  # OpenRouter LLM factory (model-agnostic)
│       ├── drive/
│       │   ├── __init__.py
│       │   └── client.py           # Google Drive CRUD via service account
│       ├── tools/
│       │   ├── __init__.py
│       │   └── drive_tools.py      # LangChain @tool wrappers for Drive operations
│       └── actions/                # Future: extensible action system
│           ├── __init__.py
│           └── base.py             # Abstract base class for agentic actions
└── tests/
    ├── conftest.py
    ├── test_parser.py
    ├── test_agent.py
    ├── test_drive_client.py
    └── fixtures/
        └── sample_dump.md          # Sample dump file for testing
```

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `langchain` + `langchain-openai` | Agent framework + ChatOpenAI (works with OpenRouter) |
| `langgraph` | For building the ReAct agent loop |
| `google-api-python-client` + `google-auth` | Google Drive API via service account |
| `pydantic-settings` | Config management (env vars + YAML) |
| `pyyaml` | Parse config.yaml |
| `python-dotenv` | Load .env file |
| `apscheduler` | In-process cron scheduling (optional, can also use system cron) |
| `structlog` | Structured logging |
| `pytest` + `pytest-asyncio` | Testing |

---

## Core Modules

### 1. `config.py` — Configuration
- Pydantic Settings model loading from `.env` (secrets) and `config.yaml` (non-secrets)
- Fields: `openrouter_api_key`, `google_service_refresh_token`, `input_drive_folder_id`, `output_drive_folder_id`, `llm_model` (default configurable), `seed_categories` (list), `schedule_cron` (default: daily)

### 2. `parser.py` — Dump File Parser
- Parses markdown content by `<!-- msg_id: {id} -->` delimiters
- Returns list of `Message(id: str, content: str)` dataclass objects
- Pure function, no side effects — easily testable

### 3. `llm.py` — LLM Factory
- Creates a `ChatOpenAI` instance pointed at OpenRouter's API base URL (`https://openrouter.ai/api/v1`)
- Model name configurable via `config.yaml`
- Swapping LLM = changing one config value

### 4. `drive/client.py` — Google Drive Client
- Service account authentication
- Methods: `list_files(folder_id)`, `read_file(file_id) -> str`, `write_file(folder_id, name, content)`, `update_file(file_id, content)`, `create_folder(parent_id, name)`, `find_file(folder_id, name)`
- All Drive operations go through this single class

### 5. `tools/drive_tools.py` — LangChain Tools
- `read_directory_index` — Reads `directory.md` to understand existing categories
- `read_category_summary(category_name)` — Reads a category's summary file
- `read_file(category_name, filename)` — Reads an existing note file
- `write_to_category(category_name, filename, content)` — Creates/updates a file in a category folder
- `update_category_summary(category_name, summary)` — Updates the category summary .md
- `update_directory_index(content)` — Updates root `directory.md`
- `create_new_category(category_name, description)` — Creates a new category folder with initial summary

### 6. `agent.py` — LangChain Agent
- Uses LangGraph's `create_react_agent` with the tools above
- System prompt instructs the agent to:
  1. Read `directory.md` to understand existing category structure
  2. For each message batch, determine the best category (existing or new)
  3. Read existing category files if updating them
  4. Write/update notes into the appropriate category files
  5. Update category summaries
  6. Update `directory.md` if new categories were created
- The agent makes autonomous decisions about categorization, merging related messages, and document structure

### 7. `main.py` — Pipeline Orchestrator
- Loads config
- Initializes Drive client
- Finds today's dump file in the input folder
- Parses messages
- Builds and invokes the agent with the parsed messages as input
- Logs results

---

## Data Flow

```
[Google Drive: Input Folder]
        │
        ▼
  1. Fetch today's dump file (by date naming convention)
        │
        ▼
  2. Parse into Message[] via parser.py
        │
        ▼
  3. Agent receives messages as input
        │
        ▼
  4. Agent reads directory.md (via tool) to understand existing categories
        │
        ▼
  5. Agent groups/categorizes messages using LLM reasoning
        │
        ▼
  6. For each category:
     - Read existing files (via tool) if appending
     - Write/update note files (via tool)
     - Update category summary (via tool)
        │
        ▼
  7. Update directory.md if structure changed (via tool)
        │
        ▼
  [Google Drive: Output Folder — Living Documents Updated]
```

---

## Living Document Update Strategy

- **Note files**: Agent reads existing content first, then appends or merges new information. The agent decides whether a new message warrants a new file or should be appended to an existing one based on topic relevance.
- **Category summaries** (`category1.md`): Regenerated each run by the agent after it has placed all new messages. A short, low-context overview.
- **Directory index** (`directory.md`): Updated only when categories are added/modified. Provides the agent a quick lookup for future runs.

---

## Configuration Example

**.env**
```
OPENROUTER_API_KEY=sk-or-...
GOOGLE_SERVICE_REFRESH_TOKEN=./token.json
INPUT_DRIVE_FOLDER_ID=1abc...
OUTPUT_DRIVE_FOLDER_ID=1xyz...
```

**config.yaml**
```yaml
llm:
  model: ""  # or any OpenRouter model
  temperature: 0.3
  max_tokens: 4096

seed_categories:
  - name: "work"
    description: "Work-related tasks, meetings, projects"
  - name: "personal"
    description: "Personal notes, reminders, ideas"
  - name: "learning"
    description: "Study notes, articles, courses"
  - name: "health"
    description: "Health, fitness, medical notes"

schedule:
  cron: "0 8 * * *"  # Daily at 8 AM
```

---

## Implementation Order

### Step 1: Project scaffolding
- Create `pyproject.toml` with dependencies
- Set up `src/second_brain/` package structure
- Create `.env.example` and `config.yaml`
- Implement `config.py` (Pydantic Settings)

### Step 2: Dump file parser
- Implement `parser.py` with regex parsing for `<!-- msg_id: ... -->` delimiters
- Write `tests/test_parser.py` with sample fixtures

### Step 3: Google Drive client
- Implement `drive/client.py` with service account auth
- Methods: list, read, write, update, create folder, find
- Test with a real service account against a test folder

### Step 4: LLM factory
- Implement `llm.py` with OpenRouter-compatible `ChatOpenAI`
- Verify connectivity with a simple test call

### Step 5: LangChain tools
- Implement `tools/drive_tools.py` — all 7 tools listed above
- Each tool wraps the Drive client with clear docstrings (these guide agent behavior)

### Step 6: Agent construction
- Implement `prompts.py` with the system prompt
- Implement `agent.py` using `create_react_agent` from LangGraph
- Wire up LLM + tools into the agent

### Step 7: Pipeline orchestrator
- Implement `main.py` that ties everything together
- Add scheduling with APScheduler or expose as a CLI command for system cron

### Step 8: End-to-end testing
- Create a test Google Drive folder with a sample dump file
- Run the full pipeline and verify output structure
- Verify living document updates on subsequent runs

---

## Verification Plan

1. **Unit tests**: Run `pytest tests/` — parser tests with fixtures, Drive client tests with mocks
2. **Integration test**: Set up test folders on Google Drive, place a sample dump file, run `python -m second_brain.main`, verify:
   - Category folders created in output folder
   - Notes correctly categorized
   - `directory.md` and category summaries generated
3. **Living document test**: Run again with a second dump file, verify existing documents are updated (not overwritten)
4. **LLM swap test**: Change model in `config.yaml`, run again, verify it still works

---

## Future Extensibility (Not in MVP)

The `actions/` package provides a hook point for future agentic actions:
- `TelegramAction` — send scheduled reminders via Telegram bot
- `CalendarAction` — create Google Calendar events/tasks
- Each action implements a base interface and is registered as a LangChain tool
- The agent can then decide when to invoke these actions based on message content
