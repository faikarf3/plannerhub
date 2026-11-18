# Planner Hub — Spec v1

Nov 17, 2026 · @faikar

## Overview

Planner Hub is one phone-first app where every task, work shift and hour of the day gets logged, by voice or by hand, and rolls up into weekly and monthly reports of where the time went.

**Goals**

- One place for tasks across job search, tutoring and SI work, SI prep, climbing, 3AM Facts and school.
- Log anything in under 10 seconds, by voice or manual input, on phone (primary) or laptop.
- Track time on everything, including paid tutoring and SI shifts, and report it by week and month.
- Let existing pipelines (3AM Facts production, job auto-apply) report into the hub on their own.

**v1 scope:** manual and voice logging, tasks, time entries with a live timer, work shifts, configurable categories, daily digest, weekly hours report.

**Later:** Google Calendar sync, Gmail reply parsing, gap detection, goals and streaks, natural-language queries, location triggers.

**Not in scope:** spending tracking, multiple users, a native Android build (the web build covers it).

## Areas tracked

Each area is a configurable category: these are the starting set, and new ones are rows in `categories`, not code changes.

| Category | What gets tracked | How it gets in | Target |
| --- | --- | --- | --- |
| Work: tutoring, SI, restaurant | Paid shifts: clock-in, clock-out, hours per week and pay period | Live timer, voice ("clocking in for tutoring"), recurring shift schedule | Hours per week for the timesheet |
| SI session prep | PH201 weekly plan form, slides, 90-minute breakdown, answer sheet; the Monday session | Recurring weekly template; Sunday-night topic prompt | Materials ready by Monday morning; prep time counts as paid work |
| Job search | Applications, status, follow-ups, replies | Auto-apply pipeline, Gmail parsing, manual | 20 applications a day |
| Climbing | Simple log: date, gym, duration, notes | Voice, manual, timer | None, log only |
| 3AM Facts | Videos moving through the pipeline, review and post tasks, hands-on time | Pipeline events, voice, timer | Morning check that last night's video was created |
| School | Classes, assignments, study time | Class schedule import, manual | None |
| Personal | Rest, commute, social, errands | Voice, manual | None |

Work shifts are time entries in a category flagged `is_work`, with a `job` field (tutoring, SI sessions, SI prep, and restaurant weekends once that job is set). That keeps one timeline for everything while letting the weekly report double as a timesheet.

## Architecture

One FastAPI service on Cloud Run sits between every input and Postgres; nothing writes to the database except the action layer.

&#91;embedded content: planner hub architecture · 4 inputs, 1 action layer, 3 outputs\]

Simple lines go straight from the quick-add parser to the action layer; anything it cannot read goes to Gemini first. Every change is recorded in the action log, which is what makes undo work.

- **Client:** Flutter, one codebase for iOS (primary) and web (laptop).
- **Backend:** FastAPI on Cloud Run; Cloud Scheduler for timed jobs; Firebase Auth and Cloud Messaging.
- **Database:** Postgres (Cloud SQL or a managed equivalent).
- **AI:** Gemini for audio transcription and for extraction (tool use).

## Data model

Three tables carry the core (`tasks`, `time_entries`, `action_log`); the area tables hold only what is specific to each area. Postgres, all timestamps stored in UTC and shown in America/New\_York.

| Table | Key columns | Notes |
| --- | --- | --- |
| `categories` | id, name, color, parent\_id, is\_work, weekly\_target\_hours | Configurable; parent\_id allows sub-categories |
| `tasks` | id, title, category\_id, status (todo, doing, done, skipped), due\_at, scheduled\_start, scheduled\_end, recurrence\_rule, source, linked\_type, linked\_id, completed\_at | linked\_\* points at an area row, e.g. an application |
| `time_entries` | id, category\_id, task\_id, job, started\_at, ended\_at, duration\_min, source (timer, voice, manual, calendar, pipeline), confirmed, note | ended\_at null = the running timer; at most one at a time |
| `applications` | id, company, role, url, status (applied, OA, interview, offer, rejected, ghosted), applied\_at, follow\_up\_at, resume\_version, source | Follow-up task created when follow\_up\_at passes with no reply |
| `si_sessions` | id, week\_of, topic, plan\_form\_done, slides\_url, answer\_sheet\_url, session\_at, attendance | One row per Monday session |
| `climbs` | id, time\_entry\_id, gym, notes | Date and duration come from the linked time entry |
| `content_items` | id, title, stage, posts (jsonb per platform: IG, TikTok, YouTube), pipeline\_run\_id | Stage set by pipeline events |
| `journal_entries` | id, created\_at, input\_type (voice, typed), raw\_text, audio\_url, mood, energy | Raw transcript always kept, even if extraction misses something |
| `action_log` | id, journal\_entry\_id, action\_type, payload, inverse, applied\_at, undone\_at | Every change from any input; inverse powers undo |
| `events` | id, source, type, payload, received\_at, processed\_at | Raw inbox for pipeline webhooks |
| `goals` | id, category\_id, metric (hours, count), period (day, week, month), target | Later phase |

