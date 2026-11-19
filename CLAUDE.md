# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Planner Hub is a single-user, phone-first app for logging tasks, time and paid work shifts (by voice or typing) and rolling them up into weekly/monthly reports and a payroll timesheet. Product spec: [Planner_Hub_Spec_v1.md](Planner_Hub_Spec_v1.md).

Phase 1 (core backend) is built in [backend/](backend/) and deployed. Phase 2 is mostly done: the Gemini fallback for `/log`, `clarify`, `set_mood` and `log_climb` exist. `/voice` is deferred (Siri dictation already transcribes) and `log_application` is dropped: applications will come from the user's existing tracker via `/events`. The iOS Shortcut is a user-built "Dictate Text → POST /log", run through Siri. No Flutter app yet: its screens (Today, Calendar, Schedule, Projects, Week, task/clock-in/sign-in) are designed on a canvas linked from the spec's "App screens" section, still in review. `POST /events` with per-pipeline keys and the repeating schedule (`/schedules`, `/calendar`) are built; Firebase sign-in for the app is live, and the Flutter app (in `frontend/`, built by a separate chat in the `../planner-hub-frontend` worktree) is merged into `main`. The SI weekly plan (`/si-sessions`) is built; next backend work: `GET /projects`.

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

Deployed on Cloud Run: service `planner-api`, project `planner-hub-97a70d`, region `us-east4`, URL https://planner-api-885606868208.us-east4.run.app. Runs as service account `planner-api@planner-hub-97a70d.iam.gserviceaccount.com`, with secrets `planner-database-url` (Neon pooled URL), `planner-api-token`, `planner-gemini-api-key` and `planner-allowed-emails` (the Firebase sign-in allow-list) from Secret Manager. Migrations are not run on boot; run them with `scripts/with-neon.sh` before deploying a schema change. Redeploy from the repo root:

```bash
gcloud run deploy planner-api --project planner-hub-97a70d --source backend --region us-east4 \
  --service-account planner-api@planner-hub-97a70d.iam.gserviceaccount.com \
  --set-secrets DATABASE_URL=planner-database-url:latest,PLANNER_API_TOKEN=planner-api-token:latest,PLANNER_GEMINI_API_KEY=planner-gemini-api-key:latest,PLANNER_ALLOWED_EMAILS=planner-allowed-emails:latest \
  --set-env-vars PLANNER_FIREBASE_PROJECT_ID=planner-hub-97a70d \
  --allow-unauthenticated --min-instances 0 --max-instances 2 --memory 512Mi --cpu-boost
```

Keep-warm: a cold start takes ~8s, longer than Siri waits for the Shortcut. Cloud Scheduler job `planner-keep-warm` (us-east4) GETs `/health` every 10 minutes from 7am to midnight New York, so the server doesn't go cold while the user is awake (`/health` doesn't touch Neon, which still sleeps). With min-instances 0 and request-based billing this stays free; `--cpu-boost` speeds up the cold starts that remain.

`--allow-unauthenticated` only makes the URL reachable; every route but `/health` still requires the bearer token. A $1/month budget alert is set on billing account "Main".

CORS: `CORSMiddleware` in `app/main.py` allows origins full-matching `PLANNER_CORS_ORIGIN_REGEX` (default: any http localhost/127.0.0.1 port, and the two Firebase Hosting domains for `planner-hub-97a70d`), with only the Authorization and Content-Type headers and no credentials.

Tests run against real Postgres: each test is wrapped in an outer transaction that's rolled back, and the app's commits become savepoint releases (see `tests/conftest.py`). Auth (`app/auth.py`, `deps.require_token`): every route except `/health` and `POST /events` takes either the owner token (`PLANNER_API_TOKEN`, used by the Siri Shortcut and admin calls; checked first, so it never calls Google) or a Firebase ID token verified with google-auth (`verify_firebase_token`, audience and issuer = `PLANNER_FIREBASE_PROJECT_ID`) for a verified email in `PLANNER_ALLOWED_EMAILS` (comma-separated; empty = nobody). The user's email is never committed: it's in `backend/.env` locally and the `planner-allowed-emails` secret when deployed. Google's certs are cached via CacheControl. Tests never call Google: `conftest.py` makes `auth._verify_with_google` fail unless a test swaps in a fake. `GET /me` reports the caller.

## Backend layout

