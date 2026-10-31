# Deployment guide for HOMS / UEMS Enterprise Management Ecosystem

Date: 2026-10-31
Audience: deployment engineers and maintainers.

Related documents:
- `docs/deployment-audit.md` (findings informing this guide)
- `docs/production-checklist.md` (verification steps and status)
- `docs/implementation-status.md` (feature and test coverage)

This guide explains how to deploy the existing project, not how to rebuild it.
It assumes the repository in this folder is the current working codebase.

## 1. Package the project for Git

1. Ensure the repository root is the folder containing `backend/`, `frontend/`, `mobile/`, `scripts/`, `docs/`, `Dockerfile`, `docker-compose.yml`, and `.env.example`.
2. Add and commit all desired source files, documentation, and deployment configuration.
3. Do **not** commit runtime secrets, local virtualenvs, build artifacts, or local databases.
4. Push the repository to a Git host you control (GitHub/GitLab/etc).
5. Keep the frontend, backend, and mobile app pointing at the same repository so builds stay aligned.

## 2. Create the managed PostgreSQL database

1. Create a managed PostgreSQL instance on your chosen provider.
2. Create a database user with least-privilege access to that database.
3. Record a connection URL in the form:
   - `postgresql://user:password@host:5432/dbname`
4. Prefer TLS connection parameters if your provider supports them.
5. This database becomes the single source of truth for all business data.
6. Do not mix Resort and Healthcare data through database tricks. The application enforces division isolation in its models, queries, and permissions; the database must keep that intact.

## 3. Deploy the backend to Render

1. Create a Render web service for the backend.
2. Point it at the repository and the `backend/` folder as the service root if the platform supports root directory selection.
3. Use a Python runtime compatible with the project dependencies.
4. Set the build command to collect static files and prepare the Python environment.
   - Example build command:
     - `pip install -r requirements.txt && python manage.py collectstatic --noinput`
5. Set the start command to run migrations and serve the app with a production WSGI server.
   - Example start command:
     - `python manage.py migrate --noinput && gunicorn uems_config.wsgi:application`
6. Bind to the platform port. Render sets `PORT`; ensure the process uses it.
   - If you use the provided gunicorn entrypoint style, bind to `$PORT` and `0.0.0.0`.
7. Do not use Django's development server as the production web server.
8. If you deploy via Docker instead, use `backend/Dockerfile` and `backend/entrypoint.sh` as the basis, and still run migrations and collectstatic as part of the container startup/build.

Backend health check:
- The deployed backend exposes a lightweight health probe at `/api/v1/health/`.
- Use that path for readiness/liveness checks where your platform supports HTTP health checks.
- The health probe is intentionally stateless and does not leak user data.

## 4. Configure backend environment variables

Set these on the backend service:

- `DJANGO_SECRET_KEY`
  - Long random value. Required when `DJANGO_DEBUG` is false.
- `DJANGO_DEBUG`
  - `false` in production.
- `DJANGO_ALLOWED_HOSTS`
  - Comma-separated public hostnames for the backend.
  - Include the Render backend hostname and any custom backend domain.
- `DJANGO_CSRF_TRUSTED_ORIGINS`
  - Origins allowed for CSRF, if your browser flows rely on cookies.
  - Include the frontend origin(s) in production.
- `CORS_ALLOWED_ORIGINS`
  - Frontend origin(s) allowed to call the backend API.
  - Do not use wildcard credentials in production.
- `FRONTEND_BASE_URL`
  - Frontend origin, used by backend templates/links where applicable.
- `PUBLIC_API_BASE_URL`
  - Public API base 경로 the frontend should use when it talks directly to the backend.
  - Example: `https://api.example.com/api/v1`
- `DATABASE_URL`
  - The managed PostgreSQL connection URL.
- `DJANGO_STATIC_URL`, `DJANGO_STATIC_ROOT`, `DJANGO_MEDIA_URL`, `DJANGO_MEDIA_ROOT`
  - Keep these configured; media handling in production still needs durable storage or a proxy, not ephemeral container storage.
- `DJANGO_SECURE_SSL_REDIRECT`
  - `true` in production unless a load balancer handles HTTPS redirect outside Django.
- `DJANGO_LOG_LEVEL`, `DJANGO_LOG_FILE` / `DJANGO_LOG_MAX_BYTES` / `DJANGO_LOG_BACKUPS`
  - Optional logging tuning.
- `APP_ENV`
  - Set to `production` where your configuration expects it.

Do not set `DATABASE_URL` or `DJANGO_SECRET_KEY` in frontend code.

## 5. Deploy the frontend to Vercel

1. Create a Vercel project for the frontend.
2. Set the project root to `frontend/` if Vercel needs a root directory for a monorepo.
3. Use the frontend's own build command:
   - `npm run build`
4. The frontend is a Next.js app. Vercel should detect it automatically.
5. Set environment variables for the client-facing API base:
   - `NEXT_PUBLIC_API_BASE_URL`
     - The public backend URL the browser should call.
     - Example: `https://api.example.com/api/v1`
6. Do not pass backend secrets through `NEXT_PUBLIC_` variables.
7. If you rely on a same-origin proxy instead of direct browser calls, configure that in `frontend/next.config.ts` via the existing proxy/target settings, but do not assume local filesystem or localhost-only behavior.
8. Make sure the frontend build succeeds before promoting to production.

## 6. Configure the frontend API URL

1. The frontend supports a configurable production API base through `NEXT_PUBLIC_API_BASE_URL`.
2. Confirm `frontend/lib/api.ts` normalizes the base URL correctly in the browser.
3. Confirm the login flow can store and apply the chosen server URL without relying on localhost.
4. Verify protected pages still call the backend through the configured public URL in production.
5. If you want the frontend and backend on the same domain, align CORS so the browser origin matches an allowed backend origin.

