# Implementation Status

## Purpose
This document records the current implementation state of the Healthcare & Resort Enterprise Management System (shared engine, isolated inventories, unified reporting) for team and client visibility.

## Repository: HOMS
- Backend: Django REST API, SQLite development database, Gunicorn entrypoint.
- Frontend: Next.js dashboard SPA with division-aware app shell.
- Mobile: Flutter staff app (attendance QR + inventory barcode scanning).
- Shared documents: README.md, DEMO_GUIDE.md, PROGRESS.md, REPAIR_REPORT.md, REPAIR_DIFF.patch.

## Completed work

### 1. Central authentication and role-based workspaces
- Single user/role model with business-unit-scoped roles.
- `DivisionAccess` grants for cross-division read.
- Frontend app shell selects a division and reloads every relevant query key.
- HR / Super Admin can switch between Resort Inventory and Healthcare Inventory; role managers see only their own division.
- Accountant can read procurement/accounting scope without automatic stock-write access.

### 2. Shared inventory engine with isolated inventories
- One backend service, not two.
- Product, ProductBatch, StockReceipt, StockIssue, StockMovement, Supplier, Goods Receipt, Stock Count, and related models carry `business_unit_id`.
- Write paths enforce division ownership and reject cross-division references.
- Stock balance is derived from `ProductBatch.quantity_remaining`, not an arbitrary counter.

### 3. Batch and stock integrity
- Atomic receipt and issue posting with FEFO allocation where applicable.
- Idempotent receipt replay via reference-based dedup on the service/API layer.
- Excessive issue requests are rejected without partial writes.
- Ledger is recorded per movement; the required 200 + 300 = 50 + 300 = 350 behavior is proven in tests.

### 4. Unified reporting engine
- Inventory, accounting/procurement, HR/payroll, transport, and management reports share report infrastructure but compute from their own authoritative records.
- Payroll is computed from salary structures and attendance, not from inventory.
- Transport estimates are separate from actuals.
- Supports printable browser reports plus PDF/Excel/CSV exports.

### 5. Dashboard corrections
- Dashboard cards are backed by database queries through `/api/v1/reports/dashboard/`.
- There are no leftover mock placeholders for the core inventory and workforce cards.

### 6. Deployment/operational wiring
- Frontend can proxy API requests in development with an explicit `API_PROXY_TARGET`.
- `.env.example` files exist for root/build environment and frontend.
- Backend Dockerfile and entrypoint are git-ignored in this working copy but exist in the actual repo.
- Mobile app already supports build-time `API_BASE_URL` and manual server config; release builds do not silently fall back to a hard-coded LAN address.

## Tested

### Backend tests
- `inventory/test_isolation.py` passes:
  - 200 + 300 batch scenario.
  - 150-unit issue leaves 50 + 300.
  - Excessive issue rejected without partial write.
  - Receipt replay is idempotent.
  - FEFO allocates earliest expiry first.
  - API forbids cross-division reads, cross-division batch issue, and cross-division receipt.
  - HR and accountant can read but cannot write stock.
  - A read-level `DivisionAccess` grant allows cross-division reads.

- `reports/test_engine.py` is present and exercises the report engine.

### Integration witness checks run during this session
- Stock transaction tables (`stockmovement`, `stockissue`, `stockreceipt`, `stockadjustment`, `stockcount`, `stocktransfer`, `purchaseorder`, `supplier`) are currently empty in the seeded database.
- Every `ProductBatch.supplier_id` that is non-null currently resolves to a valid supplier row.
- The only batch with `quantity_remaining <> quantity_received` is `MED-002 / INS-2026-001`, decremented by the seeded medicine-delivery workflow rather than by inventory stock posting; it has no corresponding `StockMovement` ledger entry.

## Not yet fully complete / known limitations

### 1. Supplier wiring on seeded data
- The `inventory_supplier`, `inventory_stockreceipt`, and `inventory_stockreceiptline` tables exist in the schema.
- The current seed data does not populate actual supplier rows or goods-receipt records, so the supplier/receipt workflows are schema-ready but not demonstrated with sample data.
- Every non-null `ProductBatch.supplier_id` in the current database resolves to a valid supplier row; there are currently no non-null batch supplier references, so the supplier chain is intact but unused.
- Newly created receipts and batches should carry supplier references; verify this with a live receipt before demoing supplier reporting.

### 2. Ledger completeness for non-inventory consumption
- The seeded medicine-delivery workflow decrements a batch directly without creating a `StockMovement` ledger row.
- In the current database this affects one batch, `MED-002 / INS-2026-001`, which has `quantity_received = 50` and `quantity_remaining = 48` but no `StockMovement` record.
- On-hand balances can be correct from the app perspective, but there is no auditable inventory movement record for that specific consumption path yet.
- If ledger completeness is required for all stock deductions, the medicine-delivery path should post through the inventory transaction service or create an equivalent audited movement.

### 3. Deployment still requires environment-specific configuration
- There is no `.env` file committed for production; only `.env.example` templates exist where applicable.
- Remote deployment still needs real values for:
  - `API_BASE_URL` / `NEXT_PUBLIC_API_BASE_URL` / frontend build-time API URL.
  - `DATABASE_URL`.
  - `ALLOWED_HOSTS`, `CORS`/trusted origins.
  - HTTPS, static/media storage, and any report storage path.
  - Mobile `API_BASE_URL` build argument for release builds.
- This repository copy keeps backend deployment files git-ignored, so Docker/entrypoint readiness should be confirmed from the actual committed repo before release.

### 4. Production public URL not yet verified
- Configuration is prepared, but a live remote URL has not been deployed and verified in this session.

## Required environment configuration
- Backend:
  - Database URL for the target DB.
  - `ALLOWED_HOSTS` and CORS origins for the frontend and any remote clients.
  - Secret key, debug off, HTTPS in production.
  - Static and media paths/storage for reports and uploads.
- Frontend:
  - Production API base URL for the deployed backend.
  - Any build-time or runtime URL override used by the deployment target.
- Mobile:
  - Release build `API_BASE_URL` pointing at the deployed backend.
  - Network access to that backend from the intended devices.

## Deployment instructions
1. Use the committed backend Dockerfile/entrypoint or a comparable WSGI deployment.
2. Set environment variables for database, secrets, allowed hosts, CORS, static/media, and logging.
3. Ensure migrations are run once as a release step.
4. Build the frontend with the production API URL.
5. Build the mobile app with the production `API_BASE_URL` if it should default to the deployed server.
6. Serve frontend and backend over HTTPS with the correct hostnames.
7. Confirm remote access from a separate device before demoing.

## Suggested next improvements
- Post medicine-delivery consumption through the inventory transaction service or create an equivalent audited movement so all stock changes are ledger-backed.
- Seed suppliers and a couple of goods-receipt records so procurement reporting can be demonstrated immediately.
- Add a small smoke test for the production HTTPS/API reachability story rather than relying on local-only checks.
- Add database indexes for the most common inventory report filters if report queries become slow at scale.
- Review N+1 queries on the busiest report paths once real data volume exists.

## How to verify from this point
- Re-run `inventory/test_isolation.py` and `reports/test_engine.py` after any inventory or report change.
- After seeding suppliers/receipts, confirm supplier and goods-receipt reports return non-empty, division-scoped results.
- After configuration, start the backend and frontend with real URLs and confirm login, division switching, and at least one division-scoped report render.
- For mobile, confirm a release-style configuration resolves to the deployed backend rather than a LAN fallback.
