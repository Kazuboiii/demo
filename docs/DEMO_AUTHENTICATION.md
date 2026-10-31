# Demo authentication and seeding — operations guide

This is the procedure for creating and verifying the six demo accounts on the
deployed Render backend, and for running the same flow locally.

## What exists now

- **`manage.py seed_demo`** — idempotent management command. It creates missing
  demo accounts, safely fills missing roles/business units, and generates a
  fresh, secure password (Django-hashed) per account **it creates**. Existing
  accounts are never touched: no deletions, no password overwrites, no
  destructive migrations. Seeding is opt-in only; nothing runs on deploy.
- **`is_demo` flag** (core migration 0004) — only seeded accounts carry it. It
  is the single gate for the one-click demo endpoints.
- **`GET /api/v1/auth/demo-accounts/`** — lists demo emails/roles for the login
  selector. Returns 404 when demo login is disabled. Passwords are never sent.
- **`POST /api/v1/auth/demo-login/`** — one-click JWT login for demo accounts.
  Enabled **only** when the `DEMO_LOGIN` env var is `true` (set on Render) and
  only for `is_demo=True` accounts. Regular accounts can never use it.
- Login page (Next.js) — manual email + password form (connected to the
  standard `/api/v1/auth/login/` endpoint), plus a demo selector that appears
  only when the server reports demo accounts.

The six roles: Super Admin (`super_admin`), Resort Inventory Manager
(`resort_inventory_manager`), Pharmacy Inventory Manager
(`healthcare_inventory_manager`), HR Manager (`hr_manager`), Finance Manager
(`accountant`), Staff (`employee`).

Division isolation is enforced in the backend API (not the frontend): the
permission matrix in `backend/core/permissions.py` plus `requested_division` /
`scoped_queryset` scoping on every inventory endpoint. A resort inventory
manager only receives RESORT rows; a pharmacy inventory manager only HEALTH.

## Commands on Render (backend service → Shell)

Render uses a Docker image (`runtime: docker`), so run these from the service
Shell in the Render dashboard:

```bash
# 1. Apply pending migrations (safe: 0004 only adds user.is_demo).
python manage.py migrate

# 2. Seed the demo accounts (explicit, opt-in; safe to re-run).
python manage.py seed_demo

# 3. Report state without changing anything.
python manage.py seed_demo --verify
```

## Getting the generated credentials

- Locally: after seeding, passwords are written to
  `backend/DEMO_CREDENTIALS.txt` (git-ignored). The file lists only accounts
  **that run created**.
- On Render: the container filesystem is not persistent, so write passwords to
  stdout in your shell session instead:

  ```bash
  python manage.py seed_demo --show-passwords
  ```

  Or re-seed with an explicit output path if you prefer a file:

  ```bash
  python manage.py seed_demo --output /tmp/DEMO_CREDENTIALS.txt
  ```

- Accounts that already existed keep their old passwords (never overwritten).
  To let an existing account use one-click demo login without changing its
  password:

  ```bash
  python manage.py seed_demo --adopt-existing
  ```

- Losing the password: delete the demo user (only demo rows) and re-seed, or
  set a new one explicitly, e.g.
  `python manage.py shell -c "u=User.objects.get(email='staff@buildakar.com'); u.set_password('New-Strength-1'); u.save()"`.

## Deployment configuration

- `render.yaml` sets `DEMO_LOGIN=true` on the demo backend service. Remove that
  key to make the one-click endpoints return 404 (manual email+password login
  keeps working for every account).
- The frontend (Vercel) needed no configuration change: the login selector is
  discovered at runtime from `/api/v1/auth/demo-accounts/`.
- The Flutter app defaults to `https://demo-jpuo.onrender.com`, so it works on
  any network. Override per build with
  `--dart-define=API_BASE_URL=https://your-host` or in the app's Settings.

## Verification checklist

```bash
python manage.py test core.test_demo_auth   # seeding + demo endpoints + isolation
python manage.py test core inventory        # full auth/permission/isolation suites
```

Manually: open the frontend login page — the "Quick sign in" panel lists the six
demo accounts; clicking one logs in directly and lands on its workspace. Each
manager role only sees its own division's inventory, and only `super@buildakar.com`
can manage account settings.
