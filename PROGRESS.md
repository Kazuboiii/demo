# Project Progress — UEMS (Buildakar Innovation)

## Status: COMPLETE — Working Client Prototype

### Backend (Django 6 + DRF + SQLite) — VERIFIED
- All migrations applied, seed command idempotent
- **24 backend tests passing** (17 original + 7 new barcode/label tests)
- **Live API verification: 27/28 scenarios passed** (1 failure was test script using non-existent batch ID; QR label endpoint verified working with valid batch ID)

### Core Features
- Auth (JWT), roles, business units, departments, users, employees
- Attendance: shifts, check-in/out, rotating QR (30s shared), one-time QR (single-use, revocable), leave, corrections, reports
- Inventory: unified engine, products w/ barcode + batch_tracking_required, batches, receipts, issues, transfers, movements
  - Barcode/GTIN lookup endpoint
  - Batch label JSON endpoint
  - Batch QR label PNG generation
- Fleet: vehicles, drivers, assignments, GPS tracking
- NEMT: transport requests, trip transitions (assigned→started→picked_up→dropped_off→completed)
- Medicine delivery: reserve/dispatch/deliver/fail with stock reconciliation
- Reports: attendance, inventory, fleet
- Settings: users/access control

### Frontend (Next.js web) — BUILD PASSES
- 16 pages: login, dashboard, employees, attendance, QR attendance, fleet, NEMT, medicine delivery, inventory (with barcode lookup + QR label), reports, settings

### Mobile (Flutter 3.44 + Dart) — APK BUILT
- `flutter analyze`: 0 errors
- Screens: Login, Home (attendance dashboard), QR Scanner (camera + manual entry), Inventory (products/receive/issue), Settings
- APK: build/app/outputs/flutter-apk/app-debug.apk (171MB)
- Android toolchain: [√] configured

### Documentation
- README.md: startup instructions, starter accounts, features, mobile setup
- PROGRESS.md: this file
- DEMO_GUIDE.md: step-by-step client presentation workflows (6 demos)

### Key Verified Workflows
1. Rotating QR attendance: generate → scan → record → duplicate rejected → shared between employees → expired rejected
2. One-time QR: generate → redeem → reuse rejected → wrong employee rejected → unauthorized generation rejected
3. Medicine receiving: barcode lookup → receive stock → generate QR label → scan batch QR
4. Medicine issue: select batch → issue stock → expired/quarantined blocked
5. NEMT trip: create → assign → start → pickup → dropoff → complete
6. Access control: business-unit scoping enforced, super admin sees both units

### Files in Repository
- backend/ — Django project (apps: core, attendance, inventory, fleet, nemt, medicine_delivery, reports)
- frontend/ — Next.js web application
- mobile/uems_mobile/ — Flutter Android app
- scripts/start.ps1 — one-command startup
- docker-compose.yml — optional Docker deployment
- README.md — startup and feature documentation
- DEMO_GUIDE.md — client presentation walkthroughs
- PROGRESS.md — this file
