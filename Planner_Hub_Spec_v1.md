# Planner Hub — Spec v1

Nov 17, 2026 · updated Nov 19, 2026 · @faikar

## Overview

Planner Hub is one phone-first app where every task, work shift and hour of the day gets logged, by voice or by hand, and rolls up into weekly and monthly reports of where the time went.

**Goals**

- One place for tasks across job search, tutoring and SI work, SI prep, climbing, 3AM Facts and school.
- Log anything in under 10 seconds, by voice or manual input, on phone (primary) or laptop.
- Track time on everything, including paid tutoring and SI shifts, and report it by week and month.
- Let existing pipelines (3AM Facts production, the job-application tracker) report into the hub on their own, and monitor them, plus the SI weekly lesson plan, from one Projects tab.

**v1 scope:** manual and voice logging, tasks, time entries with a live timer, work shifts, a repeating weekly schedule, configurable categories, daily digest, weekly hours report, and the Projects tab.

**Later:** Google Calendar sync, Gmail reply parsing, gap detection, goals and streaks, natural-language queries, location triggers.

**Not in scope:** spending tracking, multiple users, a native Android build (the web build covers it).

## Areas tracked

Each area is a configurable category: these are the starting set, and new ones are rows in `categories`, not code changes.

| Category | What gets tracked | How it gets in | Target |
| --- | --- | --- | --- |
| Work: tutoring, SI, restaurant | Paid shifts: clock-in, clock-out, hours per week and pay period | Live timer, voice ("clocking in for tutoring"), repeating weekly schedule | Hours per week for the timesheet |
| SI session prep | PH201 weekly plan form, slides, 90-minute breakdown, answer sheet; the Monday session | Checklist on the Projects tab (manual, no pipeline); Sunday-night topic prompt | Materials ready by Monday 9am; prep time counts as paid work |
| Job search | Applications, status, follow-ups, replies | Events from the user's own application tracker (runs as Claude scheduled tasks); Gmail parsing later. No manual application logging in the hub | 20 applications a day |
| Climbing | Simple log: date, gym, duration, notes | Voice, manual, timer | None, log only |
| 3AM Facts | Nightly video runs: created, posted per platform, failed or missing; hands-on time | Events from the nightly script (runs locally on the user's Mac), voice, timer | Morning check that last night's video was created |
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
| `schedules` | id, title, category\_id, job, weekdays (0 = Mon … 6 = Sun), start\_time, end\_time (earlier than start = ends next day), starts\_on, until (null = no end), note | Built. Repeating weekly blocks in New York wall-clock time; expanded into planned blocks on the calendar, not stored per week |
| `schedule_exceptions` | id, schedule\_id, on\_date, skipped, started\_at, ended\_at, time\_entry\_id | Built. One week that differs from its rule: skipped, moved, or done (linked to the time entry that logged it). Deleting that entry makes the block planned again |
| `applications` | id, company, role, url, status (applied, OA, interview, offer, rejected, ghosted), applied\_at, follow\_up\_at, source | Written only from tracker events (no manual logging); follow-up task created when follow\_up\_at passes with no reply |
| `si_sessions` | id, week\_of, topic, plan\_form\_done, slides\_done, breakdown\_done, answer\_sheet\_done, session\_at, attendance | One row per Monday session; the four flags are the Projects-tab checklist |
| `climbs` | id, time\_entry\_id (unique, cascades), gym, notes | Built. Date and duration come from the linked time entry; a climbing entry with no row still counts as a session |
| `content_items` | id, run\_date, title, status (created, posted, failed, missing), posts (jsonb per platform: Instagram, TikTok, YouTube), error | One row per night, from 3AM Facts events; "missing" is set by the hub when no event arrives by 7am |
| `journal_entries` | id, created\_at, input\_type (voice, typed), raw\_text, audio\_url, mood, energy, clarify\_question, clarify\_answer | Raw transcript always kept, even if extraction misses something; an open clarify question waits here |
| `action_log` | id, journal\_entry\_id, action\_type, payload, inverse, applied\_at, undone\_at | Every change from any input; inverse powers undo |
| `events` | id, source, type, payload, occurred\_at, received\_at, processed\_at | Raw inbox for pipeline webhooks; reactions (rows, tasks) go through the action layer |
| `pipeline_keys` | id, source, key\_hash, created\_at, revoked\_at | One key per pipeline; a key can only post events for its own source |
| `goals` | id, category\_id, metric (hours, count), period (day, week, month), target | Later phase |

## Input methods

Every input ends in the same action layer, so anything that can be said can also be typed or tapped, and every change can be undone.

**Manual (no AI)**

- Quick-add bar with a small deterministic parser: `climb 2h vital`, `SI prep 45m`, `tutoring 3-6pm`, `task follow up Traveloka fri`.
- Full forms for detail (task, time block, repeating schedule, climb, shift).
- One-tap buttons on the home screen: start/stop timer, clock in/out of work.

**Typed natural language** — the same box; anything the parser cannot read goes to Gemini like a voice note. Useful on the subway.

**Voice**

Today (built): "Hey Siri, log it" runs an iOS Shortcut that dictates with Apple's on-device transcription and sends the text to `POST /log`; Siri reads back the reply and can answer a clarify question by voice. `/voice` (audio upload) is deferred until the app has its own mic button.

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
- A repeating weekly schedule (`schedules`, edited on the Schedule screen: what, which days, start and end, until when) pre-fills planned shifts, so most weeks are confirm-only; irregular shifts are logged by clock-in or voice. One week can be skipped or changed from its calendar block without touching the rule.
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
| `log_climb` | gym?, notes?, started\_at / ended\_at / duration\_min, or time\_entry\_id | Time entry + climb row; with time\_entry\_id, adds gym and notes to an existing climbing entry (built) |
| `set_mood` | mood 1–5, energy 1–5 | Stored on the journal entry the text came from (built) |
| `clarify` | question, options\[\] | Shown on the confirmation card; nothing applied |

`log_application` was dropped: applications come only from the tracker's events. The model invents times despite the prompt, so the server checks every time it returns against what was said (an hour the user named, the moment it was said, or a stated duration from either); an unbacked time turns into a clarify question instead of being saved.

**System prompt outline**

```markdown
You turn Faikar's spoken or typed log into planner actions.

Context (injected each call):
- now: <ISO time, America/New_York>
- categories: <names>
- work categories and jobs
- open_tasks: <id, title, category, due>
- running_timer: <#id, category, started_at> or none
- recent_entries: <#id, category, start-end> for the last 24 hours (late-night logs cross midnight)

Rules:
- Match mentions to open_tasks by meaning before creating a new task.
- Resolve relative times ("this morning", "from 2 to 4") against now.
- Never invent a time or duration that was not said; if missing, use clarify.
- "Clocking in/out" and named jobs (tutoring, SI sessions, SI prep, restaurant) are work time entries.
- One statement can produce several actions; return all of them.
- If nothing is actionable, return no tools; the journal entry is still kept.
```

## API endpoints

FastAPI, JSON in and out. Every request sends `Authorization: Bearer <token>`, where the token is one of: a Firebase ID token (the app; accepted only for a verified email on the `PLANNER_ALLOWED_EMAILS` list, for Firebase project `planner-hub-97a70d`), the owner token (Siri Shortcut and admin calls), or, on `POST /events` only, a pipeline's own key. A refusal is a 401 whose `message` says why (expired sign-in, different project, email not verified or not allowed…); a 503 means Google couldn't be reached to check a sign-in.

Browsers may call the API from any `http://localhost` or `http://127.0.0.1` port (development) and from `https://planner-hub-97a70d.web.app` / `.firebaseapp.com` (Firebase Hosting); the list is the `PLANNER_CORS_ORIGIN_REGEX` setting. Auth is a bearer header, never cookies.

| Method and path | Purpose |
| --- | --- |
| `GET /me` | Who the request is signed in as: `{"auth": "owner"|"firebase", "email", "uid"}` (built) |
| `POST /voice` | Upload audio; returns transcript, applied actions, clarify questions |
| `POST /log` | Typed text; quick-add parser first, Gemini as fallback; same response as /voice |
| `POST /actions/{id}/undo` | Reverse one action from `action_log` |
| `POST /clarify/{journal_id}` | Answer a clarify question; applies the resulting actions |
| `GET /today` | Tasks due, planned shifts, running timer, today's time entries |
| `GET, POST, PATCH /tasks` | Task CRUD |
| `GET, POST, PATCH /time-entries` | Time entry CRUD; `POST /timer/start`, `POST /timer/stop` |
| `POST /shifts/clock-in`, `/clock-out` | Work shortcuts used by the home-screen button and the iOS Shortcut |
| `GET, POST /climbs` | Climbing sessions (built) |
| `GET, POST, PATCH, DELETE /schedules` | Repeating weekly blocks; the list includes minutes per week and the weekly paid total (built) |
| `POST /schedules/{id}/occurrences/{date}/skip`, `/move`, `/confirm` | Change one week only: skip it, move it, or mark it done (logs a time entry at the planned times unless others are given) (built) |
| `GET /calendar?start=&end=` | Logged entries, planned blocks from repeats (planned, done; skipped on request) and one-off scheduled tasks for local days start..end; default this Monday to Sunday (built) |
| `GET /projects` | One summary per project card: job search counts and items needing the user, last 3AM Facts run, SI checklist |
| `GET /applications?status=`, `GET /content` | Project detail pages, read-only: pipelines write them through events (built) |
| `GET /si-sessions/current` | This week's SI plan (today if Monday, otherwise next Monday, New York): topic, the four checklist flags, `session_at`, `attendance`, and `prep_minutes_this_week` (SI prep logged in the 7 days before that Monday; a running prep timer counts to now). With nothing saved yet it returns the defaults with `"id": null` (built) |
| `PATCH /si-sessions/{week_of}` | Create or update one week (`week_of` must be a Monday) with any subset of topic, `plan_form_done`, `slides_done`, `breakdown_done`, `answer_sheet_done`, `session_at`, `attendance`; undoable; returns the usual action reply (built) |
| `POST /events` | Pipeline webhooks (3AM Facts, job tracker), authenticated with that pipeline's own key (built) |
| `GET /events?source=` | Recent raw events, newest first (built) |
| `GET, POST /pipeline-keys`, `DELETE /pipeline-keys/{id}` | Create a key for one pipeline (shown once), list keys by hint, revoke (built) |
| `POST /pipelines/check` | Called by Cloud Scheduler each morning: marks a 3AM Facts night missing if nothing reported by 7am (built) |
| `GET /reports?period=week\|month&start=` | Hours by category, planned vs actual, area totals |
| `GET /timesheet?start=&end=` | Work hours per job per day |
| `GET /export.csv` | Full time-entry export |

## Integrations

Pipelines push into the hub; the hub only creates tasks for steps that need a person. The pipelines keep doing the work; the hub is their only dashboard (neither has its own), shown on the Projects tab.

**Rules for every pipeline**

- Report successes as well as failures. A pipeline that never ran can't report a failure, so the hub flags silence: an expected event that hasn't arrived by its deadline becomes "missing".
- Each pipeline gets its own key (`pipeline_keys`), separate from the app's sign-in; a leaked key can only post events for that source.
- Request shape: `POST /events` with `Authorization: Bearer <pipeline key>` and `{"type", "data": {...}, "id"?, "occurred_at"?, "source"?}`. `source` comes from the key (the owner token may post for any source by naming it). `id` is the sender's own id for the event: a retry with the same id is ignored. `occurred_at` defaults to when it arrived; 3AM Facts nights are dated by its New York date (or `data.run_date`).
- A wrong type or missing field is refused with 422 and not stored. Otherwise the raw event is stored first, then its reactions go through the action layer like any other change (each undoable, and `action_log.event_id` points back at the event). The reply says what was done in `message`.

**3AM Facts (nightly script on the user's Mac) → `POST /events`**

- Events: `video_created` (title, url), `posted` (platform, url), `run_failed` (step, error).
- `run_failed` creates a "Fix 3AM Facts run" task due today, with the step and error.
- No `video_created` by 7am marks the night as missing (the Mac may have been asleep or offline); the morning digest says so and a task is added.
- The script sends its events with one `curl` call at the end of each step.

**Job-application tracker (Claude scheduled tasks) → `POST /events`**

- Events: `application_submitted` (company, role, url), `reply_received` (company, role?, kind: rejection, oa, interview, offer; deadline if any), `run_finished` (count submitted), `run_failed` (error).
- A reply matches the application with the same company (and role, if given; otherwise the most recent one), ignoring case. An unknown company creates the application.
- `application_submitted` creates an `applications` row; the digest and the Projects card show today's count against 20.
- `reply_received` updates the application's status; an OA or interview creates a task with its deadline.
- `run_failed`, or no `run_finished` on a day the tracker should run, creates a task.

**SI weekly plan (manual, no pipeline)**

- The Projects tab holds this week's checklist (plan form, slides, 90-minute breakdown, answer sheet), the topic, and prep time logged.
- Anything unchecked by Sunday night becomes a reminder; materials are due Monday 9am.

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

## App screens

Design canvas (in review): https://claude.ai/artifact/G5kE9ExgkNLV7kBJxYTKp7. The look is very simple: white background, near-black text (Inter), and red only as an accent (mic button, running timer, paid work, primary actions, undo).

**Tabs (bottom bar):** Today · Calendar · Projects · Week.

| Screen | What it does |
| --- | --- |
| Today | Running timer with Stop, or an idle card with Start timer and Clock in; tasks due with a "+" to add; today's log with a total; log box and red mic at the bottom |
| After logging | Panel listing what was said and one line per change, each with Undo |
| Follow-up question | The clarify question with suggested answers and a mic to answer by voice; nothing is saved until answered |
| Calendar | Week grid, all 24 hours (scrolls, opens at 7am). Logged time is solid (pale red for paid work, grey otherwise), planned time is dashed, a red line marks now. Tap a block to edit or delete it, or mark a planned one done; tap an empty spot to plan or log time there |
| Schedule (from Calendar) | Repeating weekly blocks with weekly paid-hours total; edit what, days, start and end (overnight allowed), and until when |
| Edit task | Title, category, due shortcuts plus date and time, note; Mark done, Save, Delete |
| Clock in | Pick the job, start now or earlier; warns when it will stop a running timer |
| Projects | Cards for Job search (today vs 20, items needing you), 3AM Facts (last night's run and where it posted), SI weekly plan (topic, checklist progress, next session) |
| Job search | Today / this week / replies, items needing you, application list with status filter |
| 3AM Facts | Last 7 nights: posted, failed (with the error) or missing |
| SI weekly plan | Topic, the four-item checklist, prep time this week with a Start prep button |
| Week | Hours per category (paid work in red), timesheet per job with Copy for payroll |
| Sign in | Continue with Apple or Google (Firebase Auth) |

Later screens: journal and history, settings (categories, targets, notification times, pay period), morning digest and evening check-in, climbing log, a wider laptop layout, empty and offline states.

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
| Daily, morning | Digest: tasks due, planned shifts, applications vs 20 yesterday, whether last night's 3AM Facts video was created (or failed, or never reported) |
| Sunday, night | SI materials still unchecked |
| Daily, evening | Check-in: "Tell me about your day" opens straight to recording; then confirm-the-plan cards |
| Sunday, 8pm | SI topic prompt |
| Sunday, evening | Weekly review ready |
| As needed | Shift running past its end, timer running over 4 hours, follow-up due |

Push goes through Firebase Cloud Messaging; Cloud Scheduler triggers the timed jobs. Exact times are settings, not code.

## Roadmap and open questions

Phase 1 is usable on its own within about a week; each later phase adds to the same schema.

1. **Core backend (done, deployed):** schema, action layer with undo, task and time-entry CRUD, timer and clock in/out, morning digest.
2. **Logging (done, except `/voice`):** `/log` quick-add parser, Gemini fallback with clarify and the invented-time check, `set_mood`, `log_climb`, the Siri Shortcut. `/voice` waits for the app's mic.
3. **Flutter app (iOS + web):** design in review (see App screens). Firebase sign-in, Today, Calendar with editing, repeating schedule, task and clock-in screens, confirmation cards, offline queue.
4. **Reports:** weekly and monthly hours, planned vs actual, timesheet view, evening check-in.
5. **Pipelines and Projects:** `/events` with per-pipeline keys, wired to 3AM Facts and the job tracker; missing-run detection; Projects tab; SI checklist and Sunday loop.
6. **Later:** Calendar sync, Gmail parsing, gap detection, goals and streaks, natural-language queries, gym location trigger.

**Open questions**

- [ ] Pay period length, so timesheet totals match payroll (to update later).
- [ ] Restaurant weekend job: add its shift pattern once it is confirmed (the design uses Sat–Sun 5pm–1am as a placeholder).
- [ ] Which days the job tracker should run, so a missing run can be flagged.

**Decided:** SI prep counts as paid work; climbing is log-only with no target; 3AM Facts needs only a morning created-or-missing check; Gemini handles transcription and extraction; no other jobs to track beyond tutoring, SI and the restaurant. Applications are not logged in the hub, only received from the tracker. Pipelines report successes too, so silence can be flagged. The Projects tab monitors pipelines rather than replacing them. Siri dictation stands in for `/voice` until the app exists.
