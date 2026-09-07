# AGENTS.md — Second Brain Summarizer

General reference for understanding how this project is structured and scheduled.

## What this does

A daily agent pipeline that reads a daily message dump from Google Drive, extracts action items and notes, and files them into a PARA-organized knowledge base on Google Drive. On days with no dump file it runs to-do maintenance instead.

## Scheduling

Runs via **launchd** at 02:51 local time every day.

- Plist: `~/Library/LaunchAgents/com.secondbrain.summarizer.plist`
- Script: `run_yesterday.sh` — waits for network, then calls `second-brain --date yesterday`
  (the CLI resolves the literal `yesterday` itself, using the `APP_TIMEZONE` setting)
- Logs: stdout/stderr go to `/tmp/second-brain.log` and `/tmp/second-brain-error.log`; the app
  also writes a per-run debug log to `<SUMMARIZER_LOG_DIR>/<run-id><date>.log` (default
  `tmp/<run-id><date>.log`; set `SUMMARIZER_LOG_DIR=""` for stdout-only logging)

Useful launchd commands:
```bash
# Check status (shows PID if running, last exit code)
launchctl list | grep secondbrain

# Reload plist after editing it
launchctl unload ~/Library/LaunchAgents/com.secondbrain.summarizer.plist
launchctl load   ~/Library/LaunchAgents/com.secondbrain.summarizer.plist

# Trigger a manual run now
launchctl start com.secondbrain.summarizer

# Kill a stuck run
kill <PID>
```

## Agent architecture

```
main.py
  └── run_pipeline()
        ├── DriveService        — reads dump file, writes run summary
        ├── parse_dump()        — splits dump into Message objects
        └── LangGraph ReAct agent
              ├── LLM: OpenRouter (model set in config.yaml)
              └── Tools (drive_tools.py):
                    list_folder, read_directory_index,
                    read_category_summary, read_file,
                    write_to_category, update_category_summary,
                    update_directory_index, create_new_category
```

The agent reads `Directory.yaml` first to understand the knowledge base structure, then reads any `AGENTS.md` files in sections it will modify before writing.

## Configuration

`config.yaml` controls the LLM:
```yaml
llm:
  model: "deepseek/deepseek-v4-flash"
  provider:
    order: ["atlas-cloud/fp8"]
    allow_fallbacks: false
  temperature: 0.5
  max_tokens: 16000
```

Credentials live in `.env` (see `.env.example`), authenticating as your Google account's
OAuth token (`token.json`), not a service account. `.env` also carries the two runtime
settings `APP_TIMEZONE` (default `Asia/Singapore`) and `SUMMARIZER_LOG_DIR` (default `tmp`).
In CI/headless environments, `GOOGLE_TOKEN_JSON` can hold the token JSON content directly
instead of relying on a `token.json` file on disk.

## Knowledge base layout (PARA)

The output Drive folder is organized as:
```
projects/   — active multi-step work
resources/  — reference material by topic
areas/      — ongoing responsibilities
archive/    — completed or inactive items
to-do/      — daily task list + archive
```

Each section and topic folder may contain a `Directory.yaml` index and an `AGENTS.md` that the agent treats as mandatory rules for that folder.

## Debugging a stuck / missing run

**Step 1 — confirm the job is stuck (not just slow)**
```bash
launchctl list | grep secondbrain
# Output: <PID>  <exit-code>  com.secondbrain.summarizer
# A numeric PID means the job is currently running.
# A dash (-) means it last exited with exit-code.
```

**Step 2 — check how long it has been running**
```bash
ps -p <PID> -o pid,stat,etime,command
# ELAPSED column shows DD-HH:MM:SS — anything over ~35 min is stuck.
```

**Step 3 — find the child process to confirm it's blocked on an API call**
```bash
ps -ef | awk '$3 == <PID>'
# Should show the Python process. If that process also has an old start time
# it is the one making the stuck HTTP request.
```

**Step 4 — check the last log to see where it stopped**
```bash
ls -lt tmp/*.log | head -5         # find the most recent log
tail -40 tmp/<logfile>             # look for agent_invocation_start with no completion after it
```

**Step 5 — kill and recover**
```bash
kill <PID>                         # SIGTERM the bash wrapper; Python child dies too
launchctl unload ~/Library/LaunchAgents/com.secondbrain.summarizer.plist
launchctl load   ~/Library/LaunchAgents/com.secondbrain.summarizer.plist
# Run manually to process any missed dates:
.venv/bin/second-brain --date YYYY-MM-DD
```

The `TimeOut` key in the plist (2100 s) and `request_timeout` on the LLM client (1800 s) prevent this from happening silently again — launchd will SIGTERM the job after 35 minutes.
