# Deployment audit for HOMS / UEMS Enterprise Management Ecosystem

Date: 2026-10-31
Context: find what must change before static cloud hosting (frontend on a CDN/static host, backend on a long-lived Python host, managed PostgreSQL).

## 1. Project layout (what I found)

- Frontend app root: `frontend/` — Next.js app with server and client components.
  - `frontend/package.json`, `frontend/next.config.ts`, `frontend/.env.example`, `frontend/Dockerfile`.
- Backend app root: `backend/` — Django + DRF project.
  - `backend/manage.py`, `backend/requirements.txt`, `backend/Dockerfile`, `backend/entrypoint.sh`, `backend/uems_config/` (settings / urls / wsgi / asgi).
  - Apps: `core`, `inventory`, `attendance`, `fleet`, `reports`, `payroll`, `nemt`, `medicine_delivery`.
  - Virtualenv in repo: `backend/.venv/` (exists locally).
- Cross-cutting docs and scripts: `Dockerfile` at repo root for one container, `docker-compose.yml`, `scripts/start.ps1`, `.env.example`, plus per-component `.env.example` files.

Deployment target from the brief:
- Frontend: Vercel-style static/optimized build.
- Backend: Render-style Python web service.
- Database: managed PostgreSQL.
- Domains are examples; the important thing is that they are configurable.

## 2. Frontend findings

Entry and build tooling:
- Next.js project in `frontend/`.
- `frontend/package.json` controls dependencies and likely build scripts.
- `frontend/next.config.ts` is the Next config.

Runtime configuration:
- Frontend calls backend through a client-side configuration point rather than only build-time constants.
- Relevant file: `frontend/lib/api.ts`.
- Frontend login page persists a chosen backend URL in localStorage and refreshes the axios base.
- Relevant file: `frontend/app/login/page.tsx`.

Releases and proxy behavior:
- `frontend/next.config.ts` can rewrite `/api/v1` when an internal proxy target is configured.
- This is a local/dev convenience, not required by the cloud target if the browser talks directly to the deployed backend on the same top-level domain or an allowed CORS origin.

Files that must not be required at cloud runtime:
- No persistent client-side filesystem dependency for uploads or report storage was found in the frontend path being used by the backend flows. Report generation uses in-memory export code on the backend side (`backend/reports/exporters.py`).

Potential blockers / things to verify before Vercel:
- Make sure the production API URL is wired through environment variables, not hardcoded localhost.
- Verify no server-side backend calls depend on a local filesystem path only available during development.
- Confirm protected routes still guard correctly after a production deployment, including the inventory workspace and report downloads.
- Confirm build command, public output directory, and framework detection match the hosting platform.

Open items:
- I have not yet validated the exact production build command output against Vercel expectations in this session.

## 3. Backend findings

Framework:
- Django + DRF.
- ASGI and WSGI entry points both exist in `backend/uems_config/`.
- `backend/uems_config/settings.py` is the settings module.
- Authentication uses JWT (SimpleJWT + JWT blacklist).

Server and process model:
- Production web process should use Gunicorn (or equivalent) through the WSGI application.
- `backend/Dockerfile` and `backend/entrypoint.sh` show a container-style build/migration flow.
- `backend/requirements.txt` lists Python dependencies.
- `backend/.env.example` documents expected environment variables.

Static files:
- Static and media settings exist in `backend/uems_config/settings.py`.
- There is a staticfiles directory model (`STATIC_ROOT` into `staticfiles`).
- Whitenoise-style serving is compatible with a single-host Python deployment.
- Current settings still define `MEDIA_URL`/`MEDIA_ROOT` and `STATIC_URL`/`STATIC_ROOT` from environment variables.

Health endpoint:
- A backend health/readiness endpoint is desirable for Render-style health checks.
- At the time of this audit, a dedicated health view was not found in the backends main URL surface under a conventional `/health` path.
- `backend/core/views.py` exists and should be checked for or extended with a lightweight health view.

Background work:
- No Celery / beat / scheduled-task infrastructure was found in the project code being deployed.
- No channels/websocket application is in active use for the main flows I inspected.
- QR and attendance verification use normal request/response API endpoints.

Authentication / cross-origin:
- Settings distinguish backend CORS, CSRF/trusted origins, frontend base URL, and public API base URL.
- Production hardening should be verified to kick in when debug is off.
- The deployed frontend and backend will likely be on different origins unless the platform rewrites/proxies everything to one origin.
- CORS and CSRF/trusted origins must be aligned to the actual deployed frontend origin(s).

Potential blockers / things to verify before Render:
- production settings must disable debug,
- allowed hosts and CSRF trusted origins must include the deployed frontend and backend hosts,
- the process must bind to the container port and host expected by the platform,
- collectstatic and migrations must run in the deployment build/startup flow,
- a health endpoint should exist for platform health checks.

Open items:
- I have not yet confirmed a concrete `/health` response shape and route.
- I have not yet confirmed that Gunicorn entrypoint and settings match the target platform exactly.

## 4. Database findings

Current database:
- The project uses a database backend; the current runtime uses SQLite in local development through `backend/db.sqlite3`.
- A PostgreSQL path exists in the project (psycopg is referenced).
- `docker-compose.yml` and `.env.example` show a compose-oriented DB setup.

Managed PostgreSQL migration considerations:
- The app needs a `DATABASE_URL` style configuration or equivalent environment variables in production.
- Migrations must be run against the persistent database during deploy startup, not just local dev.
- Existing local SQLite data must not be silently discarded if there is anything worth preserving; a safe migration/import plan is required before any production reset.
- Do not run destructive seed scripts against production.
- Inventory isolation is enforced in application models/queries, not by separate databases, so the managed PostgreSQL instance must keep that enforcement intact.

