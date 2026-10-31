# Unified Enterprise Management System (UEMS)

**Buildakar Innovation**

A locally runnable prototype of a unified enterprise management platform covering healthcare operations, medical transportation, medicine delivery, fleet tracking, employee attendance, and resort operations.

## Technology Stack

- **Frontend:** Next.js 16, TypeScript, Tailwind CSS, shadcn/ui-style components, Lucide React, Recharts, TanStack Query, React Hook Form + Zod
- **Mobile:** Flutter 3.44 + Dart (Android), http, mobile_scanner, flutter_secure_storage, provider
- **Backend:** Django 6 + Django REST Framework, SQLite
- **Authentication:** JWT (Simple JWT)
- **QR Codes:** QR generation + backend-validated scanning (manual token fallback included)
- **Maps:** Leaflet + OpenStreetMap (simulated GPS)

## Quick Start

### Prerequisites
- Python 3.10+
- Node.js 18+
- Flutter 3.x (for mobile app, optional)

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt   # if present, otherwise packages already installed
python manage.py migrate
python manage.py seed_data
python manage.py runserver 8000
```

### Frontend (Web)

```powershell
cd frontend
npm install
npm run dev          # http://localhost:3000
```

### Mobile App (Flutter, Android)

```powershell
cd mobile/uems_mobile
flutter pub get
flutter run          # or flutter build apk --debug
```

Configure the API base URL in the app (Settings → API server URL):
- Android emulator: `http://10.0.2.2:8000` (default)
- Physical phone: your laptop's LAN IP, e.g. `http://192.168.1.X:8000`

### One-command startup (PowerShell)
A convenience script is provided at `scripts/start.ps1` which starts the backend (8000) and frontend (3000) together.

## Starter Accounts

All starter accounts use password **`admin123`**:

| Account | Email | Role | Business Unit |
|---------|-------|------|---------------|
| Super Administrator | super@buildakar.com | Super Admin | Both units |
| Healthcare Administrator | hcadmin@buildakar.com | Healthcare Admin | Healthcare |
| Resort Administrator | rsadmin@buildakar.com | Resort Admin | Resort |
| HR Manager | hr@buildakar.com | HR Manager | Healthcare |
| Fleet Manager | fleet@buildakar.com | Fleet Manager | Healthcare |
| Inventory Manager | inv@buildakar.com | Inventory Manager | Healthcare |
| Driver | driver@buildakar.com | Driver | Healthcare |
| Regular Employee | emp@buildakar.com | Employee | Resort |

Sign in at `http://localhost:3000/login` (web) or in the Flutter app.

## Key Features

- Role-based access control with business-unit scoping (healthcare vs. resort)
- Shared employee, attendance, and inventory engine across business units
- QR Attendance:
  - Rotating workplace QR (regenerates every 30 seconds, backend-time expiry)
  - One-time employee-specific QR (single-use, revocable)
  - Camera scanning + manual token entry fallback
  - Side-by-side presentation mode for single-laptop demos
  - Flutter mobile camera scanner
- Employee attendance (check-in/out, shifts, leave, corrections, reports)
- Fleet & driver management with assignment conflict prevention
- NEMT transportation workflow with status transitions
- Medicine delivery integrated with inventory stock reconciliation
- Unified inventory (medical + resort) with batches, expiry, FEFO, low-stock alerts
- Product barcode / GTIN lookup and internal batch QR label generation
- GPS fleet simulator (simulated telemetry persisted to the database)
- Reports & analytics dashboard
- Settings & access control (super admin)
- Flutter mobile app: login, employee dashboard, QR attendance scanner, inventory receive/issue, driver trips

## Testing

Backend tests (including all QR validation and inventory integrity scenarios):

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python manage.py test
```

## Demo Guide

See `DEMO_GUIDE.md` for step-by-step client presentation workflows (rotating QR, one-time QR, medicine receiving, issue, resort inventory, driver trip, access control).

## Notes

- SQLite is used for zero-configuration local demonstration. Concurrent stock and assignment operations require PostgreSQL-level testing before production use.
- All GPS and QR data is simulated/fictional for demonstration purposes.
- No real patient health records or medical diagnoses are stored.
- Cleartext HTTP is allowed in the mobile app for development only; use HTTPS in production.

## Passwordless role access

The web entry page now offers six shared roles without an email or password.
Deploy both backend and frontend changes. No Render shell or manual seeding is
required: POST /api/v1/auth/role-login/ creates the selected shared identity and
reference roles/divisions on first use. Existing personal accounts are preserved.
Normal tokens and role/division permissions still apply after selection. Anyone
who can reach this deployment can select Super Admin and access its capabilities.
Activity is attributed to shared role accounts, not individual people.
ROLE_LOGIN defaults to true; setting it to false disables these endpoints (the
role-only entry page will then be unavailable). Database migrations must already
be applied as in the normal deployment.
