# Deploy (Fly.io)

The bot runs as a single Fly.io app, built from `Dockerfile`, scaled to zero
between requests. This guide covers the Fly workflow only.

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
want to change from the default.

`fly secrets set` triggers a new deploy on its own; you don't need to also
run `fly deploy` right after unless you're also shipping a code change.

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
