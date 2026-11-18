# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Planner Hub is a single-user, phone-first app for logging tasks, time and paid work shifts (by voice or typing) and rolling them up into weekly/monthly reports and a payroll timesheet. Product spec: [Planner_Hub_Spec_v1.md](Planner_Hub_Spec_v1.md).

Phase 1 (core backend) is built in [backend/](backend/) and deployed. Phase 2 is in progress: the Gemini fallback for `/log` and `clarify` exist; `/voice`, `log_climb`, `log_application`, `set_mood` and the iOS Shortcut don't yet. No Flutter app.

## Commands

All from `backend/`. Requires local Postgres (Homebrew `postgresql@17`) with databases `planner_hub` and `planner_hub_test`; config is read from `backend/.env` (see `.env.example`, vars prefixed `PLANNER_`).

```bash
uv run uvicorn app.main:app --reload          # dev server; docs at /docs
uv run pytest                                 # all tests (migrates planner_hub_test from scratch)
uv run pytest tests/test_time.py::test_stop_and_undo   # single test
uv run ruff check app tests                   # lint
uv run alembic upgrade head                   # migrate dev DB
uv run alembic revision --autogenerate -m "..."  # new migration; review the generated file
```

Production DB is Neon (project `steep-surf-64403400`). `neon init` wrote its connection strings to the repo-root `.env.local` (gitignored; never print its values). Local dev stays on local Postgres because `PLANNER_DATABASE_URL` in `backend/.env` takes priority over Neon's `DATABASE_URL`. To act on Neon deliberately, prefix the command: `scripts/with-neon.sh uv run alembic upgrade head` (uses the direct, unpooled URL for migrations). Deployed, only `DATABASE_URL` is set.

Deployed on Cloud Run: service `planner-api`, project `planner-hub-97a70d`, region `us-east4`, URL https://planner-api-885606868208.us-east4.run.app. Runs as service account `planner-api@planner-hub-97a70d.iam.gserviceaccount.com`, with secrets `planner-database-url` (Neon pooled URL) and `planner-api-token` from Secret Manager. Migrations are not run on boot; run them with `scripts/with-neon.sh` before deploying a schema change. Redeploy from the repo root:

```bash
gcloud run deploy planner-api --project planner-hub-97a70d --source backend --region us-east4 \
  --service-account planner-api@planner-hub-97a70d.iam.gserviceaccount.com \
  --set-secrets DATABASE_URL=planner-database-url:latest,PLANNER_API_TOKEN=planner-api-token:latest \
  --allow-unauthenticated --min-instances 0 --max-instances 2 --memory 512Mi
```

`--allow-unauthenticated` only makes the URL reachable; every route but `/health` still requires the bearer token. A $1/month budget alert is set on billing account "Main".

Tests run against real Postgres: each test is wrapped in an outer transaction that's rolled back, and the app's commits become savepoint releases (see `tests/conftest.py`). Auth is a single bearer token (`PLANNER_API_TOKEN`) on every route except `/health`; Firebase Auth replaces it when the app arrives.

## Backend layout

- `app/actions/` — the action layer. `base.py` has the registry (`@action(name, ParamsModel)`), `apply_action` and `undo_action`. Handlers return `Outcome(summary, inverse, result)`; `inverse` is a list of `Step(action_type, payload)` replayed by undo (`None` = not undoable). Inverse-only actions (`restore_*`, `delete_category`) are registered with `internal=True` so they won't be exposed as AI tools.
- Undo snapshots reuse the read models in `app/schemas.py` (`TaskOut`, `TimeEntryOut`): a delete stores the row's `*Out` dump as the payload of its `restore_*` inverse. Adding a column means adding it to the `*Out` model or undo will silently lose it.
- Each action runs in a savepoint; a failed action leaves no partial writes and no `action_log` row. `ActionError(message, status)` maps directly to the HTTP response.
- `app/routers/` are thin: reads query the DB directly, writes always go through `routers/common.run()` → `apply_action`.
- `app/queries.py` builds `/today` and `/digest/morning` (read-only).
- `POST /log`: `app/actions/journal.py` saves the raw text as a `journal_entries` row, runs the pure parser in `app/quickadd.py` (grammar in its docstring; tested in `tests/test_quickadd.py` with a fixed reference time), then applies each intent via `apply_action` with `journal_entry_id`. Activity words live in `config.ACTIVITIES`; category names match automatically.
- AI fallback: text the parser can't read goes to `app/extract.py` (only when `PLANNER_GEMINI_API_KEY` is set; model from `PLANNER_GEMINI_MODEL`). Tools are hand-written in `extract.TOOLS` (a test checks each field exists on the action's params model); `to_extraction` filters undeclared fields and nulls and repairs known model slips. A `clarify` call applies nothing, is stored on the journal entry, and `POST /clarify/{journal_id}` re-runs extraction with the answer. Provider code lives only in `GeminiExtractor`. Tests never call Gemini: `conftest.py` blanks the key and `tests/test_extract.py` overrides `get_extractor` with a fake. Extraction failures (quota, 503) return `error` and keep the journal entry.
- `app/config.py` `JOBS` maps each work job to the category clock-in uses by default.
- Datetimes: input fields use `AwareDatetime` from `app/timeutil.py` (naive = New York local, converted to UTC); output models serialize in UTC.