## Input methods

Every input ends in the same action layer, so anything that can be said can also be typed or tapped, and every change can be undone.

**Manual (no AI)**

- Quick-add bar with a small deterministic parser: `climb 2h vital`, `SI prep 45m`, `tutoring 3-6pm`, `task follow up Traveloka fri`.
- Full forms per area for detail (application, climb, shift, task).
- One-tap buttons on the home screen: start/stop timer, clock in/out of work.

**Typed natural language** — the same box; anything the parser cannot read goes to Gemini like a voice note. Useful on the subway.

**Voice**

1. Tap the mic in the app, or run the "Log my day" iOS Shortcut.
2. Audio uploads to `POST /voice`; it is transcribed, then saved as a `journal_entries` row.
3. Gemini receives the transcript plus context (now, open tasks, running timer, today's shifts, categories) and returns actions as tool calls.
4. The hub applies the actions and shows a confirmation card: one line per change, each with undo.
5. Anything ambiguous comes back as a question on the card instead of a guess.

**Offline:** voice notes and quick-adds queue on the phone and send when there is signal; timestamps come from the moment of recording, not upload.

## Time tracking

All time lives in `time_entries`; there are three ways to create one, and work shifts are the same entries with a job attached.

**Three ways in**

1. **Live timer:** tap start/stop, or say "starting SI prep" and later "done". Starting a new timer stops the running one.
2. **After the fact:** "climbed from 2 to 4", "tutored 3 to 6", "about an hour on applications". Vague durations are stored with `confirmed = false` so reports can show them separately.
3. **Confirm the plan:** at the end of the day, scheduled tasks and planned shifts appear as "did this happen?" One tap accepts them as planned; or adjust the times.

**Work shifts (tutoring, SI sessions and prep, restaurant)**

- Clock in/out button on the home screen, plus voice ("clocking in for tutoring", "off work").
- A recurring shift schedule pre-fills planned shifts, so most weeks are confirm-only; irregular shifts (restaurant weekends) are logged by clock-in or voice.
- Weekly timesheet view: hours per job per day, ready to copy into the payroll form.
- A shift left running past its planned end by 30 minutes triggers a push: "Still working?"

**Rules**

- One running timer at a time; overlapping entries are flagged in the evening review, not blocked.
- Durations round to the minute; entries under 2 minutes are dropped as accidental taps.
- Every entry has a category; anything unclear lands in Personal and is listed for review.

**Gap detection (later phase):** the evening digest lists blank stretches over 90 minutes between 8am and 11pm ("3–6pm is empty, what happened?"), answerable by voice.

## Actions and the voice prompt

The model never writes to the database; it returns tool calls, and the action layer validates and applies them. The same functions back the manual forms.

| Tool | Parameters | Effect |
| --- | --- | --- |
| `create_task` | title, category, due\_at?, scheduled\_start?, scheduled\_end? | New task |
| `complete_task` | task\_id, completed\_at? | Marks an existing task done |
| `update_task` | task\_id, fields | Reschedule, rename, change status |
| `log_time` | category, started\_at?, ended\_at?, duration\_min?, task\_id?, job?, note? | Past time entry |
| `start_timer` / `stop_timer` | category, task\_id?, job? / at? | Live timer, including clock in/out |
| `log_climb` | gym, started\_at, ended\_at or duration\_min, notes? | Time entry + climb row |
| `log_application` | company, role, status?, note? | New or updated application |
| `set_mood` | mood 1–5, energy 1–5 | Stored on the journal entry |
| `clarify` | question, options\[\] | Shown on the confirmation card; nothing applied |

**System prompt outline**

```markdown
You turn Faikar's spoken or typed log into planner actions.

Context (injected each call):
- now: <ISO time, America/New_York>
- categories: <names>
- open_tasks: <id, title, category, due>
- running_timer: <category, started_at> or none
- today_shifts: <planned work shifts>

Rules:
- Match mentions to open_tasks by meaning before creating a new task.
- Resolve relative times ("this morning", "from 2 to 4") against now.
- Never invent a time or duration that was not said; if missing, use clarify.
- "Clocking in/out" and named jobs (tutoring, SI sessions, SI prep, restaurant) are work time entries.
- One statement can produce several actions; return all of them.
- If nothing is actionable, return no tools; the journal entry is still kept.
```

## API endpoints

FastAPI, JSON in and out; app clients authenticate with Firebase Auth, pipelines with a per-source API key.

| Method and path | Purpose |
| --- | --- |
| `POST /voice` | Upload audio; returns transcript, applied actions, clarify questions |
| `POST /log` | Typed text; quick-add parser first, Gemini as fallback; same response as /voice |
| `POST /actions/{id}/undo` | Reverse one action from `action_log` |
| `POST /clarify/{journal_id}` | Answer a clarify question; applies the resulting actions |
| `GET /today` | Tasks due, planned shifts, running timer, today's time entries |
| `GET, POST, PATCH /tasks` | Task CRUD |
| `GET, POST, PATCH /time-entries` | Time entry CRUD; `POST /timer/start`, `POST /timer/stop` |
| `POST /shifts/clock-in`, `/clock-out` | Work shortcuts used by the home-screen button and the iOS Shortcut |
| `GET, POST, PATCH /applications`, `/climbs`, `/si-sessions`, `/content` | Area CRUD |
| `POST /events` | Pipeline webhooks (3AM Facts, auto-apply) |
| `GET /reports?period=week\|month&start=` | Hours by category, planned vs actual, area totals |
| `GET /timesheet?start=&end=` | Work hours per job per day |
| `GET /export.csv` | Full time-entry export |

## Integrations

Pipelines push into the hub; the hub only creates tasks for steps that need a person.

**3AM Facts pipeline → `POST /events`**

- Events: `script_generated`, `render_done`, `posted` (with platform and URL), `run_failed`.
- `render_done` creates a "Review tonight's render" task; `run_failed` creates a "Check pipeline" task.
- Morning check: the digest says whether last night's run produced a video. No render by 7am is flagged as missing, with the error from any run\_failed event.

**Job auto-apply → `POST /events`**

- Event `application_submitted` creates an `applications` row; the digest shows the daily count against 20.

**Gmail (later phase)**

- A Cloud Scheduler job polls every 30 minutes for confirmation and reply emails; Gemini classifies each as applied, OA, interview, rejection or other.
- Matched replies update the application's status; OAs and interviews create tasks with the deadline from the email.

**Google Calendar (later phase)**

- Scheduled tasks and planned shifts sync to a dedicated "Planner" calendar.
- Moving an event in Calendar moves the task (two-way sync via push notifications).
- Class schedule imported once per semester as recurring events.

**SI weekly loop**

- Sunday 8pm: push "What's PH201's topic this week?" — the answer by voice or text triggers the existing SI materials workflow.
- Monday: the 90-minute session appears as a planned work shift, confirmed in the evening review.

## Reports and notifications

The weekly report is the payoff: where every hour went, planned against actual, plus work hours ready for the timesheet.

**Reports (in app, week or month)**

- Hours per category, with a trend against the previous 4 weeks or 3 months.
- Planned vs actual per category (scheduled blocks against logged time).
- Work hours per job per day, with week and pay-period totals.
- Area totals: applications sent, replies by type, SI sessions run, climbing sessions and hours, videos posted per platform.
- Unconfirmed and uncategorized time, listed so it can be fixed.
- A short written summary from Gemini: what took the most time, what slipped, one pattern worth noticing.

**Notifications**

| When | What |
| --- | --- |
| Daily, morning | Digest: tasks due, planned shifts, applications vs 20 yesterday, whether last night's 3AM Facts video was created |
| Daily, evening | Check-in: "Tell me about your day" opens straight to recording; then confirm-the-plan cards |
| Sunday, 8pm | SI topic prompt |
| Sunday, evening | Weekly review ready |
| As needed | Shift running past its end, timer running over 4 hours, follow-up due |

Push goes through Firebase Cloud Messaging; Cloud Scheduler triggers the timed jobs. Exact times are settings, not code.

## Roadmap and open questions

Phase 1 is usable on its own within about a week; each later phase adds to the same schema.

1. **Core backend:** schema, action layer with undo, task and time-entry CRUD, timer and clock in/out, morning digest.
2. **Logging:** `/log` quick-add parser, `/voice` with transcription and Gemini tools, the "Log my day" iOS Shortcut.
3. **Flutter app (iOS + web):** today view, mic button, timer and clock-in buttons, confirmation cards, offline queue.
4. **Reports:** weekly and monthly hours, planned vs actual, timesheet view, evening check-in.
5. **Pipelines:** `/events` wired to 3AM Facts and auto-apply; SI Sunday loop.
6. **Later:** Calendar sync, Gmail parsing, gap detection, goals and streaks, natural-language queries, gym location trigger.

**Open questions**

- [ ] Pay period length, so timesheet totals match payroll (to update later).
- [ ] Restaurant weekend job: add its shift pattern once it is confirmed.

**Decided:** SI prep counts as paid work; climbing is log-only with no target; 3AM Facts needs only a morning created-or-missing check; Gemini handles transcription; no other jobs to track beyond tutoring, SI and the restaurant.
