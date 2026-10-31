import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:uems_mobile/core/api_client.dart';

void main() {
  test('discovery verifies identity, deduplicates concurrent calls, and caches', () async {
    var discoveries = 0;
    var probes = 0;
    final api = ApiClient(
      discover: () async { discoveries++; return ['http://192.168.1.10:8000']; },
      client: MockClient((request) async {
        probes++;
        expect(request.url.path, '/api/v1/health/');
        expect(request.headers.containsKey('Authorization'), false);
        return http.Response('{"service":"homs","version":1}', 200);
      }),
    );
    final results = await Future.wait([api.detectApiBase(), api.detectApiBase()]);
    expect(results, everyElement('http://192.168.1.10:8000/api/v1'));
    await api.detectApiBase();
    expect(discoveries, 1);
    expect(probes, 1);
    api.resetDiscovery();
    await api.detectApiBase();
    expect(discoveries, 2);
    api.dispose();
  });

  test('an unrelated HTTP server is not selected', () async {
    final api = ApiClient(discover: () async => ['http://192.168.1.10:8000'],
      client: MockClient((_) async => http.Response('{"service":"other"}', 200)));
    await expectLater(api.detectApiBase(), throwsFormatException);
    api.dispose();
  });

  test('multiple LAN servers require a deliberate choice', () async {
    final api = ApiClient(discover: () async => ['http://192.168.1.10:8000', 'http://192.168.1.11:8000'],
      client: MockClient((_) async => http.Response('{"service":"homs","version":1}', 200)));
    await expectLater(api.detectApiBase(), throwsFormatException);
    api.dispose();
  });
}
