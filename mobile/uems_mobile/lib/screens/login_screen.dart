import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../core/app_state.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _emailCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  final _formKey = GlobalKey<FormState>();
  bool _detectingIp = false;

  @override
  void dispose() {
    _emailCtrl.dispose();
    _passCtrl.dispose();
    super.dispose();
  }

  Future<void> _demoLogin(String email) async {
    final state = context.read<AppState>();
    await state.demoLogin(email);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          state.error ?? 'Demo signed in',
          style: const TextStyle(color: Colors.white),
        ),
        backgroundColor:
            state.error == null ? const Color(0xFF0D9488) : Colors.red,
      ),
    );
  }

  Future<void> _login() async {
    if (!_formKey.currentState!.validate()) return;
    final state = context.read<AppState>();
    await state.login(_emailCtrl.text.trim(), _passCtrl.text);
    if (mounted && state.error != null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(state.error!), backgroundColor: Colors.red),
      );
    }
  }

  Future<void> _autoDetectIp() async {
    setState(() => _detectingIp = true);
    try {
      final state = context.read<AppState>();
      await state.detectAndSetApiBase();
      if (mounted && state.error == null) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Server found on local network'),
            backgroundColor: Color(0xFF0D9488),
          ),
        );
      } else if (mounted && state.error != null) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Auto-detect failed: ${state.error}'),
            backgroundColor: Colors.red,
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _detectingIp = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Sign in — UEMS')),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Icon(
                  Icons.workspaces_outlined,
                  size: 64,
                  color: Color(0xFF0F172A),
                ),
                const SizedBox(height: 24),
                const Text(
                  'Unified Enterprise Management',
                  style: TextStyle(
                    fontSize: 22,
                    fontWeight: FontWeight.bold,
                    color: Color(0xFF0F172A),
                  ),
                ),
                const Text(
                  'Buildakar Innovation',
                  style: TextStyle(
                    color: Color(0xFF0D9488),
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 32),
                Form(
                  key: _formKey,
                  child: Column(
                    children: [
                      TextFormField(
                        controller: _emailCtrl,
                        decoration: const InputDecoration(
                          labelText: 'Work email',
                          prefixIcon: Icon(Icons.email_outlined),
                        ),
                        keyboardType: TextInputType.emailAddress,
                        validator: (v) =>
                            (v == null || v.isEmpty) ? 'Enter email' : null,
                      ),
                      const SizedBox(height: 16),
                      TextFormField(
                        controller: _passCtrl,
                        decoration: const InputDecoration(
                          labelText: 'Password',
                          prefixIcon: Icon(Icons.lock_outlined),
                        ),
                        obscureText: true,
                        validator: (v) =>
                            (v == null || v.isEmpty) ? 'Enter password' : null,
                      ),
                      const SizedBox(height: 24),
                      Consumer<AppState>(
                        builder: (_, auth, child) => SizedBox(
                          width: double.infinity,
                          height: 50,
                          child: ElevatedButton(
                            onPressed: auth.loading ? null : _login,
                            child: auth.loading
                                ? const SizedBox(
                                    height: 20,
                                    width: 20,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                    ),
                                  )
                                : const Text('Sign in'),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 24),
                const Divider(),
                const SizedBox(height: 16),
                const Text(
                  'Works on any network - the app connects to the UEMS cloud '
                  'server automatically. No laptop or shared Wi-Fi needed.',
                  style: TextStyle(fontSize: 12, color: Colors.grey),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 8),
                SizedBox(
                  width: double.infinity,
                  height: 40,
                  child: OutlinedButton.icon(
                    onPressed: _detectingIp ? null : _autoDetectIp,
                    icon: _detectingIp
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.wifi, size: 16),
                    label: const Text('Auto-detect local server'),
                  ),
                ),
                const SizedBox(height: 24),
                const Text(
                  'Demo accounts (one-click sign in)',
                  style: TextStyle(fontSize: 12, color: Colors.grey),
                ),
                const SizedBox(height: 8),
                Consumer<AppState>(
                  builder: (_, auth, child) => Wrap(
                    spacing: 8,
                    runSpacing: 6,
                    children: [
                      _Chip('Super Admin', 'super@buildakar.com'),
                      _Chip('Resort Inventory', 'invrs@buildakar.com'),
                      _Chip('Pharmacy Inventory', 'inv@buildakar.com'),
                      _Chip('HR Manager', 'hr@buildakar.com'),
                      _Chip('Finance Manager', 'finance@buildakar.com'),
                      _Chip('Staff', 'staff@buildakar.com'),
                    ],
                  ),
                ),
                const SizedBox(height: 24),
                TextButton.icon(
                  onPressed: () => Navigator.pushNamed(context, '/settings'),
                  icon: const Icon(Icons.tune, size: 18),
                  label: const Text('Advanced connection settings'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _Chip extends StatelessWidget {
  final String label;
  final String email;
  const _Chip(this.label, this.email);

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    return FilterChip(
      label: Text(label, style: const TextStyle(fontSize: 11)),
      onSelected: state.loading
          ? null
          : (_) => context
              .findAncestorStateOfType<_LoginScreenState>()
              ?._demoLogin(email),
    );
  }
}
