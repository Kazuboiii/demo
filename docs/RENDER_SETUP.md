# Render Docker deployment for HOMS

The reported COPY error came from building the backend Dockerfile with the
repository root as context while COPY expected backend-relative files. The
Dockerfile now consistently uses the repository root. Compose and render.yaml
use this same layout.

## Existing Render service: apply these settings

Editing render.yaml does not update a manually configured service automatically.
In the existing service's Settings > Build & Deploy, use:

| Setting | Value |
| --- | --- |
| Language/runtime | Docker |
| Branch | main |
| Root Directory | empty (repository root) |
| Dockerfile Path | ./backend/Dockerfile |
| Docker Build Context Directory | . |
| Docker Command | empty (use the image entrypoint) |
| Health Check Path | /api/v1/health/ |

Do not set Root Directory to backend with this Dockerfile. Its COPY paths are
now repository-root-relative. Equivalent local command:
`docker build -f backend/Dockerfile -t homs-backend .`

The image normalizes Windows line endings in entrypoint.sh, collects static files
without production credentials, and runs Gunicorn on Render's PORT. The root
.dockerignore excludes frontend, mobile, local databases, environments and secrets.
Docker is not installed in the editing environment; the full image build must be
verified on Render or another Docker host.

## Environment on the same Render service

Keep the EXISTING DJANGO_SECRET_KEY and DATABASE_URL unchanged. DATABASE_URL must
point to the persistent database that contains your existing accounts. The
blueprint no longer provisions a replacement database or generates a signing key.
New installations must supply these explicitly. Do not reseed an existing database.

Set:

```dotenv
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=demo-jpuo.onrender.com
PUBLIC_API_BASE_URL=https://demo-jpuo.onrender.com/api/v1
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,https://frontend-lake-three-pu8rw4cxw9.vercel.app
CORS_ALLOW_ALL_ORIGINS=false
CORS_ALLOW_CREDENTIALS=true
DJANGO_CSRF_TRUSTED_ORIGINS=https://frontend-lake-three-pu8rw4cxw9.vercel.app
FRONTEND_BASE_URL=https://frontend-lake-three-pu8rw4cxw9.vercel.app
RUN_MIGRATIONS=0
DJANGO_MEDIA_ROOT=/app/media
```

Django now accepts RENDER_EXTERNAL_HOSTNAME, which Render supplies automatically.
Preserve DJANGO_ALLOWED_HOSTS for any additional backend custom domains. Set
PUBLIC_API_BASE_URL to https://demo-jpuo.onrender.com/api/v1 if used by your clients.
Origins must not include /login or any trailing path.

The blueprint uses a Starter service with a persistent media disk mounted at
/app/media. For an existing service, preserve its disk and files; review the
current mount before changing it. If keeping a different mount path, set
DJANGO_MEDIA_ROOT to that path. Do not replace or delete an existing disk.

Automatic migrations are disabled in this blueprint to avoid unapproved database
writes. Review pending migrations and run `python manage.py migrate --noinput`
through your approved release process before serving traffic when required.
No migrations or production database operations were performed here.

## Connect Vercel

In the Vercel project that serves the provided frontend URL, set:

```dotenv
NEXT_PUBLIC_API_BASE_URL=https://demo-jpuo.onrender.com/api/v1
NEXT_PUBLIC_ALLOW_API_OVERRIDE=false
```

Select each Vercel environment that should connect to this backend, then redeploy
(the public URL is embedded at build time). Do not put database or signing secrets
in Vercel public variables. The confirmed Render backend is https://demo-jpuo.onrender.com.

For local Next.js against this same account database, use the same API URL in
frontend/.env.local and restart the dev server. For local Django use
http://localhost:8000/api/v1; its SQLite users are independent.

The supplied Vercel URL is allowed exactly. If Vercel gives you another deployment
or production alias, add that exact origin to CORS_ALLOWED_ORIGINS too. Do not
allow all vercel.app tenants. Existing auth, refresh, logout and backend role
checks are unchanged by this deployment fix.

## Release verification

1. Push the reviewed repository changes to the connected branch and deploy the
   existing Render service using the settings above.
2. Check https://demo-jpuo.onrender.com/api/v1/health/ returns the HOMS JSON response.
3. Set the Vercel API URL, redeploy, then sign in at the provided frontend URL.
4. Reload a protected page, verify role/division restrictions, then sign out.

Repository changes alone do not update either hosting dashboard. No hosting
credentials were available in this session, and no push or deployment was made.

Reference: https://render.com/docs/monorepo-support and https://render.com/docs/docker

## Verification and files changed in this deployment fix

- 10 backend authentication/deployment tests passed on an isolated test database,
  including the exact supplied Vercel origin and missing Render database protection.
- Render and Compose YAML parsed successfully; Dockerfile/context paths and the
  Vercel CORS allowlist were checked.
- git diff --check passed.
- Docker image execution and live hosting connectivity remain unverified.

Changed files: backend/Dockerfile, .dockerignore, docker-compose.yml, render.yaml,
backend/uems_config/settings.py, backend/.env.example, backend/core/tests.py,
backend/core/test_deployment.py, docs/RENDER_SETUP.md, and
 docs/AUTHENTICATION_DEPLOYMENT.md (link to this updated setup).
The pre-existing frontend submodule changes were not modified in this task.