- `app/actions/` — the action layer. `base.py` has the registry (`@action(name, ParamsModel)`), `apply_action` and `undo_action`. Handlers return `Outcome(summary, inverse, result)`; `inverse` is a list of `Step(action_type, payload)` replayed by undo (`None` = not undoable). Inverse-only actions (`restore_*`, `delete_category`) are registered with `internal=True` so they won't be exposed as AI tools.
- Undo snapshots reuse the read models in `app/schemas.py` (`TaskOut`, `TimeEntryOut`, `ClimbOut`, `ApplicationOut`, `ContentItemOut`): a delete stores the row's `*Out` dump as the payload of its `restore_*` inverse. Adding a column means adding it to the `*Out` model or undo will silently lose it.
- Each action runs in a savepoint; a failed action leaves no partial writes and no `action_log` row. `ActionError(message, status)` maps directly to the HTTP response.
- `app/routers/` are thin: reads query the DB directly, writes always go through `routers/common.run()` → `apply_action`.
- `app/queries.py` builds `/today` and `/digest/morning` (read-only).
- `POST /log`: `app/actions/journal.py` saves the raw text as a `journal_entries` row, runs the pure parser in `app/quickadd.py` (grammar in its docstring; tested in `tests/test_quickadd.py` with a fixed reference time), then applies each intent via `apply_action` with `journal_entry_id`. Activity words live in `config.ACTIVITIES`; category names match automatically.
- AI fallback: text the parser can't read goes to `app/extract.py` (only when `PLANNER_GEMINI_API_KEY` is set; model from `PLANNER_GEMINI_MODEL`). Tools are hand-written in `extract.TOOLS` (a test checks each field exists on the action's params model); `to_extraction` filters undeclared fields and nulls and repairs known model slips. A `clarify` call applies nothing, is stored on the journal entry, and `POST /clarify/{journal_id}` re-runs extraction with the answer. Provider code lives only in `GeminiExtractor`. Tests never call Gemini: `conftest.py` blanks the key and `tests/test_extract.py` overrides `get_extractor` with a fake. Extraction failures (quota, 503) return `error` and keep the journal entry. The model invents times despite the prompt, so `find_invented_time` checks every `log_time`/timer time against the text (an hour the user said, the moment it was said, or a backed end ± a stated duration); an unbacked time turns the log into a clarify, and the answer counts as backing. `set_mood` writes to the journal entry the text came from (its id is injected, never taken from the model). Each `/log` and `/clarify` writes one `planner.log` line (journal id, via, actions, error) and never the user's text. To check prompt changes, run real samples against Gemini without writing to the DB; the free tier allows roughly 10 requests a minute.
- Climbs: a climbing session is an ordinary time entry in `CLIMBING_CATEGORY` plus an optional `climbs` row (gym, notes; FK cascades). `log_climb` either logs a new session or adds details to an existing entry (`time_entry_id`). Deleting an entry goes through `time_entries.remove_entry` so undo restores its climb too. `GET /climbs` lists every climbing entry, with or without details. In quick-add, a climbing log's note is `[at] <gym>[, notes]`.
- Pipelines: `POST /events` (`app/routers/pipelines.py` `ingest`, outside the owner-token dependency) authenticates with `deps.pipeline_source`: a `pipeline_keys` row (sha256 of the key; returns its source) or the owner token (any source). `app/pipelines.py` validates `data` with a model per (source, type) in `HANDLERS` (must match `config.PIPELINES`; refused events aren't stored), stores the `events` row, then runs the reactor, which applies actions with `event_id` set (`actions/pipelines.py`: `save_application`, `save_content_item`, key create/revoke; plus `create_task`). Same `id` from the same source = duplicate, ignored. `check_missing` (via `POST /pipelines/check`, meant for Cloud Scheduler) marks a 3AM Facts night missing after `FACTS_REPORT_BY_HOUR`. The digest's 3AM Facts and applications lines appear only once that pipeline has reported something.
- Schedules: a `schedules` row is a weekly rule in New York wall-clock time (weekdays 0 = Monday; `end_time` < `start_time` = ends next day). `app/schedule.py` `occurrences()` expands rules for a date range (also the day before, for overnight shifts) and applies `schedule_exceptions` (skipped / moved / done via `time_entry_id`); occurrences are never stored. An occurrence is named by (schedule_id, local start date). `actions/schedules.py` has the rule CRUD and `skip_occurrence` / `move_occurrence` / `confirm_occurrence` (logs via `log_time`, source `calendar`). `/today` and the digest include occurrences as `planned_blocks`.
- SI weekly plan: one `si_sessions` row per Monday (`week_of`, CHECK isodow = 1), written only by `update_si_session` (`actions/si.py`), which upserts: undoing a first save deletes the row (the week reads as defaults again), undoing a later one restores the old values. Read helpers in `app/si.py` (`current_week_of`, `week_or_defaults`, `prep_minutes`) are shared with `/projects`. Prep minutes = time entries with job `si_prep` started in [Monday − 7 days, Monday), New York days.
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

- **Only the action layer writes to Postgres.** Voice, typed text, manual forms, and pipeline webhooks all funnel into the same set of action functions (`create_task`, `complete_task`, `update_task`, `log_time`, `start_timer`/`stop_timer`, `log_climb`, `set_mood`, `clarify`, and the reactions to pipeline events). Manual forms and AI tool calls share these functions.
- **The model never writes to the DB.** It returns tool calls; the action layer validates and applies them. `clarify` applies nothing and surfaces a question on the confirmation card. The model must not invent times/durations — missing info → `clarify`.
- **Every change goes in `action_log` with an `inverse`.** This is what powers per-action undo (`POST /actions/{id}/undo`). Any new action type needs an inverse.
- **Raw input is always kept.** Every voice/typed log creates a `journal_entries` row with the raw transcript, even if extraction yields nothing.
- **`/log` flow:** deterministic quick-add parser first (e.g. `climb 2h vital`, `SI prep 45m`, `tutoring 3-6pm`, `task follow up Traveloka fri`); only unparseable input falls through to Gemini. `/voice` and `/log` return the same response shape.
- **Categories are data, not code.** New areas are rows in `categories` (with `parent_id`, `is_work`, `weekly_target_hours`); don't hardcode category lists.
- **One timeline for all time.** Work shifts are ordinary `time_entries` in an `is_work` category with a `job` field (tutoring, SI sessions, SI prep, restaurant). SI prep counts as paid work.
- **Pipelines push, hub reacts.** External pipelines (3AM Facts, a local nightly script; the job-application tracker, Claude scheduled tasks) post to `POST /events` with their own key (raw inbox in `events` table); the hub creates tasks only for steps needing a human. Pipelines report successes too, so a run that never happened is flagged as missing. The hub monitors them; it doesn't replace them.

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
5. Pipelines and Projects: `/events` for 3AM Facts and the job tracker, missing-run detection, Projects tab, SI checklist and Sunday loop.
6. Later: Calendar sync, Gmail parsing, gap detection, goals/streaks, NL queries.

Out of scope: spending tracking, multiple users. Notification times are settings, not code.
