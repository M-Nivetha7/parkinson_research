# ParkiScribe

Contactless air-writing platform for assistive-communication research. **Research prototype. Not a diagnostic system.**
Early build: see `PROGRESS.md` for exactly what exists and what does not. No model has been trained and there are no
experimental results.

## Run the tests
```bash
cd backend && pip install -r requirements.txt && python -m pytest -q
cd ../frontend && npm install && npx vitest run && npx tsc --noEmit
```

## Run the API (dev)
```bash
cd backend
export JWT_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"
uvicorn app.main:app --reload --port 8000     # docs at http://localhost:8000/docs
```
On first install the research protocol is inactive: only nonclinical **pilot mode** is available.

## Layout
`backend/app/collection/` hand tracking + air-writing (Python, offline/validation) ·
`frontend/src/features/hand-tracking/` same logic in TypeScript (live) ·
`backend/tests/fixtures/` shared constructed fixtures · `MIGRATION_NOTES.md` · `PROGRESS.md`
