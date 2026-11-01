import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../core/app_state.dart';

class LoginScreen extends StatelessWidget {
  const LoginScreen({super.key});

  static const roles = {
    'super_admin': 'Super Admin',
    'resort_inventory_manager': 'Resort Inventory Manager',
    'healthcare_inventory_manager': 'Pharmacy Inventory Manager',
    'hr_manager': 'HR Manager',
    'accountant': 'Finance Manager',
    'employee': 'Staff',
  };

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    return Scaffold(
      appBar: AppBar(title: const Text('Choose your role'), actions: [
        IconButton(tooltip: 'Server settings', icon: const Icon(Icons.settings_outlined),
          onPressed: state.loading ? null : () => Navigator.pushNamed(context, '/settings')),
      ]),
      body: SafeArea(child: Center(child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 520),
        child: ListView(shrinkWrap: true, padding: const EdgeInsets.all(24), children: [
          const Icon(Icons.workspaces_outlined, size: 56),
          const SizedBox(height: 16),
          const Text('Buildakar Innovation', textAlign: TextAlign.center,
            style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
          const SizedBox(height: 12),
          const Text('Select your workspace. No email or password needed.', textAlign: TextAlign.center),
          const SizedBox(height: 24),
          for (final role in roles.entries) Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: OutlinedButton(
              style: OutlinedButton.styleFrom(padding: const EdgeInsets.all(18)),
              onPressed: state.loading ? null : () => state.roleLogin(role.key),
              child: Row(children: [Expanded(child: Text(role.value)), const Icon(Icons.chevron_right)]),
            ),
          ),
          if (state.loading) const Center(child: CircularProgressIndicator()),
          if (state.error != null) Semantics(liveRegion: true, child: Text(state.error!,
            style: TextStyle(color: Theme.of(context).colorScheme.error))),
          const SizedBox(height: 12),
          const Text('For phone attendance testing, select Staff and scan the Resort attendance QR. Activity uses a shared demo employee.',
            textAlign: TextAlign.center),
        ]),
      ))),
    );
  }
}
