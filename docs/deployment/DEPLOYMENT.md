# Deployment (development only so far)

Local API: see `README.md`. Required env: `JWT_SECRET` (32+ chars). Optional: `DATABASE_URL`
(default SQLite file), `PARKISCRIBE_DATA_DIR`, `CORS_ORIGINS`. First staff account:
`cd backend && ADMIN_PASSWORD=... python -m scripts.create_admin --email you@example.com`.

Local web demo: `cd web_demo && python3 -m http.server 8080`, open `/airwrite.html`.

Production is NOT prepared: no Dockerfile, no migrations (tables come from `create_all`), no TLS, no PostgreSQL run.
If the frontend is later hosted on Vercel, connect WebSockets directly to the separately hosted Python backend, and host
the MediaPipe WASM and model files on the app's own origin (the demo currently loads them from jsDelivr / Google).
