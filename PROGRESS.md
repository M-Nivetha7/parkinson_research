# PROGRESS

Last updated: 2026-11-21 (session 1). Honest status against the 12 phases of the master prompt.

## Test status (run at the end of this session)
* Backend: `cd backend && python -m pytest -q` -> **88 passed, 0 failed**
* Frontend core: `cd frontend && npx vitest run` -> **53 passed**; `npx tsc --noEmit` -> clean
* Not run: anything touching a real camera, real video, PostgreSQL, a browser, or a deployed environment.

## Phase 1 - strict-scope repository audit: DONE
Two old files inspected. See `MIGRATION_NOTES.md`.

## Phase 2 - architecture / backend / DB: PARTIAL
Done: FastAPI app, SQLAlchemy models (users, protocols, participants, separate contact table, clinical metadata,
consents, sessions, recordings, label revisions, audit log), scrypt password hashing, JWT auth, backend-enforced roles,
protocol inactive on first install, clinical registration/sessions blocked until an admin activates a protocol with
ethics details, consent checks (version-matched for clinical), withdrawal blocks new collection, label corrections
audited, statistics computed from the DB.
NOT done: Alembic migrations (tables are created with `create_all`), PostgreSQL run (tests use SQLite), encryption at
rest, token revocation / refresh, rate limiting, admin user bootstrap script, Next.js app shell and every page.

## Phase 3 - browser hand tracking: PARTIAL
Done: Python + TypeScript landmark parsing, hand selection, mirrored-input conversion, gesture detection, timestamp
quality, tested on shared constructed fixtures.
NOT done: MediaPipe Tasks Vision wrapper, camera/`getUserMedia` code, `requestVideoFrameCallback` timestamping +
fallback, hosting WASM/model on the app origin (the `hand_landmarker.task` model could not be downloaded in the build
sandbox), skeleton/trajectory canvas, video-clip comparison between TS and Python trackers, numerical tolerances.

## Phase 4 - air-writing & trajectory collection: PARTIAL
Done: raw fingertip samples, strokes, pen-lift, tracking-loss events, recorder with raw JSON/CSV, upload endpoint.
NOT done: Air-Writing Studio UI, rendered trajectory PNG, task prompts UI, recording review page.

## Phases 5-12: NOT STARTED beyond the backend pieces above
Participant/consent UI, dataset export & annotation UI, preprocessing, kinematic features, synthetic simulator,
models, NLP decoder, assistive UI + TTS, dashboards, evaluation/statistics/latency, security hardening, E2E tests,
deployment, remaining docs (ARCHITECTURE, DATA_DICTIONARY, ...), MANUSCRIPT_TRACEABILITY.

No model has been trained. No experimental result of any kind exists yet. Nothing in this repository should be
quoted as a result.

## Known issues / caveats
* Fixtures are constructed hands, not recordings (see MIGRATION_NOTES section 6).
* `extract_from_video` is untested on real video.
* `POST /api/participants/{code}/withdraw` blocks new collection but does not yet delete stored recordings.
* `create_all` is used instead of migrations; do not use for production.

## Exact next steps (in order)
1. `backend/scripts/create_admin.py` (env-driven bootstrap of a `research_admin`) + Alembic initial migration; run the
   API tests against PostgreSQL.
2. Next.js app shell in `frontend/` (App Router, Tailwind): layout, auth pages, protocol banner ("pilot mode"), role
   guards; install `@mediapipe/tasks-vision` and copy its `wasm/` into `public/mediapipe/wasm`.
3. Obtain `hand_landmarker.task` locally and place it in `public/mediapipe/models/` (add a `scripts/fetch_models.sh`
   with checksum); implement `HandTrackerService` using `requestVideoFrameCallback` and the existing `landmarks.ts`
   / `gesture.ts` / `trajectory.ts`; Air-Writing Studio page posting to `/api/recordings/upload`.
4. Record 3-5 short pilot clips (nonclinical volunteers, consent first); extract with `extract_from_video` and the
   browser tracker; document tolerances in `MIGRATION_NOTES.md`.
5. Continue with Phase 5 (UI for consent / participant flows) then Phase 6 onward.
