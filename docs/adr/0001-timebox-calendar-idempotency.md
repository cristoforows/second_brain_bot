# 1. Timebox calendar writes are idempotent via tag + clear-then-write

Date: 2026-06-21

## Status

Accepted

## Context

`/timebox` generates a Schedule for a Target Date and (new) writes it as events
into a configured Target Calendar. The session can write to the same day more
than once:

- `/done` keeps the task buffer and stays open after a failure, so the user can
  retry `/done` — possibly after a partial write.
- The user may re-run `/timebox` for a day already planned.

A naive "just insert" approach produces duplicate events on every retry or redo.
We need re-running to converge on a single correct set of events.

## Decision

Every event the bot creates is tagged with
`extendedProperties.private.source = "timebox"`.

Right after the mode is chosen in `/timebox`, we list the Target Calendar for
tagged events on the (auto-computed, pinned) Target Date. If any exist, the user
is asked via inline keyboard whether to **Redo** (clear + rewrite) or **Keep
existing** (abort, no collection). On Redo, the tagged events for that date are
deleted before the fresh Schedule is written.

If the Calendar API lacks the means to filter by the private tag for our query,
we fall back to clearing all events on the Target Date — acceptable because the
Target Calendar is dedicated to the bot and never the user's primary calendar.

## Consequences

- Re-running is safe and convergent: a day always ends with exactly one bot
  Schedule, never duplicates.
- Manual (untagged) events on the Target Calendar are never touched in the
  tag-based path.
- The tag is now part of the write contract — every insert must set it, or
  clear-then-write will leak orphans. Changing the tag key later requires a
  migration of already-written events.
- We deliberately rejected deterministic per-slot event IDs (slots change
  between runs, leaving orphans) and accept-duplicates (unusable on retry).
