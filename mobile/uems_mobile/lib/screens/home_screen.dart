import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import '../core/app_state.dart';
import '../core/api_client.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  Map<String, dynamic>? _user;
  List<Map<String, dynamic>> _events = [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    if (!mounted) return;
    setState(() => _loading = true);
    final state = context.read<AppState>();
    try {
      await state.fetchMe();
      _user = state.user;
      final events = <Map<String, dynamic>>[];
      for (var page = 1; ; page++) {
        if (!mounted || !state.isAuthenticated) return;
        final res = await ApiClient.instance.get(
          '/attendance/events/mine/',
          query: {'page': '$page'},
        );
        if (res.statusCode != 200) {
          throw StateError('Attendance request failed');
        }
        final data = ApiClient.decodeBody(res);
        final list = data is List
            ? data
            : data is Map
            ? data['results']
            : null;
        if (list is! List) {
          throw const FormatException('Invalid attendance response');
        }
        events.addAll(list.map((e) => Map<String, dynamic>.from(e as Map)));
        if (data is! Map || data['next'] == null) break;
      }
      _events = events
        ..sort(
          (a, b) => DateTime.parse(
            b['timestamp'],
          ).compareTo(DateTime.parse(a['timestamp'])),
        );
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Could not load attendance. Check your connection.'),
          ),
        );
      }
    }
    if (mounted) setState(() => _loading = false);
  }

  String? get _lastAction {
    if (_events.isEmpty) return null;
    return _events.first['action'] as String?;
  }

  bool get _checkedIn => _lastAction == 'check_in';

  String _todayHours() {
    final minutes = attendanceMinutesToday(_events, DateTime.now());
    return '${minutes ~/ 60}:${(minutes % 60).toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    final state = context.watch<AppState>();
    return Scaffold(
      appBar: AppBar(
        title: const Text('UEMS'),
        automaticallyImplyLeading: false,
        actions: [
          IconButton(
            tooltip: 'Refresh',
            icon: const Icon(Icons.refresh),
            onPressed: _load,
          ),
          IconButton(
            tooltip: 'Settings',
            icon: const Icon(Icons.settings_outlined),
            onPressed: () => Navigator.pushNamed(context, '/settings'),
          ),
          IconButton(
            icon: const Icon(Icons.logout, color: Colors.red),
            onPressed: () async {
              await state.logout();
              if (context.mounted) {
                Navigator.popUntil(context, (route) => route.isFirst);
              }
            },
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              CircleAvatar(
                backgroundColor: const Color(0xFF0F172A),
                child: Text(
                  (_user?['first_name'] as String? ?? '').isEmpty
                      ? 'U'
                      : (_user!['first_name'] as String).substring(0, 1),
                  style: const TextStyle(color: Colors.white),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      _user?['first_name'] ?? 'Employee',
                      style: const TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '${_user?['role_name'] ?? 'Staff'}  •  ${_user?['business_unit_name'] ?? '—'}',
                      style: const TextStyle(
                        fontSize: 12,
                        color: Color(0xFF64748B),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Container(
                        padding: const EdgeInsets.all(8),
                        decoration: BoxDecoration(
                          color:
                              (_checkedIn
                                      ? const Color(0xFF0D9488)
                                      : const Color(0xFF64748B))
                                  .withValues(alpha: 0.1),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Icon(
                          _checkedIn ? Icons.login : Icons.logout,
                          color: _checkedIn
                              ? const Color(0xFF0D9488)
                              : const Color(0xFF64748B),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              _checkedIn ? 'Checked In' : 'Checked Out',
                              style: const TextStyle(
                                fontSize: 16,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                            const SizedBox(height: 2),
                            Text(
                              'Last event: ${_events.isNotEmpty ? DateFormat('HH:mm').format(DateTime.parse(_events.first['timestamp'] as String).toLocal()) : '—'}',
                              style: const TextStyle(
                                fontSize: 12,
                                color: Color(0xFF64748B),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  Row(
                    children: [
                      Expanded(
                        child: _stat(
                          'Hours Today',
                          _todayHours(),
                          Icons.access_time,
                        ),
                      ),
                      Expanded(
                        child: _stat(
                          'Events',
                          '${_events.length}',
                          Icons.event_note,
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 20),
          OutlinedButton.icon(
            icon: const Icon(Icons.inventory_2_outlined),
            label: const Text('Inventory'),
            onPressed: () => Navigator.pushNamed(context, '/inventory'),
          ),
          const SizedBox(height: 16),
          const Text(
            'Recent Activity',
            style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 8),
          if (_events.isEmpty)
            const Center(child: Text('No attendance records yet.'))
          else
            ..._events
                .take(6)
                .map(
                  (e) => Card(
                    margin: const EdgeInsets.only(bottom: 8),
                    child: ListTile(
                      leading: Icon(
                        e['action'] == 'check_in' ? Icons.login : Icons.logout,
                        color: e['action'] == 'check_in'
                            ? const Color(0xFF0D9488)
                            : const Color(0xFF64748B),
                      ),
                      title: Text(
                        e['action'] == 'check_in' ? 'Check In' : 'Check Out',
                      ),
                      subtitle: Text(
                        DateFormat('MMM dd, HH:mm').format(
                          DateTime.parse(e['timestamp'] as String).toLocal(),
                        ),
                      ),
                    ),
                  ),
                ),
          const SizedBox(height: 20),
          SizedBox(
            width: double.infinity,
            height: 50,
            child: ElevatedButton.icon(
              onPressed: () async {
                await Navigator.pushNamed(context, '/scanner');
                if (mounted) await _load();
              },
              icon: const Icon(Icons.qr_code_scanner),
              label: const Text('Scan Attendance QR'),
              style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFF0D9488),
                foregroundColor: Colors.white,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _stat(String label, String value, IconData icon) {
    return Column(
      children: [
        Icon(icon, size: 20, color: const Color(0xFF0D9488)),
        const SizedBox(height: 6),
        Text(
          value,
          style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
        ),
        const SizedBox(height: 4),
        Text(
          label,
          style: const TextStyle(fontSize: 11, color: Color(0xFF64748B)),
        ),
      ],
    );
  }
}

/// Sum actual check-in intervals, clipping overnight shifts to the local day.
int attendanceMinutesToday(List<Map<String, dynamic>> events, DateTime now) {
  final startOfDay = DateTime(now.year, now.month, now.day);
  final ordered =
      events
          .map(
            (event) => (
              time: DateTime.parse(event['timestamp'] as String).toLocal(),
              action: event['action'],
            ),
          )
          .toList()
        ..sort((a, b) => a.time.compareTo(b.time));
  DateTime? checkIn;
  var worked = Duration.zero;
  for (final event in ordered) {
    if (event.time.isAfter(now)) break;
    if (event.action == 'check_in') {
      checkIn ??= event.time.isBefore(startOfDay) ? startOfDay : event.time;
    } else if (event.action == 'check_out' && checkIn != null) {
      if (event.time.isAfter(checkIn)) worked += event.time.difference(checkIn);
      checkIn = null;
    }
  }
  if (checkIn != null) worked += now.difference(checkIn);
  return worked.inMinutes;
}
