import 'dart:async';
import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';
import '../core/app_state.dart';
import '../core/api_client.dart';

class QrScannerScreen extends StatefulWidget {
  const QrScannerScreen({super.key, this.apiClient});
  final ApiClient? apiClient;

  @override
  State<QrScannerScreen> createState() => _QrScannerScreenState();
}

class _QrScannerScreenState extends State<QrScannerScreen>
    with WidgetsBindingObserver {
  final MobileScannerController _controller = MobileScannerController(
    autoStart: false,
  );
  final _manualCtrl = TextEditingController();
  bool _processing = false;
  String? _result;
  bool _success = false;
  String _action = 'check_in';
  String? _lastSubmission;
  DateTime? _lastSubmittedAt;
  bool _cameraBusy = false;
  Completer<void>? _cameraIdle;
  StreamSubscription<BarcodeCapture>? _barcodes;
  bool _foreground = true;
  String? _cameraError;
  bool _isScanning = false;

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    unawaited(_barcodes?.cancel());
    _manualCtrl.dispose();
    unawaited(_releaseCamera());
    super.dispose();
  }

  Future<void> _releaseCamera() async {
    await _cameraIdle?.future;
    await _controller.dispose();
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _barcodes = _controller.barcodes.listen(_onDetect);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _foreground = state == AppLifecycleState.resumed;
    unawaited(_syncCamera());
  }

  Future<void> _syncCamera() async {
    if (_cameraBusy || !mounted) return;
    _cameraBusy = true;
    final idle = _cameraIdle = Completer<void>();
    try {
      if (_isScanning && _foreground) {
        await _controller.start();
        if (mounted && (!_isScanning || !_foreground)) await _controller.stop();
        if (mounted) {
          setState(
            () => _cameraError = _controller.value.error == null
                ? null
                : 'Camera unavailable. Allow camera access in Settings, or enter the token below.',
          );
        }
      } else {
        await _controller.stop();
      }
    } catch (_) {
      if (mounted) {
        setState(
          () => _cameraError =
              'Unable to start camera. You can enter the token below.',
        );
      }
    } finally {
      _cameraBusy = false;
      idle.complete();
      if (mounted &&
          _cameraError == null &&
          (_isScanning && _foreground) != _controller.value.isRunning) {
        unawaited(_syncCamera());
      }
    }
  }

  Future<void> _onDetect(BarcodeCapture capture) async {
    if (!_isScanning || !_foreground || !mounted) return;
    for (final barcode in capture.barcodes) {
      final code = barcode.rawValue?.trim();
      if (code != null && code.isNotEmpty) {
        await _verify(code);
        return;
      }
    }
  }

  Future<void> _verify(String token) async {
    if (!mounted || _processing || token.isEmpty) return;
    final key = '$_action:$token';
    final now = DateTime.now();
    if (_success && _lastSubmission == key) return;
    if (_lastSubmission == key &&
        _lastSubmittedAt != null &&
        now.difference(_lastSubmittedAt!) < const Duration(seconds: 5)) {
      return;
    }
    _lastSubmission = key;
    _lastSubmittedAt = now;
    final action = _action;
    setState(() {
      _processing = true;
      _result = null;
      _success = false;
    });
    try {
      var res = await (widget.apiClient ?? ApiClient.instance).post(
        '/attendance/rotating-qr/verify/',
        body: {'token': token, 'action': action},
      );
      final data = ApiClient.decodeBody(res);
      if (res.statusCode == 404 &&
          data is Map &&
          data['code'] == 'one_time_token') {
        res = await (widget.apiClient ?? ApiClient.instance).post(
          '/attendance/one-time-qr/verify/',
          body: {'token': token, 'action': action},
        );
      }
      if (mounted) _handleResult(res);
    } catch (_) {
      if (mounted) {
        setState(() {
          _success = false;
          _result =
              'Could not confirm attendance. Check your connection and attendance history before retrying.';
        });
      }
    } finally {
      if (mounted) setState(() => _processing = false);
    }
  }

  void _handleResult(http.Response res) {
    final data = ApiClient.decodeBody(res);
    final detail = (data is Map && data['detail'] != null)
        ? data['detail'].toString()
        : 'Unknown response';
    setState(() {
      _processing = false;
      _success = res.statusCode == 200;
      _result = detail;
    });
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            res.statusCode == 200
                ? 'Attendance recorded: $detail'
                : 'Rejected: $detail',
          ),
          backgroundColor: res.statusCode == 200
              ? const Color(0xFF0D9488)
              : Colors.red,
          duration: const Duration(seconds: 4),
        ),
      );
    }
  }

  void _manualSubmit() {
    final token = _manualCtrl.text.trim();
    if (token.isEmpty || _processing) return;
    _verify(token);
  }

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    if (!state.isAuthenticated) {
      return const Scaffold(
        body: Center(child: Text('Sign in to record attendance.')),
      );
    }
    return Scaffold(
      appBar: AppBar(
        title: Text(_action == 'check_in' ? 'QR Check In' : 'QR Check Out'),
        actions: [
          PopupMenuButton<String>(
            initialValue: _action,
            enabled: !_processing,
            onSelected: (v) => setState(() => _action = v),
            itemBuilder: (_) => const [
              PopupMenuItem(value: 'check_in', child: Text('Check In')),
              PopupMenuItem(value: 'check_out', child: Text('Check Out')),
            ],
          ),
        ],
      ),
      body: _buildScannerView(),
    );
  }

  Widget _buildScannerView() {
    return ListView(
      children: [
        SizedBox(
          height: 260,
          child: Container(
            decoration: BoxDecoration(
              border: Border.all(color: Colors.grey.shade300),
              borderRadius: BorderRadius.circular(8),
            ),
            child: ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: MobileScanner(
                errorBuilder: (_, error, child) => const Center(
                  child: Text(
                    'Camera unavailable. Check camera permission or use manual entry.',
                    textAlign: TextAlign.center,
                  ),
                ),
                controller: _controller,
              ),
            ),
          ),
        ),
        SizedBox(
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                ElevatedButton.icon(
                  onPressed: _toggleScanner,
                  icon: Icon(_isScanning ? Icons.stop : Icons.camera_alt),
                  label: Text(_isScanning ? 'Stop Camera' : 'Start Camera'),
                ),
                if (_cameraError != null)
                  Text(
                    _cameraError!,
                    style: const TextStyle(color: Colors.red),
                  ),
                if (_processing) const LinearProgressIndicator(),
                const SizedBox(height: 12),
                const Text(
                  'Point camera at the workplace QR code',
                  style: TextStyle(fontSize: 15, color: Color(0xFF64748B)),
                ),
                const SizedBox(height: 16),
                if (_result != null)
                  Container(
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: (_success ? const Color(0xFF0D9488) : Colors.red)
                          .withValues(alpha: 0.1),
                      border: Border.all(
                        color: _success ? const Color(0xFF0D9488) : Colors.red,
                      ),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Row(
                      children: [
                        Icon(
                          _success ? Icons.check_circle : Icons.error,
                          color: _success
                              ? const Color(0xFF0D9488)
                              : Colors.red,
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Text(
                            _result!,
                            style: TextStyle(
                              color: _success
                                  ? const Color(0xFF0D9488)
                                  : Colors.red,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                if (_result != null) const SizedBox(height: 16),
                const Text(
                  'Manual token entry',
                  style: TextStyle(fontSize: 13, color: Color(0xFF64748B)),
                ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _manualCtrl,
                        decoration: const InputDecoration(
                          hintText: 'Paste QR token',
                          border: OutlineInputBorder(),
                        ),
                        onSubmitted: (_) => _manualSubmit(),
                      ),
                    ),
                    const SizedBox(width: 8),
                    IconButton(
                      icon: const Icon(Icons.send),
                      onPressed: _processing ? null : _manualSubmit,
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }

  void _toggleScanner() {
    setState(() {
      _isScanning = !_isScanning;
      _cameraError = null;
    });
    unawaited(_syncCamera());
  }
}
