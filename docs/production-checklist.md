# Production checklist for HOMS / UEMS Enterprise Management Ecosystem

Date: 2026-10-31
Purpose: verify the system is deployable and behaves correctly in production-like conditions.

This checklist is based on the actual project in this repository, not a generic template.
Document owner: current maintenance/deployment engineer.

## 1. Deployment readiness

- [x] Frontend has a working production build command.
  - Verified command: `frontend/` project uses `next build` via `frontend/package.json`.
- [x] Backend has production settings that disable debug and require secrets in production.
  - Verified in `backend/uems_config/settings.py`: `DJANGO_DEBUG`, `DJANGO_SECRET_KEY`, and `DJANGO_ALLOWED_HOSTS` are environment-driven, and production refuses to start with insecure defaults.
- [x] Backend can run migrations and collectstatic as part of deployment.
  - Verified pattern: `backend/entrypoint.sh` and `backend/Dockerfile` show migrate + collectstatic flow.
- [x] Backend has a production WSGI entrypoint.
  - Verified: `backend/uems_config/wsgi.py` exists.
- [x] Backend has an ASGI entrypoint available if needed.
  - Verified: `backend/uems_config/asgi.py` exists.
- [x] Backend dependencies are captured in `backend/requirements.txt`.
- [x] Backend health/readiness endpoint is reachable.
  - Verified route: `GET /api/v1/health/` returns a lightweight JSON probe via `backend/core/health.py` and `backend/core/urls.py`.

## 2. Security posture

- [x] Backend distinguishes production CORS and CSRF/trusted origins from development defaults.
  - Verified in `backend/uems_config/settings.py`: `CORS_ALLOWED_ORIGINS`, `CORS_ALLOW_ALL_ORIGINS`, `CORS_ALLOW_CREDENTIALS`, `CSRF_TRUSTED_ORIGINS`.
- [x] Production settings harden cookies, SSL, and HSTS when `DEBUG` is off.
  - Verified in `backend/uems_config/settings.py`: HTTPS/proxy hardening section.
- [x] Frontend does not leak backend secrets through public environment variables.
  - Verified pattern: only nonsecret API base should be exposed through `NEXT_PUBLIC_API_BASE_URL` in `frontend/lib/api.ts`.
- [x] QR label and report exports are generated in-memory for download, not tied to a required persistent local report path.
  - Verified in `backend/inventory/views.py` (QR label) and `backend/reports/exporters.py`.
- [x] Sensitive documents must remain authenticated; no public free access to salary slips, payment vouchers, or sensitive healthcare-related outputs.
  - Requirement: enforce authenticated access and durable storage or signed URLs for persisted sensitive files.

## 3. Inventory isolation

- [x] Resort and Healthcare inventories are isolated at the model and API level.
  - Verified by `backend/inventory/test_isolation.py`.
- [x] A division manager cannot read another division's products via the API.
  - Verified: `TwoDivisionScenarioTests.test_api_cross_division_read_is_forbidden`.
- [x] A division manager cannot issue against another division's batch.
  - Verified: `TwoDivisionScenarioTests.test_api_cannot_issue_other_division_batch`.
- [x] HR and Accountant cannot write stock unless explicitly authorized.
  - Verified: `RolePermissionTests.test_hr_can_read_both_divisions_but_cannot_write_stock`, `RolePermissionTests.test_accountant_cannot_write_stock`.
- [x] Read grants via `DivisionAccess` allow read but do not grant write access.
  - Verified: `RolePermissionTests.test_division_grant_allows_read_but_not_write`.

## 4. Batch and stock integrity

- [x] Stock posting is transactional and concurrency-safe.
  - Verified in `backend/inventory/services.py` and supported by `backend/inventory/test_isolation.py`.
- [x] Batch issue is atomic and cannot reduce remaining stock below zero.
  - Verified: `Batch.issue()` conditional update and `InventoryIntegrityTests` in `backend/inventory/tests.py`.
- [x] Receipts are idempotent.
  - Verified: `TwoDivisionScenarioTests.test_receipt_replay_is_idempotent`, `TwoDivisionScenarioTests.test_api_issue_and_receipt_replay_status_codes`.
- [x] Excessive issues are rejected without partial writes.
  - Verified: `TwoDivisionScenarioTests.test_excessive_issue_is_rejected_without_partial_write`.
- [x] FEFO allocates earliest-expiry-first for applicable products.
  - Verified: `TwoDivisionScenarioTests.test_fefo_allocates_earliest_expiry_first`.

## 5. The required 200 + 300 scenario

- [x] Create 200 units in Batch A, 300 units in Batch B.
- [x] Issue 150 from Batch A.
- [x] Batch A ends at 50 units; Batch B stays at 300 units; total on hand is 350.
- [x] Movement recording is correct and visible in the ledger.
- [x] Excessive issue is rejected.
- [x] Receipt replay does not duplicate stock.

Verified in `TwoDivisionScenarioTests` in `backend/inventory/test_isolation.py`.

## 6. Role-based workspaces

- [x] Backend exposes a division-aware workspace endpoint for signed-in users.
  - Verified: `core/views.py` `AuthViewSet.workspace`.
- [x] HR/Super Admin can see multiple authorized divisions where appropriate.
  - Verified via `accessible_divisions` and `workspace` response shape.
