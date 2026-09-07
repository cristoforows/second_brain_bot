# Deploy (Fly.io)

The bot and the nightly summarizer ship from the same Dockerfile as a single
Fly.io app. The bot runs continuously (scaled to zero between requests); the
summarizer runs as a one-off machine invocation, not a long-lived process.
This guide covers the Fly workflow only.

## Prerequisites

- [`fly` CLI](https://fly.io/docs/flyctl/install/) installed and logged in
  (`fly auth login`)
- The app already exists: `second-brain-bot-old-violet-1669` (see `fly.toml`
  for its config — region, VM size, health check)

## Secrets

Set required config as Fly secrets (never commit these). Names come from
`.env.example`:

```bash
fly secrets set \
  TELEGRAM_BOT_TOKEN=... \
  WEBHOOK_URL=https://second-brain-bot-old-violet-1669.fly.dev \
  GOOGLE_CLIENT_ID=... \
  GOOGLE_CLIENT_SECRET=... \
  GOOGLE_REDIRECT_URI=https://second-brain-bot-old-violet-1669.fly.dev/oauth/callback \
  DATABASE_USER=... \
  DATABASE_PASSWORD=... \
  DATABASE_HOST=... \
  DATABASE_PORT=... \
  DATABASE_NAME=... \
  TOKEN_ENCRYPTION_KEY=... \
  OPENROUTER_API_KEY=...
```

Optional overrides (Drive folder names, `DAY_CUTOFF_HOUR`,
`OUTBOUND_API_SECRET`, `LLM_MODEL`, and the `TIMEBOX_*` scheduling defaults)
are documented with their defaults in `.env.example` — set only the ones you
want to change from the default. `APP_TIMEZONE` is set in `fly.toml`'s
`[env]` block (not a secret) since it isn't sensitive.

`fly secrets set` triggers a new deploy on its own; you don't need to also
run `fly deploy` right after unless you're also shipping a code change.

For the nightly summarizer job, also set:

```bash
fly secrets set \
  GOOGLE_TOKEN_JSON="$(cat token.json)" \
  INPUT_DRIVE_FOLDER_ID=... \
  VAULT_FOLDER_ID=... \
  SUMMARY_CHAT_ID=... \
  FLY_JOB_TOKEN=...
```

`GOOGLE_TOKEN_JSON` carries the OAuth token's JSON *content* (rather than a
file path) since Fly secrets are environment variables, not files —
`summarizer/drive.py` checks for it before falling back to
`GOOGLE_SERVICE_REFRESH_TOKEN`'s file path.

`FLY_JOB_TOKEN` is what lets the bot itself create the summarizer's one-off
machine when the nightly workflow calls `POST /api/jobs/nightly-summary` —
see "Nightly summarizer job" below for how to generate it. Leaving it unset
disables that endpoint (it returns 503) without affecting anything else.

## Deploy

```bash
fly deploy
```

This builds the image from `Dockerfile` using Fly's remote builder (no local
Docker required) and rolls out a new release.

## Verify

```bash
fly status                                                        # machine state
fly logs                                                          # tail startup + runtime logs
curl https://second-brain-bot-old-violet-1669.fly.dev/            # health check -> {"status": "ok", ...}
curl https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getWebhookInfo   # confirm Telegram has the right webhook URL
```

## Rollback

```bash
fly releases                        # list past releases and their image refs
fly deploy --image <previous-image> # redeploy a specific prior image
```

## Scale-to-zero and suspend

`fly.toml` sets `min_machines_running = 0` and `auto_stop_machines =
"suspend"`: the machine suspends (not a full stop) after a period of no
traffic, and `auto_start_machines = true` lets Fly's proxy wake it on the
next incoming request — faster than a cold boot. The `[[http_service.checks]]`
block polls `GET /` every 30s (5s timeout, 20s grace period after start) so
Fly's routing layer knows when the machine is actually ready.

## Runtime notes

