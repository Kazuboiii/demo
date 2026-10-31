import 'package:flutter_test/flutter_test.dart';
import 'package:uems_mobile/screens/home_screen.dart';

void main() {
  Map<String, dynamic> event(String action, DateTime time) => {
    'action': action,
    'timestamp': time.toIso8601String(),
  };

  test('hours exclude breaks and include current check-in', () {
    expect(
      attendanceMinutesToday([
        event('check_in', DateTime(2026, 10, 29, 8)),
        event('check_out', DateTime(2026, 10, 29, 12)),
        event('check_in', DateTime(2026, 10, 29, 13)),
      ], DateTime(2026, 10, 29, 15)),
      360,
    );
  });

  test('overnight shifts count only the current local day', () {
    expect(
      attendanceMinutesToday([
        event('check_in', DateTime(2026, 10, 28, 22)),
        event('check_out', DateTime(2026, 10, 29, 6)),
      ], DateTime(2026, 10, 29, 12)),
      360,
    );
  });
}
