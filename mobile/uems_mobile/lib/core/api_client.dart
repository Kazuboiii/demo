import 'dart:convert';
import 'lan_discovery.dart';
import 'package:http/http.dart' as http;

import '../core/storage.dart';

/// Central HTTP client for the UEMS Django REST API.
///
/// Automatically attaches the Bearer access token from secure storage and
/// notifies the app state on 401 (unauthorized) so the user can re-login.
class ApiClient {
  ApiClient({http.Client? client, Future<List<String>> Function()? discover})
    : _client = client ?? http.Client(),
      _discoverServers = discover ?? discoverServers;
  static final ApiClient instance = ApiClient();

  /// Build-time API endpoint, e.g.
  /// `flutter build apk --dart-define=API_BASE_URL=https://api.example.com`.
  static const String configuredBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: '',
  );

  /// Deployed UEMS backend. Without any user configuration the app talks to
  /// this server, so it works on any network (mobile data, hotel Wi-Fi, ...),
  /// not only on the same Wi-Fi as a laptop running the backend locally.
  /// Users can override it in Settings or via --dart-define for local dev.
  static const String defaultBaseUrl = 'https://demo-jpuo.onrender.com';

  final http.Client _client;
  final Future<List<String>> Function() _discoverServers;
  Future<void> Function()? onUnauthorized;

  static String normalizeBase(String value) {
    final base = value.trim().replaceAll(RegExp(r'/+$'), '');
    final uri = Uri.tryParse(base);
    if (uri == null ||
        !['http', 'https'].contains(uri.scheme) ||
        uri.host.isEmpty ||
        uri.hasQuery ||
        uri.hasFragment ||
        uri.userInfo.isNotEmpty) {
      throw const FormatException('Enter an HTTP or HTTPS server URL.');
    }
    return base.endsWith('/api/v1') ? base : '$base/api/v1';
  }

  Future<http.Response> _check(http.Response response, String path) async {
    if (response.statusCode == 401 &&
        path != '/auth/login/' &&
        path != '/auth/role-login/' &&
        path != '/auth/logout/') {
      await onUnauthorized?.call();
    }
    return response;
  }

  /// Base path including "/api/v1".
  ///
  /// Priority: URL saved in Settings → `--dart-define=API_BASE_URL` →
  /// the deployed cloud backend. The fallback means the app is usable from
  /// any network; LAN discovery remains available through the explicit
  /// "Auto-detect UEMS server" button for local development.
  Future<String> get _base async {
    final pref = await Storage.prefs;
    final host = pref.getString('api_base_url');

    // If user has manually configured a URL, use it.
    if (host != null && host.isNotEmpty) {
      return normalizeBase(host);
    }

    if (configuredBaseUrl.trim().isNotEmpty) {
      return normalizeBase(configuredBaseUrl);
    }

    return normalizeBase(defaultBaseUrl);
  }

  String? _discoveredBase;
  DateTime? _discoveredAt;
  Future<String>? _discovery;

  void resetDiscovery() {
    _discoveredBase = null;
    _discoveredAt = null;
  }

  Future<String> detectApiBase() {
    if (_discoveredBase != null &&
        _discoveredAt != null &&
        DateTime.now().difference(_discoveredAt!) <
            const Duration(seconds: 30)) {
      return Future.value(_discoveredBase);
    }
    return _discovery ??= _discover().whenComplete(() => _discovery = null);
  }

  Future<String> _discover() async {
    final candidates = (await _discoverServers()).toSet();
    final matches = await Future.wait(
      candidates.map((base) async {
        try {
          final response = await _client
              .get(Uri.parse('${normalizeBase(base)}/health/'))
              .timeout(const Duration(seconds: 2));
          final data = decodeBody(response);
          if (response.statusCode == 200 &&
              data is Map &&
              data['service'] == 'homs' &&
            data['version'] == 1) {
            return normalizeBase(base);
          }
        } catch (_) {
          /* A candidate can disappear while the network changes. */
        }
        return null;
      }),
    );
    final servers = matches.whereType<String>().toList();
    // Prefer a LAN response over the same laptop's loopback address.
    final lan = servers
        .where((s) => !['127.0.0.1', '10.0.2.2'].contains(Uri.parse(s).host))
        .toList();
    if (lan.length > 1) {
      throw const FormatException(
        'Multiple HOMS servers found. Keep only the intended laptop server running, or choose one in advanced settings.',
      );
    }
    if (servers.isEmpty) {
      throw const FormatException(
        'Laptop not found. Start HOMS on the laptop and connect both devices to the same Wi-Fi. Guest Wi-Fi may block device discovery.',
      );
    }
    _discoveredBase = lan.isNotEmpty ? lan.single : servers.first;
    _discoveredAt = DateTime.now();
    return _discoveredBase!;
  }

  Future<Map<String, String>> _headers() async {
    final token = await Storage.accessToken;
    final headers = <String, String>{
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    };
    if (token != null && token.isNotEmpty) {
      headers['Authorization'] = 'Bearer $token';
    }
    return headers;
  }

  Future<http.Response> get(String path, {Map<String, String>? query}) async {
    final uri = Uri.parse(
      '${await _base}$path',
    ).replace(queryParameters: query);
    return _check(
      await _client
          .get(uri, headers: await _headers())
          .timeout(const Duration(seconds: 20)),
      path,
    );
  }

  Future<http.Response> post(
    String path, {
    Map<String, dynamic>? body,
    Map<String, String>? query,
  }) async {
    final uri = Uri.parse(
      '${await _base}$path',
    ).replace(queryParameters: query);
    return _check(
      await _client
          .post(
            uri,
            headers: await _headers(),
            body: body == null ? null : jsonEncode(body),
          )
          .timeout(const Duration(seconds: 20)),
      path,
    );
  }

  /// Convenience: decode JSON response body, or return null on empty/error.
  static dynamic decodeBody(http.Response res) {
    if (res.body.isEmpty) return null;
    try {
      return jsonDecode(res.body);
    } on FormatException {
      return null;
    }
  }

  void dispose() {
    _client.close();
  }
}
