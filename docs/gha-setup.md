# GitHub Actions Setup

The pipeline is currently triggered locally via `run_yesterday.sh` and a macOS launcher (launchd). GHA support is stubbed in the code but not wired up. This document covers how to enable it when needed.

## Credential strategy

Storing a Google OAuth refresh token in GitHub Secrets gives it access to your **entire Google Drive**. The two safer approaches are:

### Option A — Self-hosted runner (recommended)

Run the GHA runner process on your own Mac. `token.json` never leaves the machine; GitHub just orchestrates the cron trigger.

**Setup:**
1. Repo → Settings → Actions → Runners → New self-hosted runner
2. Follow the download/configure steps (~10 min)
3. The installer registers a `launchd` service that keeps the runner alive across reboots

**Workflow snippet:**
```yaml
runs-on: self-hosted
```

**Secrets needed** (low-risk — no Drive access on their own):
- `OPENROUTER_API_KEY`
- `INPUT_DRIVE_FOLDER_ID`
- `OUTPUT_DRIVE_FOLDER_ID`

**Cons:**
- Mac must be on and awake when the cron fires — if it's asleep or off, the job is skipped
- If the runner process crashes and launchd doesn't revive it, jobs queue silently until you notice
- Tied to one machine — no redundancy

---

### Option B — Service account with scoped folder access

Create a Google Cloud service account, share *only* the input/output Drive folders with its email. Store the service account JSON key in GitHub Secrets. If the key leaks, it only touches those two folders.

**Requires code changes:**
- Replace `google-auth-oauthlib` OAuth flow with service account auth (`google.oauth2.service_account.Credentials`)
- Remove `GOOGLE_TOKEN_JSON` / `token.json` credential loading from `drive.py`
- Add `GOOGLE_APPLICATION_CREDENTIALS_JSON` secret (service account key JSON)

**Cons:**
- More Google Cloud setup (project, service account, IAM)
- Service account key doesn't auto-rotate — needs manual rotation if compromised

---

## What's already in the code

`drive.py` already supports `GOOGLE_TOKEN_JSON` as an env var (checked before falling back to `token.json` on disk). This was added for future GHA use. With a self-hosted runner this env var is unused; the file-based flow runs as normal.

## Workflow file (self-hosted runner)

Create `.github/workflows/daily.yml`:

```yaml
name: Daily summarizer

on:
  schedule:
    - cron: "0 8 * * *"  # 8 AM UTC daily
  workflow_dispatch:
    inputs:
      date:
        description: "Date to process (YYYY-MM-DD). Defaults to yesterday."
        required: false

jobs:
  run:
    runs-on: self-hosted
    steps:
      - uses: actions/checkout@v4

      - name: Determine date
        id: date
        run: |
          if [ -n "${{ inputs.date }}" ]; then
            echo "value=${{ inputs.date }}" >> $GITHUB_OUTPUT
          else
            echo "value=$(date -v-1d +%Y-%m-%d)" >> $GITHUB_OUTPUT
          fi

      - name: Run pipeline
        env:
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
          INPUT_DRIVE_FOLDER_ID: ${{ secrets.INPUT_DRIVE_FOLDER_ID }}
          OUTPUT_DRIVE_FOLDER_ID: ${{ secrets.OUTPUT_DRIVE_FOLDER_ID }}
        run: |
          .venv/bin/second-brain --date ${{ steps.date.outputs.value }}
```

> **Note:** This workflow assumes the venv and `token.json` already exist on the runner machine. The `checkout` step is needed so `config.yaml` is current, but the venv and credentials are persistent on the host.
