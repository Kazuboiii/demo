# Authentication deployment and verification

HOMS continues to use core.User (email/password), the existing role/division
matrix, and SimpleJWT bearer tokens. No external identity provider or new user
store was introduced. Pharmacy Inventory Manager is the existing
`healthcare_inventory_manager` role; no role or account migration is needed.

## Three combinations

| Frontend | Backend | frontend/.env.local or Vercel build environment |
| --- | --- | --- |
| Local Next.js | Local Django | NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1 |
| Local Next.js | Render | NEXT_PUBLIC_API_BASE_URL=https://<actual-render-host>/api/v1 |
| Vercel | Render | NEXT_PUBLIC_API_BASE_URL=https://<actual-render-host>/api/v1 |

The actual hosting domains were not present in the repository. Replace the
placeholders with the deployed hostnames; do not copy placeholders literally.
Next.js embeds NEXT_PUBLIC values at build time: restart local development or
redeploy Vercel after changes. This URL is public, not a secret.

Optional existing same-origin proxy: leave NEXT_PUBLIC_API_BASE_URL blank and
set API_PROXY_TARGET to the backend origin without /api/v1. Never leave both
blank unless an external reverse proxy handles /api/v1. The LAN server picker
requires NEXT_PUBLIC_ALLOW_API_OVERRIDE=true and a blank explicit API URL.
Deployment configuration takes precedence over legacy browser overrides.

## Render configuration

Preserve the current DJANGO_SECRET_KEY and DATABASE_URL. Never regenerate them
or create/reseed a database to fix a login failure. Check that DATABASE_URL
points at the database containing the required existing users and grants.

Set these in the Render service environment:

- DJANGO_DEBUG=false
- DJANGO_ALLOWED_HOSTS=<actual-render-host> (plus any backend custom hostname;
  hostnames only, without scheme or paths)
- CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,https://<actual-vercel-domain>
- CORS_ALLOW_ALL_ORIGINS=false
- FRONTEND_BASE_URL=https://<actual-vercel-domain>
- PUBLIC_API_BASE_URL=https://<actual-render-host>/api/v1
- DJANGO_CSRF_TRUSTED_ORIGINS=https://<actual-vercel-domain> for trusted frontend
  session-based requests; include localhost only if intentionally using Django
  session authentication from localhost. JWT requests do not require this setting.
- CORS_ALLOW_CREDENTIALS=true preserves existing session clients; the Next.js
  cross-origin JWT client does not enable credentialed cookies.

Add every actual custom domain and selected Vercel preview origin individually
to CORS_ALLOWED_ORIGINS. An origin includes scheme and port, has no path/trailing
slash, and must match exactly. Never wildcard all Vercel tenants. CORS is a
browser access policy, not backend authorization.

Existing blacklist migrations must be applied through the normal approved
release process. This change adds no migrations. Production secrets, databases,
and hosting configuration were not modified by this work.

## Vercel configuration

Use the frontend directory as the project root. Set NEXT_PUBLIC_API_BASE_URL to
the Render API URL in each intended Production/Preview environment, and set
NEXT_PUBLIC_ALLOW_API_OVERRIDE=false (or omit it). No DATABASE_URL,
DJANGO_SECRET_KEY, database password, JWT signing key, or account password belongs
in NEXT_PUBLIC variables. API_PROXY_TARGET is needed only for the optional proxy.
Deploy the backend refresh endpoint before deploying the new frontend.

## Identity consistency

Both local and deployed frontends must target the SAME Render backend to use the
same accounts. A local backend with its default SQLite database is an independent
identity source; matching email addresses do not synchronize passwords, roles,
approval, or permissions. Use a shared nonproduction backend/database for local
integration testing. Connecting local Django to production DATABASE_URL is not
necessary and requires explicit approval; it was not done. Do not copy production
secrets or seed demo accounts into production.

## Session behavior and security

Login ignores stale bearer headers. Access-token expiry triggers one shared
refresh request per client, followed by one retry. Invalid/expired refresh clears
the session; transient network/server failures retain it for retry. Refresh also
checks that the user still exists, is active, and is approved. Login reloads the
workspace so cached data and division state cannot carry over between accounts.
Protected page content waits for the backend session check.

Tokens remain in localStorage, preserving the existing architecture. Each session
is bound to its API URL; changing backend requires login again. Existing sessions
without this binding require a one-time fresh login after upgrade. Tokens remain
accessible to JavaScript, so XSS prevention remains important.

