import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

Future<List<String>> discoverServers() async {
  final found = <String>{};

  final nonce = List.generate(
    16,
    (_) => Random.secure().nextInt(256),
  ).map((n) => n.toRadixString(16).padLeft(2, '0')).join();

  final socket = await RawDatagramSocket.bind(InternetAddress.anyIPv4, 0);
  socket.broadcastEnabled = true;

  final subscription = socket.listen((event) {
    if (event != RawSocketEvent.read) return;
    Datagram? packet;
    while ((packet = socket.receive()) != null) {
      try {
        final data = jsonDecode(utf8.decode(packet!.data));
        if (data is Map &&
            data['service'] == 'homs' &&
            data['version'] == 1 &&
            data['nonce'] == nonce &&
            data['port'] == 8000) {
          found.add('http://${packet.address.address}:8000');
        }
      } catch (_) {
        /* Ignore unrelated network traffic. */
      }
    }
  });

  try {
    final request = utf8.encode(
      jsonEncode({'service': 'homs-discover', 'nonce': nonce}),
    );
    for (var attempt = 0; attempt < 3; attempt++) {
      for (final address in ['255.255.255.255', '127.0.0.1']) {
        socket.send(request, InternetAddress(address), 45873);
      }
      await Future<void>.delayed(const Duration(milliseconds: 600));
    }
  } finally {
    await subscription.cancel();
    socket.close();
  }

  // Loopback may be an emulator or the laptop itself.
  return [...found, 'http://127.0.0.1:8000', 'http://10.0.2.2:8000'];
}