Open items:
- I have not migrated the current SQLite data to PostgreSQL in this session.
- I have not validated the managed Postgres connection from the deployed backend from a real remote host.

## 5. Cross-origin, auth, and cookies

Auth model:
- JWT-based authentication with blacklist support.
- Views must still enforce inventory scope server-side.

Cookie/session considerations:
- If any browser authentication uses cookies, production settings should set appropriate SameSite/Secure behavior when not debug.
- CORS must not use credentials with wildcard origins.
- CSRF protection should remain enabled for browser flows that need it.

Inventory isolation under deployment:
- Inventory division isolation is enforced server-side and must stay that way after deployment.
- CORS/auth changes must not weaken those checks.
- Resort and Healthcare inventories must remain isolated even though they share the same backend and database.

## 6. Flutter mobile findings

Mobile app location:
- `mobile/uems_mobile/` is the Flutter app.

Expected mobile requirements for cloud use:
- The app must be able to point at the deployed backend, not only localhost.
- There is a settings-based production API base and a `--dart-define` compile-time option.
- Relevant files: `mobile/uems_mobile/lib/main.dart`, `mobile/uems_mobile/lib/core/api_client.dart`, `mobile/uems_mobile/lib/screens/settings_screen.dart`.

Localhost discovery fallback:
- The app still contains LAN/localhost-oriented discovery code as a fallback.
- Backup-only localhost addresses exist in `mobile/uems_mobile/lib/core/lan_discovery_io.dart.bak`.
- This is acceptable as a fallback during local dev, but it must not be treated as the production access path.

QR attendance:
- QR attendance verification uses backend endpoints and should continue to work remotely when staff are on mobile data or external Wi-Fi.
- If QR content includes absolute URLs, those must resolve to the deployed public endpoint, not a local one.
- Relevant file: `mobile/uems_mobile/lib/screens/medicine_delivery_screen.dart` / QR scanner screen as applicable.

Files to update before a production mobile build:
- Replace dev-only API addresses/hints with the configurable production path.
- Keep the app robust to network errors, timeouts, expired/invalid sessions, and backend unavailability.
- Prevent duplicate submissions and false success messages when the backend is unreachable.
- Use secure storage for tokens where appropriate.

## 7. Reports, files, PDFs

Report generation:
- Backend report engine and exporters exist in `backend/reports/`.
- Report exports use in-memory buffers for downloads.
- Relevant file: `backend/reports/exporters.py`.
- This is good for cloud deployment because it does not depend on persistent local report storage for the download flow.

Persistent file storage:
- If the system stores uploaded documents or generated PDFs that must survive restarts, a durable storage backend is required in production.
- The current local setup uses local `MEDIA_ROOT` style paths. Those are not sufficient if the platform container filesystem is ephemeral.

Sensitive documents:
- Salary slips, payment vouchers, and sensitive healthcare-related outputs must not be publicly reachable.
- Report downloads must remain authenticated.

Verification requirement:
- Exported report totals must match the same filtered source data shown in the UI.

## 8. Deployment blockers found so far

Likely blockers, in priority order:
1. Confirm the production frontend API base is configured through environment variables and not hardcoded localhost.
2. Confirm backend production settings are ready:
   - DEBUG off,
   - allowed hosts,
   - CSRF trusted origins,
   - CORS allowed origins,
   - static/media handling suitable for the host,
   - a health-check route.
3. Confirm backend process startup binds to the platform port/host and runs migrations + collectstatic in the deploy flow.
4. Confirm a managed PostgreSQL connection path is available and migrations run against it.
5. Confirm the mobile app can target the deployed backend and that QR attendance URLs resolve correctly.
6. Confirm any persistent file storage needs are covered (uploads/reports that must survive restarts).
7. Confirm no destructive seeding is done in production.
8. Confirm no secrets leak into frontend bundles.

Not yet confirmed in this session:
- exact Vercel build output,
- exact Render startup command and port binding,
- real remote access to deployed frontend/backend,
- remote Flutter authentication and QR attendance over an external network.

## 9. What is already OK

From the current repository state, these things look workable:
- One backend with shared inventory engine code and division-scoped data.
- Inventory isolation is enforced in the application layer.
- Report exports are in-memory for download.
- Frontend uses a configurable API base rather than a single compile-time constant in the browser flow.
- Mobile app already has a configurable production API base path.

## 10. Recommended next steps

1. Add or clarify a lightweight backend health endpoint and expose it in the URL config.
2. Make backend production settings and startup commands match the chosen hosting platform exactly.
3. Decide frontend API base strategy for Vercel:
   - direct browser calls to the deployed backend origin, or
   - a proxied path if you want one origin.
4. Decide managed PostgreSQL connection variable names and migration behavior.
5. Determine whether persistent file storage is required; if so, choose a durable backend and update protected-download handling.
6. Update Flutter for production API base, timeout/error handling, secure token storage, and correct QR URL resolution.
7. Prepare deployment docs and environment examples for each component.
8. Test locally with production-like settings before touching live hosting.
9. Only claim remote accessibility after testing the public URL.

## 11. Deliverables this audit feeds into

- `docs/deployment-audit.md` (this file)
- `docs/deployment-guide.md`
- `docs/production-checklist.md`
- `.env.example` files as needed
- platform configs only where they actually fit this repo
- deployment-safe migration instructions
- mobile production configuration notes
- backend health endpoint
- deployment test notes, clearly marking what is NOT VERIFIED
