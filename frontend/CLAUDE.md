# frontend/ — Planner Hub app (Flutter, iOS + web)

Built by the "frontend" Claude chat in the git worktree `../planner-hub-frontend` on branch `frontend`. The backend is built by a separate chat in the main checkout; see the root CLAUDE.md and the spec's "App screens" and "API endpoints" sections.

Ownership while both chats run:
- This chat edits only `frontend/**`. It never edits `backend/**`, the root `CLAUDE.md` or the spec, never deploys the backend, never runs backend tests (they reset `planner_hub_test`), and never runs `git checkout` in the main checkout.
- API changes the app needs go through the user to the backend chat. The backend only makes additive changes to response shapes.

Design: very simple, white background, near-black text (Inter), red (#D92D20) only as an accent: mic, running timer, paid work, primary actions, undo. Canvas: https://claude.ai/artifact/G5kE9ExgkNLV7kBJxYTKp7.

Commands (from `frontend/`):

```bash
flutter run -d chrome        # web
flutter run -d ios           # iOS simulator
flutter analyze
flutter test
```
