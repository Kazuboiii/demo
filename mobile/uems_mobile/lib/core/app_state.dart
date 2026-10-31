import 'package:flutter/foundation.dart';

import '../core/api_client.dart';
import '../core/storage.dart';

/// Holds authentication + app configuration state.
class AppState extends ChangeNotifier {
  AppState() {
    ApiClient.instance.onUnauthorized = expireSession;
    ready = _load();
  }

  late final Future<void> ready;
  bool _disposed = false;

  @override
  void notifyListeners() {
    if (!_disposed) super.notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    ApiClient.instance.onUnauthorized = null;
    super.dispose();
  }

  Future<void> expireSession() async {
    _accessToken = null;
    _refreshToken = null;
    _user = null;
    _error = 'Session expired. Please sign in again.';
    await Storage.clearTokens();
    notifyListeners();
  }

  Future<void> _load() async {
    _accessToken = await Storage.accessToken;
    _refreshToken = await Storage.refreshToken;
    _apiBaseUrl = await Storage.apiBaseUrl;
    _user = null;
    notifyListeners();
  }

  String? _accessToken;
  String? _refreshToken;
  String? _apiBaseUrl;
  Map<String, dynamic>? _user;
  bool _loading = false;
  String? _error;

  String? get accessToken => _accessToken;
  String? get refreshToken => _refreshToken;
  String? get apiBaseUrl => _apiBaseUrl;
  Map<String, dynamic>? get user => _user;
  bool get isAuthenticated => _accessToken != null && _accessToken!.isNotEmpty;
  bool get loading => _loading;
  String? get error => _error;

  set error(String? value) {
    _error = value;
    notifyListeners();
  }

  Future<void> setApiBaseUrl(String url) async {
    final normalized = url.trim().isEmpty ? '' : ApiClient.normalizeBase(url);
    await Storage.setApiBaseUrl(normalized);
    ApiClient.instance.resetDiscovery();
    _apiBaseUrl = normalized;
    notifyListeners();
  }

  Future<void> detectAndSetApiBase() async {
    try {
      ApiClient.instance.resetDiscovery();
      await ApiClient.instance.detectApiBase();
      await Storage.setApiBaseUrl('');
      _apiBaseUrl = '';
      _error = null;
    } catch (_) {
      _error =
          'Laptop not found. Start HOMS and connect both devices to the same Wi-Fi.';
    }
    notifyListeners();
  }

  /// Call after a successful login to store tokens + user.
  Future<void> setAuthenticated({
    required String access,
    String? refresh,
    required Map<String, dynamic> user,
  }) async {
    _loading = false;
    _error = null;
    _accessToken = access;
    _refreshToken = refresh;
    _user = user;
    await Storage.saveTokens(access: access, refresh: refresh);
    notifyListeners();
  }

  Future<void> login(String email, String password) async {
    await ready;
    if (_loading) return;
    _loading = true;
    _error = null;
    notifyListeners();
    try {
      final res = await ApiClient.instance.post(
        '/auth/login/',
        body: {'email': email, 'password': password},
      );
      if (res.statusCode == 200) {
        final data = ApiClient.decodeBody(res) as Map<String, dynamic>;
        await setAuthenticated(
          access: data['access'],
          refresh: data['refresh'],
          user: data['user'],
        );
      } else {
        final data = ApiClient.decodeBody(res);
        _error = (data is Map && data['detail'] != null)
            ? data['detail'].toString()
            : 'Login failed (${res.statusCode})';
      }
    } catch (e) {
      _error = 'Network error: $e';
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  /// One-click sign-in for seeded demo accounts (server-gated by the
  /// DEMO_LOGIN flag and the per-account is_demo marker). Never sends a
  /// password; regular accounts are unaffected.
  Future<void> demoLogin(String email) async {
    await ready;
    if (_loading) return;
    _loading = true;
    _error = null;
    notifyListeners();
    try {
      final res = await ApiClient.instance.post(
        '/auth/demo-login/',
        body: {'email': email},
      );
      if (res.statusCode == 200) {
        final data = ApiClient.decodeBody(res) as Map<String, dynamic>;
        await setAuthenticated(
          access: data['access'],
          refresh: data['refresh'],
          user: data['user'],
        );
      } else {
        final data = ApiClient.decodeBody(res);
        _error = (data is Map && data['detail'] != null)
            ? data['detail'].toString()
            : 'Demo sign-in failed (${res.statusCode})';
      }
    } catch (e) {
      _error = 'Network error: $e';
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  Future<void> logout() async {
    try {
      final refresh = _refreshToken;
      if (refresh != null) {
        await ApiClient.instance.post(
          '/auth/logout/',
          body: {'refresh': refresh},
        );
      }
    } catch (_) {}
    _accessToken = null;
    _refreshToken = null;
    _user = null;
    _error = null;
    await Storage.clearTokens();
    notifyListeners();
  }

  Future<void> fetchMe() async {
    if (!isAuthenticated) return;
    final res = await ApiClient.instance.get('/auth/me/');
    if (res.statusCode == 200) {
      _user = ApiClient.decodeBody(res) as Map<String, dynamic>;
      notifyListeners();
    }
  }
}
