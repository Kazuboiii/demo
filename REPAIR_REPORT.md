# HOMS repair report — 29 October 2026

The existing architecture is Flutter/Dart with Provider, HTTP, secure storage and mobile_scanner 5.2.3; Django REST Framework with JWT and SQLite; and a separate Next.js frontend. The work repaired the existing implementation. No dependencies were upgraded and no schema migration or production-data reset was performed.

## A. Files modified or added

| File | Defect and correction |
| --- | --- |
| [mobile/uems_mobile/lib/screens/qr_scanner_screen.dart](C:/Users/Kazuboiii/Desktop/HOMS/mobile/uems_mobile/lib/screens/qr_scanner_screen.dart) | Fixed malformed layout and unsupported controller access; manual camera start, lifecycle synchronization, safe disposal, owned barcode subscription, empty-capture handling, request/duplicate guards, shared employee/admin manual entry, visible action/loading/errors, scrollable layout; fallback requires explicit backend code. |
| [mobile/uems_mobile/lib/core/api_client.dart](C:/Users/Kazuboiii/Desktop/HOMS/mobile/uems_mobile/lib/core/api_client.dart) | Normalized API prefix, validated URLs, added 20-second request timeouts, safe non-JSON decoding, session-expiry callback and injectable HTTP transport for tests; discovery no longer reports a nonexistent server as found. |
| [mobile/uems_mobile/lib/core/app_state.dart](C:/Users/Kazuboiii/Desktop/HOMS/mobile/uems_mobile/lib/core/app_state.dart) | Awaited settings persistence, serialized startup/login, handled failed discovery, cleared expired sessions, and prevented notifications after disposal. |
| [mobile/uems_mobile/lib/main.dart](C:/Users/Kazuboiii/Desktop/HOMS/mobile/uems_mobile/lib/main.dart) | Reset navigation on authentication transitions and guarded protected named routes. |
| [mobile/uems_mobile/lib/screens/home_screen.dart](C:/Users/Kazuboiii/Desktop/HOMS/mobile/uems_mobile/lib/screens/home_screen.dart) | Caught load failures, protected empty initials, refreshed after scanning, corrected logout navigation, loaded paginated attendance, and summed actual work intervals excluding breaks and clipping overnight shifts to the local day. |
| [mobile/uems_mobile/lib/screens/inventory_screen.dart](C:/Users/Kazuboiii/Desktop/HOMS/mobile/uems_mobile/lib/screens/inventory_screen.dart) | Replaced hard-coded location/department IDs and product-as-batch IDs with scoped selections; fixed map-identity dropdown assertions, honored entered expiry, validated quantities, loaded pagination, and handled network failures/disposal/concurrent submission. |
| [mobile/uems_mobile/lib/screens/login_screen.dart](C:/Users/Kazuboiii/Desktop/HOMS/mobile/uems_mobile/lib/screens/login_screen.dart) | Disposed text controllers and removed unused imports/analyzer issues. |
| [mobile/uems_mobile/lib/screens/settings_screen.dart](C:/Users/Kazuboiii/Desktop/HOMS/mobile/uems_mobile/lib/screens/settings_screen.dart) | Validated/save-error feedback, scrollable content, and safe logout navigation. |
| [mobile/uems_mobile/ios/Runner/Info.plist](C:/Users/Kazuboiii/Desktop/HOMS/mobile/uems_mobile/ios/Runner/Info.plist) | Added the missing camera permission purpose string. |
| [backend/attendance/views.py](C:/Users/Kazuboiii/Desktop/HOMS/backend/attendance/views.py) | Validated request bodies/actions, added explicit owned-one-time-token discriminator, enforced approved/active users and active employee lookup, serialized rotating attendance transitions, rejected unmatched checkout, restricted token listing/revocation, returned the exact created event, and returned a clear 503 for SQLite lock contention. |
| [backend/attendance/models.py](C:/Users/Kazuboiii/Desktop/HOMS/backend/attendance/models.py) | Atomic employee-serialized one-time redemption with fresh token state, conditional single-use consumption, check-in/out transition checks, server timestamps, rollback on event failure, and inclusive expiry boundary. |
| [backend/core/views.py](C:/Users/Kazuboiii/Desktop/HOMS/backend/core/views.py) | Required authentication/approval for auth/me and scoped department listings by business unit. |
| [backend/core/permissions.py](C:/Users/Kazuboiii/Desktop/HOMS/backend/core/permissions.py) | Made RolePermission honor the allowed_roles configured on each view. |
| [backend/inventory/models.py](C:/Users/Kazuboiii/Desktop/HOMS/backend/inventory/models.py) | Fixed receipt movement parent location, excluded expired batches from usable stock, and made stock deduction conditional on current available quantity/status/expiry. |
| [backend/inventory/serializers.py](C:/Users/Kazuboiii/Desktop/HOMS/backend/inventory/serializers.py) | Made stock document creation atomic, required positive line quantities, and validated receipt/issue unit, destination and product consistency. |
| [mobile/uems_mobile/test/widget_test.dart](C:/Users/Kazuboiii/Desktop/HOMS/mobile/uems_mobile/test/widget_test.dart) | Replaced the unrelated Text smoke test with the actual app and Provider. |
| [mobile/uems_mobile/test/qr_regression_test.dart](C:/Users/Kazuboiii/Desktop/HOMS/mobile/uems_mobile/test/qr_regression_test.dart) | Added URL, JSON, session, mocked camera lifecycle/permission, discriminator, concurrent request, disposal and small-screen regressions. |
| [mobile/uems_mobile/test/attendance_hours_test.dart](C:/Users/Kazuboiii/Desktop/HOMS/mobile/uems_mobile/test/attendance_hours_test.dart) | Added break and overnight-hours regression tests. |
| [backend/attendance/test_regressions.py](C:/Users/Kazuboiii/Desktop/HOMS/backend/attendance/test_regressions.py) | Added discriminator, action, expiry boundary, stale instance, rollback, authorization and checkout regressions. |
| [backend/attendance/test_concurrency.py](C:/Users/Kazuboiii/Desktop/HOMS/backend/attendance/test_concurrency.py) | Added actual simultaneous requests on separate database connections for same-token and mixed-token check-ins. |
| [backend/inventory/test_regressions.py](C:/Users/Kazuboiii/Desktop/HOMS/backend/inventory/test_regressions.py) | Added receipt location/rollback, failed issue rollback, and usable-stock regressions. |

