# Context Glossary

Canonical terms for this codebase. Definitions only — no implementation detail.

## Timebox Session
A `/timebox` conversation where the user sends next-day tasks one per message,
then `/done` produces a timeboxed **Schedule** for the **Target Date**.

## Target Date
The single day a Timebox Session plans for: tomorrow in the user's timezone, or
the current day if `/done` runs before the late-night cutoff hour.

## Schedule
The ordered set of non-overlapping time slots produced for the Target Date,
plus any tasks dropped because they did not fit.

## Target Calendar
The specific Google Calendar the bot writes Schedule events into, identified by
its **Calendar ID**. Never the user's primary calendar. Configurable.

## Calendar ID
Google's identifier for a calendar (e.g. `...@group.calendar.google.com`). The
write target — not a public/iCal URL, which is read-only.
