import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'core/app_state.dart';
import 'core/storage.dart';
import 'screens/login_screen.dart';
import 'screens/home_screen.dart';
import 'screens/qr_scanner_screen.dart';
import 'screens/inventory_screen.dart';
import 'screens/settings_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Storage.prefs;
  runApp(
    ChangeNotifierProvider(create: (_) => AppState(), child: const UemsApp()),
  );
}

class UemsApp extends StatelessWidget {
  const UemsApp({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<AppState>(
      builder: (_, auth, child) {
        return MaterialApp(
          key: ValueKey(auth.isAuthenticated),
          title: 'UEMS',
          debugShowCheckedModeBanner: false,
          theme: ThemeData(
            useMaterial3: true,
            colorScheme: const ColorScheme.light(
              primary: Color(0xFF0F172A),
              secondary: Color(0xFF0D9488),
            ),
          ),
          home: auth.isAuthenticated ? const HomeScreen() : const LoginScreen(),
          routes: {
            '/login': (_) =>
                auth.isAuthenticated ? const HomeScreen() : const LoginScreen(),
            '/home': (_) =>
                auth.isAuthenticated ? const HomeScreen() : const LoginScreen(),
            '/scanner': (_) => auth.isAuthenticated
                ? const QrScannerScreen()
                : const LoginScreen(),
            '/inventory': (_) => auth.isAuthenticated
                ? const InventoryScreen()
                : const LoginScreen(),
            '/settings': (_) => const SettingsScreen(),
          },
        );
      },
    );
  }
}
