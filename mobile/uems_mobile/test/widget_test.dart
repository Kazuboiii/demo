// Basic smoke test for the UEMS mobile app.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:provider/provider.dart';
import 'package:uems_mobile/core/app_state.dart';

import 'package:uems_mobile/main.dart';

void main() {
  testWidgets('UemsApp builds', (WidgetTester tester) async {
    FlutterSecureStorage.setMockInitialValues({});
    SharedPreferences.setMockInitialValues({});
    final state = AppState();
    await state.ready;
    await tester.pumpWidget(
      ChangeNotifierProvider.value(value: state, child: const UemsApp()),
    );
    await tester.pumpAndSettle();
    expect(find.text('Choose your role'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
    state.dispose();
  });
}
