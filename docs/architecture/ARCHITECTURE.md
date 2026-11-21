# Architecture (as built, not as planned)

| Part | Location | State |
|---|---|---|
| Hand tracking + air-writing (Python, offline) | `backend/app/collection/` | built, 69 tests |
| Same logic in TypeScript (live) | `frontend/src/features/hand-tracking/` | built, 53 tests, shared fixtures |
| REST API (FastAPI): auth, roles, protocol, participants, consent, sessions, uploads, labels, stats | `backend/app/api/routes.py` | built, 20 tests |
| Database models | `backend/app/database/models.py` | built (SQLite tested; PostgreSQL untested; no migrations yet) |
| Security: scrypt hashes, JWT, role checks | `backend/app/security/auth.py` | built |
| Live camera tracking + recognition demo | `web_demo/airwrite.html`, `web_demo/recognizer.js` | built, only syntax-checked in a browser-less environment |
| Standalone pointer-capture page | `web_demo/parkiscribe.html` | built |

## Data flow (API path)
client capture (frames with landmarks + real timestamps) -> `POST /api/recordings/upload` -> `RecordingSession`
(raw JSON + CSV stored first) -> derived strokes/quality written beside raw files -> row in `recordings`.

## Not built
Next.js app, accounts UI, researcher/admin dashboards, dataset export, annotation UI, preprocessing/filters,
kinematic spectral features, synthetic simulator, trained models, NLP decoder, evaluation/statistics/latency modules,
encryption at rest, migrations, deployment config. See `PROGRESS.md`.

## Recognizer
`recognizer.js` is glyph template matching (fonts rendered to 32x32 blurred bitmaps, cosine similarity). It is not
one of the CNN/BiLSTM/Transformer models in the research plan. No such model has been trained.