The report and REPAIR_DIFF.patch are additional review artifacts. There is no Git repository at the workspace root, so the diff compares files against a temporary pre-edit baseline captured during this session; it is not a Git diff.

## B. QR attendance status

- Camera initialization/start/stop/disposal: repaired for installed mobile_scanner 5.2.3; mocked native-channel tests pass, including pause/resume and permission denial.
- QR scanning: guards empty captures and values, serializes submissions, and suppresses repeated successful detections. Optical recognition remains untested on real hardware.
- Rotating verification: existing `/api/v1/attendance/rotating-qr/verify/`, authenticated POST `{token, action}`. Server verifies workplace, employee, action, expiration and attendance transition. Success returns `detail` and `event`; expired tokens return 410; duplicates/invalid transitions return 409.
- One-time verification: existing `/api/v1/attendance/one-time-qr/verify/`, authenticated POST `{token, action}`. Action is now checked. Atomic consumption and attendance creation prevent reuse; the exact event is returned. Existing 400 responses for expired/used/wrong-employee tokens are preserved.
- Token distinction: opaque raw tokens remain unchanged. Only an explicit `code: one_time_token` in a rotating verification 404 triggers one-time verification. Generic missing-route/resource 404 responses never trigger fallback. The discriminator is restricted to the token's employee/workplace. Deploy these backend and mobile updates together.
- Check-in/check-out: backend tests cover valid transitions, unmatched checkout, repeat use, and cross-token competing check-ins.
- Duplicate prevention: client request guards plus server serialization/conditional token consumption. Real concurrent SQLite tests pass. Contention returns a clear 503 when SQLite cannot acquire a lock; clients are told to check history before retrying.
- Errors: request timeouts, non-JSON responses, network failures, expired sessions, permission denial and disposal during submission are handled. Employees have manual-token access and result feedback.

## C. Validation

| Check | Result |
| --- | --- |
| flutter pub get | Passed; existing compatible dependency versions retained |
| dart format | Applied only to changed Dart files |
| flutter analyze | Passed: no issues found |
| flutter test | Passed: 12 tests |
| Django check | Passed: no issues |
| Django test attendance inventory core fleet nemt medicine_delivery reports --noinput | Passed: 44 tests, including two genuinely concurrent QR tests; temporary test database only |
| Django makemigrations --check --dry-run | Passed: no schema changes detected |
| flutter build apk --debug | Passed; Android dependency/toolchain combination builds |
| flutter run -d chrome --no-resident | Launched successfully and exited with code 0; runtime smoke check, not a full authenticated workflow |
| Android device/emulator | None connected/installed; physical camera validation unavailable |
| iOS build/runtime | Not run on this Windows host |

## D. Remaining limitations and manual checks

- Test a real camera on Android/iOS: first permission grant, denial then re-enable in Settings, rapid start/stop, background/resume, navigation away, and optical recognition of both token types.
- Test phone-to-backend connectivity using the server's LAN URL. Loopback discovery only checks local/emulator addresses; it does not scan the LAN.
- Complete a real-device authenticated check-in/out and inventory receive/issue flow against the intended deployment. Tests use isolated backend data and mocked HTTP/native channels for Flutter; they do not establish production readiness for the entire ecosystem.
- SQLite concurrency was tested; PostgreSQL and other deployment databases were not available.
- Android build emits a future-compatibility warning about mobile_scanner's Kotlin Gradle Plugin usage. The current build succeeds, so the installed versions were deliberately preserved.
- Inventory barcode lookup remains the existing text-entry lookup flow; this repair does not add a new inventory camera-scanning feature.
- The separate Next.js frontend and every other ecosystem workflow were not manually exercised end to end.

## E. Final change review

Changes are confined to attendance, the related mobile API/authentication/screens, confirmed inventory defects, and regression tests. Existing token formats and URLs are preserved, and migrations, database schema, dependency declarations, Android build settings, unrelated frontend code, and other modules were not intentionally changed. Generated outputs were produced only by normal Flutter validation/build commands, not edited manually.

Edits read current file contents, used contextual patches or targeted current-content transformations, and were followed by file inspection/analyzer/tests. One patch-tool request was rejected because it attempted two operations on the same test path; the file was reread and updated with a supported single operation. No unchanged failing exact-string replacement was repeatedly retried.