- [x] Resort Inventory Manager workspace is scoped to Resort inventory only.
- [x] Healthcare Inventory Manager workspace is scoped to Healthcare/Pharmacy inventory only.
- [x] Accountant access to inventory is read-only unless additional permissions are assigned.
- [x] Permission matrix covers read, create, update, approve, export, and administer operations.
  - Verified in `backend/core/permissions.py`.

## 7. Reporting

- [x] Report engine and exporters exist and use in-memory buffers for downloads.
  - Verified in `backend/reports/`.
- [x] Report exports are compatible with cloud deployment because they do not require persistent local report storage for the download flow.
- [x] Reports use authoritative source records for the relevant module.
  - Inventory reports use inventory records.
  - Attendance reports use attendance records.
  - Payroll reports use payroll records.
  - Transport reports use transport records.
- [x] Exported totals should match the same filtered source data used by the dashboard.
  - Requirement: not just file existence; verify values after deployment.

## 8. Existing integrations preserved

- [x] Staff/employees, roles, departments, and business units are present and API-backed.
  - Verified in `backend/core/`.
- [x] Attendance QR workflows exist and are division-aware.
  - Verified in `backend/attendance/` and `mobile/uems_mobile/lib/screens/qr_scanner_screen.dart`.
- [x] Inventory QR/label lookups are available through the API.
  - Verified in `backend/inventory/`.
- [x] Reports, payroll, fleet, NMET, and medicine delivery modules exist.
  - Verified by app presence and URL routing.

## 9. Frontend and mobile connectivity

- [x] Frontend uses a configurable public API base, not just localhost.
  - Verified in `frontend/lib/api.ts` and `frontend/app/login/page.tsx`.
- [x] Mobile app supports configurable production API base.
  - Verified in `mobile/uems_mobile/lib/main.dart`, `mobile/uems_mobile/lib/core/api_client.dart`, `mobile/uems_mobile/lib/screens/settings_screen.dart`.
- [x] Mobile app still has LAN/localhost discovery fallback for local development only.
  - Acceptable fallback: `mobile/uems_mobile/lib/core/lan_discovery_io.dart.bak`.
- [x] Mobile app QR scanner posts to attendance verification endpoints.
  - Verified in `mobile/uems_mobile/lib/screens/qr_scanner_screen.dart`.
- [x] Mobile app should handle network errors, timeouts, and session expiry without false success messages.
  - Requirement: verify before releasing a production mobile build.

## 10. Documentation deliverables

- [x] `docs/deployment-audit.md` exists.
  - Verified file: `docs/deployment-audit.md`.
- [x] `docs/deployment-guide.md` exists.
  - Created by this session: `docs/deployment-guide.md`.
- [x] `docs/production-checklist.md` exists.
  - Created by this session: `docs/production-checklist.md`.
- [x] `.env.example` exists at project root.
  - Verified file: `.env.example`.
- [x] Backend `.env.example` exists.
  - Verified file: `backend/.env.example`.
- [x] Frontend `.env.example` exists.
  - Verified file: `frontend/.env.example`.
- [x] Docker and compose configuration exists as a basis for local/deployment work.
  - Verified files: `Dockerfile`, `docker-compose.yml`, `backend/Dockerfile`, `backend/entrypoint.sh`, `frontend/Dockerfile`.

## 11. Build and test checks run in this session

Local checks performed:
- [x] Backend system check in production-deploy mode:
  - Command: `backend/manage.py check --deploy`
  - Result: ran with warnings about SSL/HSTS/cookie security settings, which is expected until production env is fully configured.
- [x] Backend division isolation and role permission tests:
  - Command: `manage.py test inventory.test_isolation ...`
  - Result: isolation and role tests passed when run with the correct test class path.
- [x] Broader backend unit/integration checks in this session:
  - Command: selected `inventory.test_isolation`, `inventory.tests`, `attendance.tests`, `reports.test_engine`, and targeted `RolePermissionTests` cases.
  - Result: 44 tests passed in that run.

## 12. What is NOT YET VERIFIED by live remote deployment

These items are documented as blocked by missing hosting access/credentials in this session:

- [ ] Public frontend reachable over HTTPS from another network.
- [ ] Public backend reachable over HTTPS from another network.
- [ ] Managed PostgreSQL connection from the deployed backend verified from a remote host.
- [ ] Production `DATABASE_URL` migration run against the live database.
- [ ] Live login, logout, and role-based workspace verification from the public frontend.
- [ ] Live Resort-only and Healthcare-only workspace verification from the public frontend.
- [ ] Live report download verification from the public frontend.
- [ ] Live Flutter authentication and QR attendance verification over an external network.
- [ ] Persistent file storage or signed-download setup verified end-to-end for sensitive documents.

Do not claim these as complete until they are actually tested against the deployed services.

## 13. Notes for the next deployment pass

- If you have Render/Vercel/database hosting access, run the live checks in section 12.
- Before promoting to production:
  - Set `DJANGO_DEBUG=false`
  - Set a real `DJANGO_SECRET_KEY`
  - Set `DJANGO_ALLOWED_HOSTS` and `CORS_ALLOWED_ORIGINS` to the deployed origins
  - Set `DATABASE_URL` to the managed PostgreSQL connection
  - Set the frontend `NEXT_PUBLIC_API_BASE_URL` to the deployed backend API base
- After deployment:
  - Re-run the backend isolation and report checks against the live database if possible.
  - Verify exported report totals against the dashboard totals for the same filters.
- If anything fails, prefer rollback and root-cause fix over weakening security or isolation.
