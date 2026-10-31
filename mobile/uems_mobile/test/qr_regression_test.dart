import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uems_mobile/core/api_client.dart';
import 'package:uems_mobile/core/app_state.dart';
import 'package:uems_mobile/screens/qr_scanner_screen.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    SharedPreferences.setMockInitialValues({
      'api_base_url': 'http://localhost:8000',
    });
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
          const MethodChannel('dev.steenbakker.mobile_scanner/scanner/method'),
          (_) async => null,
        );
  });

  test('base URL has exactly one API prefix', () {
    expect(
      ApiClient.normalizeBase('http://10.0.2.2:8000/'),
      'http://10.0.2.2:8000/api/v1',
    );
    expect(
      ApiClient.normalizeBase('http://10.0.2.2:8000/api/v1/'),
      'http://10.0.2.2:8000/api/v1',
    );
    expect(() => ApiClient.normalizeBase('server:8000'), throwsFormatException);
  });

  test('HTML and empty responses do not crash JSON parsing', () {
    expect(
      ApiClient.decodeBody(http.Response('<html>Bad gateway</html>', 502)),
      isNull,
    );
    expect(ApiClient.decodeBody(http.Response('', 204)), isNull);
  });

  test('401 notifies session expiry except during login', () async {
    var expired = false;
    final api = ApiClient(
      client: MockClient((_) async => http.Response('{}', 401)),
    );
    api.onUnauthorized = () async {
      expired = true;
    };
    await api.get('/auth/me/');
    expect(expired, isTrue);
    expired = false;
    await api.post('/auth/login/');
    expect(expired, isFalse);
    api.dispose();
  });

  Future<AppState> scanner(WidgetTester tester, http.Client client) async {
    final state = AppState();
    await state.ready;
    await state.setAuthenticated(
      access: 'test-token',
      user: {'role_code': 'employee'},
    );
    await tester.pumpWidget(
      ChangeNotifierProvider.value(
        value: state,
        child: MaterialApp(
          home: QrScannerScreen(apiClient: ApiClient(client: client)),
        ),
      ),
    );
    await tester.pumpAndSettle();
    return state;
  }

  Future<void> submit(WidgetTester tester) async {
    await tester.ensureVisible(find.byType(TextField));
    await tester.enterText(find.byType(TextField), 'opaque-token');
    await tester.ensureVisible(find.byIcon(Icons.send));
    await tester.tap(find.byIcon(Icons.send));
    await tester.pump();
  }

  testWidgets('camera starts once, pauses, resumes and stops on disposal', (
    tester,
  ) async {
    final methods = <String>[];
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(
      const MethodChannel('dev.steenbakker.mobile_scanner/scanner/event'),
      (_) async => null,
    );
    messenger.setMockMethodCallHandler(
      const MethodChannel('dev.steenbakker.mobile_scanner/scanner/method'),
      (call) async {
        methods.add(call.method);
        if (call.method == 'state') return 1;
        if (call.method == 'start') {
          return {
            'textureId': 1,
            'numberOfCameras': 1,
            'size': {'width': 640.0, 'height': 480.0},
          };
        }
        return null;
      },
    );
    final state = await scanner(
      tester,
      MockClient((_) async => http.Response('{}', 400)),
    );
    expect(methods.where((m) => m == 'start'), isEmpty);
    await tester.tap(find.text('Start Camera'));
    await tester.pumpAndSettle();
    expect(methods.where((m) => m == 'start').length, 1);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    await tester.pumpAndSettle();
    expect(methods.where((m) => m == 'stop').length, 1);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
    expect(methods.where((m) => m == 'start').length, 2);
    await tester.pumpWidget(const SizedBox());
    await tester.pumpAndSettle();
    expect(methods.where((m) => m == 'stop').length, 2);
    expect(tester.takeException(), isNull);
    state.dispose();
  });

  testWidgets('permission denial leaves manual entry available', (
    tester,
  ) async {
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(
      const MethodChannel('dev.steenbakker.mobile_scanner/scanner/event'),
      (_) async => null,
    );
    messenger.setMockMethodCallHandler(
      const MethodChannel('dev.steenbakker.mobile_scanner/scanner/method'),
      (call) async {
        if (call.method == 'state') return 2;
        if (call.method == 'request') return false;
        return null;
      },
    );
    final state = await scanner(
      tester,
      MockClient(
        (_) async => http.Response('{"detail":"Attendance recorded."}', 200),
      ),
    );
    await tester.tap(find.text('Start Camera'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Allow camera access'), findsOneWidget);
    await submit(tester);
    await tester.pumpAndSettle();
    expect(find.text('Attendance recorded.'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
    await tester.pumpAndSettle();
    state.dispose();
  });

  for (final discriminator in [false, true]) {
    testWidgets('404 fallback requires discriminator: $discriminator', (
      tester,
    ) async {
      final paths = <String>[];
      final state = await scanner(
        tester,
        MockClient((request) async {
          paths.add(request.url.path);
          return paths.length == 1
              ? http.Response(
                  discriminator
                      ? '{"code":"one_time_token"}'
                      : '<html>Not found</html>',
                  404,
                )
              : http.Response('{"detail":"Attendance recorded."}', 200);
        }),
      );
      await submit(tester);
      await tester.pumpAndSettle();
      expect(paths.length, discriminator ? 2 : 1);
      if (discriminator) expect(paths.last, endsWith('/one-time-qr/verify/'));
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      state.dispose();
    });
  }

  testWidgets('pending submission is single-flight and safe after disposal', (
    tester,
  ) async {
    var count = 0;
    final response = Completer<http.Response>();
    final state = await scanner(
      tester,
      MockClient((_) {
        count++;
        return response.future;
      }),
    );
    await submit(tester);
    await tester.tap(find.byIcon(Icons.send));
    await tester.pump();
    expect(count, 1);
    await tester.pumpWidget(const SizedBox());
    response.complete(http.Response('{"detail":"Attendance recorded."}', 200));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    state.dispose();
  });

  testWidgets('small-screen manual entry and network failure recover loading', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(320, 480);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final state = await scanner(
      tester,
      MockClient((_) async => throw http.ClientException('offline')),
    );
    await submit(tester);
    await tester.pumpAndSettle();
    expect(find.byType(LinearProgressIndicator), findsNothing);
    expect(
      find.textContaining('Could not confirm attendance.'),
      findsOneWidget,
    );
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
    state.dispose();
  });
}