## 7. Configure CORS and authentication

1. In production, set `CORS_ALLOWED_ORIGINS` to the frontend origin(s) only.
2. If your browser authentication uses cookies, set:
   - `DJANGO_CSRF_TRUSTED_ORIGINS` to the frontend origin(s)
   - `SECURE` cookie flags via the production settings
3. Do not disable CSRF just to make cross-origin authentication work.
4. This project uses JWT authentication for API access.
   - Keep token lifetimes appropriate for your deployment.
   - Ensure logout/blacklist behavior is preserved.
5. Verify that cross-origin changes do not weaken inventory division isolation.
6. Verify that unauthorized users still cannot read or write inventory across divisions.

## 8. Configure persistent file storage

1. QR label and report downloads in this project are generated in-memory for download.
   - That is suitable for cloud deployment because it does not require persistent local report storage for the download flow.
2. If you store uploaded files or generated documents that must survive restarts, choose durable storage:
   - object storage, or
   - a mounted persistent volume, or
   - a reverse proxy serving media from durable storage
3. Do not rely on the container's ephemeral filesystem for long-lived media in production.
4. Protect sensitive documents with authentication or short-lived signed download URLs.
   - Salary slips, payment vouchers, and sensitive healthcare-related outputs must not be publicly reachable.

## 9. Create an authorized Super Admin

1. After the backend is running and connected to the database:
   - Run migrations against the production database.
   - Create the first Super Admin through the Django admin or a management command authorized for that purpose.
2. Do **not** run destructive seed scripts against production.
3. Do **not** automatically populate production with sample products, employees, salaries, or inventory transactions unless you have explicitly decided that is desired.
4. Once Super Admin access exists, create the required roles and users:
   - Resort Inventory Manager
   - Healthcare Inventory Manager
   - HR
   - Accountant
   - Staff
5. Assign each inventory manager to the correct division and verify scope in the app.

## 10. Build Flutter with the production API endpoint

1. The mobile app supports configurable production API access through settings and compile-time overrides.
2. Update the mobile app to point at the deployed backend before building for distribution.
   - Relevant files:
     - `mobile/uems_mobile/lib/main.dart`
     - `mobile/uems_mobile/lib/core/api_client.dart`
     - `mobile/uems_mobile/lib/screens/settings_screen.dart`
3. Use the production API base via:
   - a settings screen override, or
   - a build-time `--dart-define` value when you want a fixed production endpoint
4. Keep QR attendance and login flows intact.
5. Handle network errors, timeouts, expired/invalid sessions, and backend unavailability gracefully.
6. Prevent duplicate submissions and false success messages when the backend is unreachable.
7. Store tokens securely where appropriate.
8. If QR content contains absolute URLs, validate that they resolve to the deployed public endpoint, not a local one.

## 11. Test access from another network

1. From a device outside the development machine/network:
   - Load the deployed frontend URL.
   - Log in with authorized credentials.
   - Confirm the correct inventory workspace appears for the signed-in role.
   - Confirm Resort Inventory Manager only sees Resort inventory.
   - Confirm Healthcare Inventory Manager only sees Healthcare/Pharmacy inventory.
   - Confirm HR/Super Admin can switch authorized inventories if applicable.
   - Confirm reports and downloads still work remotely.
   - Confirm logout and session expiry behave as expected.
2. For mobile:
   - Test on mobile data or external Wi-Fi.
   - Confirm staff can scan attendance QR codes and reach the backend.
3. For each check, use the actual public service, not a local mock, whenever possible.

## 12. Troubleshooting deployment problems

Common issues and first checks:

- Frontend cannot reach the backend:
  - Verify `NEXT_PUBLIC_API_BASE_URL` is set and public.
  - Verify CORS allows the frontend origin.
  - Verify the backend health endpoint responds.
- Backend fails to start:
  - Confirm `DJANGO_DEBUG` is `false` only when `DJANGO_SECRET_KEY` and `DJANGO_ALLOWED_HOSTS` are set.
  - Check logs for database connectivity or migration failures.
- Authentication fails after deployment:
  - Confirm `DJANGO_CSRF_TRUSTED_ORIGINS`, `CORS_ALLOWED_ORIGINS`, and cookie secure flags are set appropriately for the deployed frontend origin.
- Inventory still appears mixed:
  - Confirm the division assignment on users and products/batches/suppliers/locations.
  - Confirm the server-side scope checks are still active; do not rely on frontend filtering.
- Reports or documents missing:
  - Confirm report generation runs in-memory for downloads.
  - Confirm durable storage or a media proxy is configured for any persisted files.
- Mobile app cannot connect:
  - Confirm the mobile API base points to the deployed backend.
  - Confirm HTTPS is used.
  - Confirm the backend CORS/auth configuration allows the mobile client.

Deployment order:
1. Database
2. Backend
3. Frontend
4. Mobile build configuration
5. Super Admin and role setup
6. Cross-network verification

Rollback notes:
- Keep the previous working backend service and frontend deployment available until new deployments are validated.
- Roll back environment variables first if a bad variable causes startup failure.
- Restore the previous database state from backup before re-running migrations if migration issues are suspected.
- Do not retry migrations blindly against production; stop and review the failure.

Documents to keep updated:
- `docs/deployment-audit.md`
- `docs/production-checklist.md`
- `docs/implementation-status.md`

Environment examples:
- `frontend/.env.example` for frontend example variables
- `backend/.env.example` for backend example variables
- `.env.example` and `docker-compose.yml` for local compose-style setups
