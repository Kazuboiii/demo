import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

class Storage {
  Storage._();
  static final Storage instance = Storage._();
  static final _secure = const FlutterSecureStorage();
  static SharedPreferences? _prefs;

  static Future<SharedPreferences> get prefs async {
    _prefs ??= await SharedPreferences.getInstance();
    return _prefs!;
  }

  static const _accessKey = 'access_token';
  static const _refreshKey = 'refresh_token';
  static const _apiBaseKey = 'api_base_url';

  static Future<String?> get accessToken async => await _secure.read(key: _accessKey);

  static Future<void> saveTokens({required String access, String? refresh}) async {
    await _secure.write(key: _accessKey, value: access);
    if (refresh != null) await _secure.write(key: _refreshKey, value: refresh);
  }

  static Future<String?> get refreshToken async => await _secure.read(key: _refreshKey);

  static Future<void> clearTokens() async {
    await _secure.delete(key: _accessKey);
    await _secure.delete(key: _refreshKey);
  }

  static Future<void> setApiBaseUrl(String url) async {
    final p = await prefs;
    await p.setString(_apiBaseKey, url);
  }

  static Future<String?> get apiBaseUrl async {
    final p = await prefs;
    return p.getString(_apiBaseKey);
  }

  static Future<void> clearAll() async {
    await clearTokens();
    final p = await prefs;
    await p.remove(_apiBaseKey);
  }
}