Logout clears browser credentials and calls the existing blacklist endpoint.
When the backend cannot be reached, local logout still completes but remote
refresh revocation cannot be guaranteed. As before, an already issued access JWT
remains valid until expiry (default 480 minutes; JWT_ACCESS_MINUTES is tunable).
This change does not introduce per-request token revocation or rotate signing keys.

Bearer tokens are explicitly attached, never automatically supplied as cookies.
Login/refresh/logout operate on JSON credentials or explicit refresh tokens and
do not create a Django session. Django admin and existing SessionAuthentication
retain CSRF enforcement. No CSRF middleware was removed.

Account mutation is now restricted to Super Admin; scoped account reads remain
available. This closes self-promotion through role/is_staff/is_approved updates.
Inventory retains its existing backend role/action and division checks. HR has
cross-division read access without stock writes; inventory managers retain their
existing division grants. No user or permission-matrix data was changed.

## Verification

Run backend tests from backend/ with a dedicated test database environment:
DJANGO_DEBUG=true and DATABASE_URL=sqlite:///:memory:.
Command: .venv/Scripts/python.exe manage.py test --noinput
Django creates/destroys only its test database. Do not run tests against production.

From frontend/: node --test tests/auth.test.cjs; npx tsc --noEmit; npm run build.
Frontend tests use the real Axios interceptor chain with mock transport.
Backend tests exercise login, restoration, expiry, refresh, logout blacklisting,
revoked approval, inactive/deleted accounts, invalid credentials, unauthorized
requests, role escalation, session CSRF, and an origin/host matrix. Existing
inventory tests cover cross-division reads/writes and HR stock restrictions.
The origin matrix models all three topologies with test hostnames; it is not a
live Vercel/Render end-to-end test.

After exact domains are supplied and hosting changes are deployed, verify in a
browser for each topology: login with each existing role, reload a protected URL,
refresh an expired access token, attempt cross-division access, logout, and revisit
protected URLs. Do not use seeded demo credentials on production. No live account
login or production database writes have been performed.

## Results from this change

- Full backend suite: 87 tests passed using an isolated in-memory database.
- After adding a Super Admin account-mutation regression test: all 8 core tests passed.
- Frontend authentication suite: all 8 tests passed.
- TypeScript: npx tsc --noEmit passed after the final frontend edit.
- Root and frontend git diff --check passed (line-ending notices only).
- npm run build failed twice, inside and outside the sandbox: Turbopack could not
  connect to a spawned CSS worker while processing leaflet/dist/leaflet.css.css.
  The production build is therefore NOT verified. No unrelated CSS/build
  configuration was changed to conceal this failure.
- Live localhost/Render/Vercel combinations were not exercised. Actual deployed
  domains were not supplied, so exact production CORS configuration remains pending.

## Complete file inventory for this task

| File | Change |
| --- | --- |
| .env.example | Added explicit CORS and optional server-override configuration notes; retained prior edits. |
| backend/.env.example | Documented origins, cookie compatibility, and JWT settings. |
| backend/uems_config/settings.py | Explicit localhost CORS defaults, wildcard off by default, credential flag configurable. |
| backend/core/views.py | Existing SimpleJWT refresh integration, approval checks, stale-header-safe login/logout, restricted account mutations. |
| backend/core/urls.py | Registered /api/v1/auth/refresh/. |
| backend/core/permissions.py | Super Admin object access, active/approved role checks, account-administration write permission. |
| backend/core/tests.py | Authentication, CORS, CSRF, expiry and privilege-escalation regression tests. |
| frontend/.env.example | Usable local default and Render/Vercel/proxy configuration examples. |
| frontend/.gitignore | Permit committing .env.example while keeping real environment files ignored. |
| frontend/lib/api.ts | Environment precedence, URL normalization, token endpoint binding, shared refresh and one retry. |
| frontend/lib/auth.ts | Clear token endpoint binding on logout. |
| frontend/app/login/page.tsx | Bind credentials to backend; reset workspace on login; respect managed URL configuration. |
| frontend/components/layout/sidebar.tsx | Call backend logout and clear local state. |
| frontend/components/layout/app-shell.tsx | Withhold protected content during session validation/error. |
| frontend/tests/auth.test.cjs | Real Axios-chain tests using mock transport. |
| docs/AUTHENTICATION_DEPLOYMENT.md | Deployment configuration, identity guidance, test results, limitations and this inventory. |

The frontend is a nested Git repository/submodule with substantial pre-existing
uncommitted/untracked work. Preserve and include its required existing application
files when preparing a release. This task did not commit, push, or deploy either
repository. Pre-existing render.yaml, Next.js config, package files and other
unrelated changes were left intact. Build/type-check tools may update ignored
.next output and tsconfig.tsbuildinfo; these are generated artifacts, not source edits.
