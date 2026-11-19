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

Notes:
- Firebase is pinned to `firebase_core 4.2.0` / `firebase_auth 6.1.0`: newer releases need a newer Flutter than the installed 3.35 (`FlutterSceneLifeCycleDelegate`). Unpin after upgrading Flutter.
- CocoaPods needs a UTF-8 locale: `export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8` before `pod install`.
- Dev token: create `frontend/dev.json` (gitignored) as `{"PLANNER_TOKEN": "<owner token>"}` and run with `--dart-define-from-file=dev.json`. Without it the app shows the Google sign-in screen, which only works once the backend accepts Firebase tokens.
- Firebase (project `planner-hub-97a70d`): iOS app `com.plannerhub.plannerHub` and a web app are registered; `lib/firebase_options.dart` holds their public identifiers. Google sign-in must be enabled in the Firebase console (Authentication > Sign-in method). The iOS URL scheme in Info.plist (`app-1-885606868208-ios-…`) is what brings sign-in back to the app.
- CORS is live on the backend, so `flutter run -d chrome --dart-define-from-file=dev.json` works against the deployed API.
- Auth errors (backend contract): a 401 mentioning "expired" gets one retry with `getIdToken(true)`; any other 401 calls `Auth.rejected`, which signs out and shows the server's message on the sign-in screen; 503 is retried with backoff. After Google sign-in the app calls `GET /me` to confirm the account is allowed. Apple sign-in isn't offered yet (needs a paid Apple Developer account).