- Flask is served by [waitress](https://docs.pylonsproject.org/projects/waitress/)
  (a production WSGI server), single process, 8 worker threads — not Flask's
  single-threaded dev server. It binds the port immediately on start, before
  the heavier bot-stack imports run, so Fly's proxy never hits a closed port
  during cold start.
- On SIGTERM or SIGINT (Fly sends SIGINT on autostop/suspend) the server
  shuts down gracefully: `bot_app.stop()` then `bot_app.shutdown()` run on
  the bot's event loop, then the loop itself is stopped. Shutdown is
  attempted at most once and never raises past a logged error.
- The Postgres connection pool sends TCP keepalives and, on checkout,
  verifies a connection with `SELECT 1` before use — a connection that went
  stale across a suspend/resume cycle is discarded and replaced
  transparently instead of surfacing an error to the caller.

## Nightly summarizer job

The summarizer runs as a **one-off Fly machine**, not a long-lived service —
it starts, processes one day's dump, sends its Telegram summary, and exits.
It ships from the exact same image as the bot (same `Dockerfile`, same
deploy), just invoked with a different command.

### How the trigger works

```
GitHub Actions (cron, 04:05 SGT)
  │  requests a short-lived OIDC ID token from GitHub
  ▼
POST /api/jobs/nightly-summary  (the bot, always-on)
  │  verifies the token's signature (GitHub's JWKS) and its claims
  │  (repository/ref/workflow/event) against an allowlist — no shared
  │  secret between the workflow and the bot, just this verification
  ▼
Fly Machines API — creates a one-off machine:
  second-brain summarize [--date D] [--dry-run]
  (wrapped in `timeout -k 60 2100` so a hang can't run forever)
  │  auto_destroy: true, restart policy "no" — runs once, cleans itself up
  ▼
Telegram: run summary + active to-do digest (or a ❌ failure notice)
```

There is no long-lived secret in the workflow at all — GitHub signs the
identity token itself, and the bot verifies it against `NIGHTLY_ALLOWED_*`
settings rather than trusting a bearer secret.

### Secrets to set

In addition to the bot secrets above:

```bash
fly secrets set \
  FLY_JOB_TOKEN=$(fly tokens create deploy -a second-brain-bot-old-violet-1669 --name job-runner --expiry 8760h) \
  GOOGLE_TOKEN_JSON="$(cat token.json)" \
  INPUT_DRIVE_FOLDER_ID=... \
  VAULT_FOLDER_ID=... \
  SUMMARY_CHAT_ID=...
```

`FLY_JOB_TOKEN` is a deploy-scoped Fly API token (1-year expiry above; rotate
before it lapses) — it's what lets the bot call the Fly Machines API on its
own behalf to create the summarizer machine. `FLY_APP_NAME` and
`FLY_IMAGE_REF` don't need to be set manually — Fly injects both into every
machine automatically.

### Policy (who's allowed to trigger)

The endpoint accepts a token only if **all** of these match (defaults below;
override via the matching `NIGHTLY_*` env var only if you forked the repo or
renamed the workflow):

| Claim | Required value | Setting |
|---|---|---|
| `aud` (audience) | `second-brain-bot-nightly` | `NIGHTLY_OIDC_AUDIENCE` |
| `repository` | `cristoforows/second_brain_bot` | `NIGHTLY_ALLOWED_REPOSITORY` |
| `ref` | `refs/heads/main` | `NIGHTLY_ALLOWED_REF` |
| `workflow_ref` (prefix) | `<repository>/<workflow>@<ref>` | `NIGHTLY_ALLOWED_WORKFLOW` |
| `event_name` | `schedule` or `workflow_dispatch` | (fixed, not configurable) |

A token failing signature/expiry/audience/issuer checks gets **401**; a
token that verifies but doesn't match the policy table gets **403**; GitHub's
JWKS endpoint being unreachable gets **503** (retry — this isn't a rejection).
A request while a summarizer machine is already running gets **409**; a
downstream Fly Machines API failure gets **502**.

### Backfilling a specific day

Either trigger the workflow manually with a date:

```bash
gh workflow run nightly-summary.yml -f date=2026-06-01 -f dry_run=true
```

(uses "Run workflow" → fill in `date`/`dry_run` if you'd rather click through
the GitHub UI), or bypass the trigger entirely and run a machine directly:

```bash
fly machine run <image> -a <app> --rm --restart no --region sin \
  --vm-memory 512 --command "second-brain summarize --date YYYY-MM-DD"
```

Find `<image>` from `fly releases` or `fly image show`. `--rm` deletes the
machine once it exits; `--restart no` stops Fly from ever restarting a
one-shot job that's supposed to run once.

### Negative test

Confirm the endpoint rejects an unauthenticated request (expect `401`):

```bash
curl -i -X POST https://second-brain-bot-old-violet-1669.fly.dev/api/jobs/nightly-summary
```
