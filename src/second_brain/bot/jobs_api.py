"""POST /api/jobs/nightly-summary — starts the summarizer as a one-off Fly
machine, triggered by the nightly GitHub Actions workflow.

Deliberately independent of the rest of webhook.py's bot stack: it never
touches `bot_app`/`event_loop`/`token_storage`, so it doesn't gate on
`_bot_ready()` and is reachable the moment Flask starts accepting
connections, not just once the bot has finished initializing.

Auth is GitHub Actions OIDC (see `github_oidc.py`), not a shared secret —
the workflow proves its identity (repository/ref/workflow/event) with a
token GitHub itself signs, so no long-lived credential needs to live in the
workflow at all.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from second_brain.bot.github_oidc import (
    OidcRejected,
    OidcUnavailable,
    PolicyRejected,
    verify_github_identity,
)
from second_brain.core import fly_machines
from second_brain.core.config import get_settings
from second_brain.core.timeutil import today

logger = logging.getLogger(__name__)

jobs_bp = Blueprint("jobs_api", __name__)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ALLOWED_BODY_KEYS = {"date", "dry_run"}
_MAX_BACKFILL_DAYS = 30
_JOB_REGION = "sin"
_JOB_MEMORY_MB = 512
# Mirrors the job machine's own internal SUMMARIZER_MAX_SECONDS budget (see
# core.config) plus headroom for the SIGKILL grace period, so `summarize`
# always gets a chance to report its own failure before this escalates.
_JOB_TIMEOUT_CMD = ["timeout", "-k", "60", "2100"]


@jobs_bp.route("/api/jobs/nightly-summary", methods=["POST"])
def trigger_nightly_summary():
    settings = get_settings()

    if not settings.fly_job_token:
        return jsonify({"error": "nightly trigger disabled"}), 503

    auth_header = request.headers.get("Authorization", "")
    prefix = "Bearer "
    if not auth_header.startswith(prefix) or not auth_header[len(prefix):]:
        return jsonify({"error": "unauthorized"}), 401
    bearer = auth_header[len(prefix):]

    try:
        claims = verify_github_identity(bearer)
    except OidcUnavailable as e:
        logger.error(f"nightly trigger: identity verification unavailable: {e}")
        return jsonify({"error": "identity verification unavailable"}), 503
    except OidcRejected as e:
        logger.warning(f"nightly trigger: OIDC token rejected: {e}")
        return jsonify({"error": "unauthorized"}), 401
    except PolicyRejected as e:
        logger.warning(f"nightly trigger: policy rejected: {e}")
        return jsonify({"error": "forbidden"}), 403

    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict) or not set(body.keys()) <= _ALLOWED_BODY_KEYS:
        return jsonify({"error": "body must be a JSON object with only 'date'/'dry_run' keys"}), 400

    date = body.get("date")
    if date is not None:
        if not isinstance(date, str) or not _DATE_RE.match(date):
            return jsonify({"error": "date must be YYYY-MM-DD"}), 400
        try:
            parsed_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"error": "date must be YYYY-MM-DD"}), 400
        today_local = today(settings.app_timezone)
        if parsed_date > today_local:
            return jsonify({"error": "date must not be after today"}), 400
        if parsed_date < today_local - timedelta(days=_MAX_BACKFILL_DAYS):
            return jsonify({"error": f"date must be within the last {_MAX_BACKFILL_DAYS} days"}), 400

    dry_run = body.get("dry_run", False)
    if not isinstance(dry_run, bool):
        return jsonify({"error": "dry_run must be a boolean"}), 400

    app_name = settings.fly_app_name
    if fly_machines.summarizer_active(app_name):
        return jsonify({"error": "a summarizer job is already running"}), 409

    cmd = list(_JOB_TIMEOUT_CMD) + ["second-brain", "summarize"]
    if date:
        cmd += ["--date", date]
    if dry_run:
        cmd += ["--dry-run"]

    metadata = {
        "role": "summarizer",
        "triggered_by": "github",
        "run_id": str(claims.get("run_id", "")),
        "event": claims.get("event_name", ""),
    }

    try:
        machine_id = fly_machines.create_machine(
            app_name,
            image=settings.fly_image_ref,
            cmd=cmd,
            region=_JOB_REGION,
            memory_mb=_JOB_MEMORY_MB,
            metadata=metadata,
        )
    except fly_machines.FlyMachinesError as e:
        logger.error(f"nightly trigger: Fly Machines API error: {e}")
        return jsonify({"error": "failed to start job machine"}), 502

    logger.info(
        "nightly job started "
        f"machine_id={machine_id} run_id={claims.get('run_id')} "
        f"actor={claims.get('actor')} event_name={claims.get('event_name')}"
    )
    return (
        jsonify({"ok": True, "machine_id": machine_id, "date": date or "yesterday", "dry_run": dry_run}),
        202,
    )