## Planned stack

- **Backend:** FastAPI (Python) on Cloud Run; Cloud Scheduler for timed jobs (digests, prompts, Gmail polling later).
- **DB:** Postgres. Store all timestamps in UTC; display in `America/New_York`.
- **Client:** Flutter, one codebase for iOS (primary) and web (laptop). No native Android.
- **Auth/push:** Firebase Auth for app clients, per-source API keys for pipelines, Firebase Cloud Messaging for push.
- **AI:** Gemini for audio transcription and for extracting actions from transcripts/typed text (tool use).

## Architecture invariants

These cut across the whole system and must hold in every feature:

- **Only the action layer writes to Postgres.** Voice, typed text, manual forms, and pipeline webhooks all funnel into the same set of action functions (`create_task`, `complete_task`, `update_task`, `log_time`, `start_timer`/`stop_timer`, `log_climb`, `log_application`, `set_mood`, `clarify`). Manual forms and AI tool calls share these functions.
- **The model never writes to the DB.** It returns tool calls; the action layer validates and applies them. `clarify` applies nothing and surfaces a question on the confirmation card. The model must not invent times/durations — missing info → `clarify`.
- **Every change goes in `action_log` with an `inverse`.** This is what powers per-action undo (`POST /actions/{id}/undo`). Any new action type needs an inverse.
- **Raw input is always kept.** Every voice/typed log creates a `journal_entries` row with the raw transcript, even if extraction yields nothing.
- **`/log` flow:** deterministic quick-add parser first (e.g. `climb 2h vital`, `SI prep 45m`, `tutoring 3-6pm`, `task follow up Traveloka fri`); only unparseable input falls through to Gemini. `/voice` and `/log` return the same response shape.
- **Categories are data, not code.** New areas are rows in `categories` (with `parent_id`, `is_work`, `weekly_target_hours`); don't hardcode category lists.
- **One timeline for all time.** Work shifts are ordinary `time_entries` in an `is_work` category with a `job` field (tutoring, SI sessions, SI prep, restaurant). SI prep counts as paid work.
- **Pipelines push, hub reacts.** External pipelines (3AM Facts, job auto-apply) post to `POST /events` (raw inbox in `events` table); the hub creates tasks only for steps needing a human.

## Time-entry rules

- `ended_at IS NULL` = running timer; at most one at a time (enforced by the partial unique index `uq_time_entries_one_running`). Starting a new timer stops the running one.
- Overlapping entries are flagged in the evening review, not blocked.
- Round durations to the minute; drop entries under 2 minutes.
- Vague durations ("about an hour") are stored with `confirmed = false` and reported separately.
- Every entry needs a category; unclear ones go to Personal and are listed for review.
- Offline-queued inputs use the recording timestamp, not upload time.

## Build order (from spec roadmap)

1. Core backend: schema, action layer with undo, task/time-entry CRUD, timer + clock in/out, morning digest.
2. Logging: `/log` quick-add parser, `/voice` with transcription + Gemini tools, iOS Shortcut.
3. Flutter app: today view, mic, timer/clock-in buttons, confirmation cards, offline queue.
4. Reports: weekly/monthly hours, planned vs actual, timesheet, evening check-in.
5. Pipelines: `/events` for 3AM Facts and auto-apply; SI Sunday loop.
6. Later: Calendar sync, Gmail parsing, gap detection, goals/streaks, NL queries.

Out of scope: spending tracking, multiple users. Notification times are settings, not code.
