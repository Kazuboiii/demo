import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../core/app_state.dart';
import '../core/api_client.dart';

class InventoryScreen extends StatefulWidget {
  const InventoryScreen({super.key});

  @override
  State<InventoryScreen> createState() => _InventoryScreenState();
}

class _InventoryScreenState extends State<InventoryScreen> {
  int _tab = 0;
  List<Map<String, dynamic>> _products = [];
  Map<String, dynamic>? _product;
  List<Map<String, dynamic>> _locations = [], _departments = [], _batches = [];
  int? _locationId, _departmentId, _batchId;
  final _expiryCtrl = TextEditingController();
  String? _msg;
  bool _isError = false;
  bool _loading = false;
  final _qtyCtrl = TextEditingController(text: '1');
  final _batchCtrl = TextEditingController();
  final _barcodeCtrl = TextEditingController();

  @override
  void initState() {
    super.initState();
    _loadProducts();
  }

  void _message(String message, {bool error = true}) {
    if (mounted) {
      setState(() {
        _msg = message;
        _isError = error;
      });
    }
  }

  Future<void> _refresh() async {
    await _loadProducts();
  }

  Future<List<Map<String, dynamic>>> _list(String path) async {
    final items = <Map<String, dynamic>>[];
    for (var page = 1; ; page++) {
      final res = await ApiClient.instance.get(path, query: {'page': '$page'});
      if (res.statusCode != 200) {
        throw StateError('Request failed (${res.statusCode})');
      }
      final data = ApiClient.decodeBody(res);
      final rows = data is List
          ? data
          : data is Map
          ? data['results']
          : null;
      if (rows is! List) throw const FormatException('Invalid list response');
      items.addAll(rows.map((row) => Map<String, dynamic>.from(row as Map)));
      if (data is! Map || data['next'] == null) return items;
    }
  }

  List<Map<String, dynamic>> _alerts = [];

  Future<void> _loadProducts() async {
    try {
      final lists = await Future.wait([
        _list('/inventory/products/'),
        _list('/inventory/locations/'),
        _list('/departments/'),
        _list('/inventory/batches/'),
        _list('/inventory/alerts/'),
      ]);
      if (!mounted) return;
      final bu = context.read<AppState>().user?['business_unit'];
      setState(() {
        _products = lists[0]
            .where(
              (p) =>
                  p['is_active'] == true &&
                  (bu == null || p['business_unit'] == bu),
            )
            .toList();
        _locations = lists[1].where((p) => p['is_active'] == true).toList();
        _departments = lists[2].where((p) => p['is_active'] == true).toList();
        _batches = lists[3];
        _alerts = lists[4];
        final selected = _products.where((p) => p['id'] == _product?['id']);
        _product = selected.isEmpty ? null : selected.first;
        _batchId = null;
      });
    } catch (_) {
      _message('Could not load inventory. Check your connection and sign-in.');
    }
  }

  void _selectProduct(int? id) {
    setState(() {
      _product = id == null ? null : _products.firstWhere((p) => p['id'] == id);
      _locationId = null;
      _departmentId = null;
      _batchId = null;
    });
  }

  Future<void> _lookup(String barcode) async {
    if (barcode.trim().isEmpty || _loading) return;
    setState(() => _loading = true);
    try {
      final bu = context.read<AppState>().user?['business_unit'];
      final res = await ApiClient.instance.get(
        '/inventory/products/lookup/',
        query: {
          'barcode': barcode.trim(),
          if (bu != null) 'business_unit': '$bu',
        },
      );
      final data = ApiClient.decodeBody(res);
      if (res.statusCode != 200 || data is! Map) {
        _message('Product lookup failed (${res.statusCode}).');
        return;
      }
      if (!mounted) return;
      final product = Map<String, dynamic>.from(data);
      if (!_products.any((p) => p['id'] == product['id'])) {
        _products.add(product);
      }
      _selectProduct(product['id'] as int);
      setState(() => _msg = null);
    } catch (_) {
      _message('Could not look up the barcode.');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _receive() async {
    final qty = int.tryParse(_qtyCtrl.text) ?? 0;
    if (_loading) return;
    if (_product == null ||
        _locationId == null ||
        qty <= 0 ||
        _batchCtrl.text.trim().isEmpty) {
      _message(
        'Select a product and location, and enter a batch number and positive quantity.',
      );
      return;
    }
    final expiry = _expiryCtrl.text.trim();
    final date = DateTime.tryParse(expiry);
    if ((expiry.isNotEmpty &&
            (date == null ||
                date.toIso8601String().split('T').first != expiry)) ||
        (_product!['is_perishable'] == true && expiry.isEmpty)) {
      _message(
        'Enter a valid expiry date (YYYY-MM-DD). Perishable products require one.',
      );
      return;
    }
    await _submit('/inventory/receipts/', {
      'reference': 'RCPT-${DateTime.now().microsecondsSinceEpoch}',
      'business_unit': _product!['business_unit'],
      'location': _locationId,
      'lines': [
        {
          'product': _product!['id'],
          'batch_number': _batchCtrl.text.trim(),
          'expiry_date': expiry.isEmpty ? null : expiry,
          'quantity': qty,
          'unit_cost': '0.00',
        },
      ],
    }, 'Stock received successfully.');
  }

  Future<void> _issue() async {
    if (_loading) return;
    final qty = int.tryParse(_qtyCtrl.text) ?? 0;
    if (_product == null ||
        _batchId == null ||
        _departmentId == null ||
        qty <= 0) {
      _message(
        'Select a product, usable batch and department, and enter a positive quantity.',
      );
      return;
    }
    await _submit('/inventory/issues/', {
      'reference': 'ISSUE-${DateTime.now().microsecondsSinceEpoch}',
      'business_unit': _product!['business_unit'],
      'department': _departmentId,
      'lines': [
        {'product_batch': _batchId, 'quantity': qty},
      ],
    }, 'Stock issued successfully.');
  }

  Future<void> _submit(
    String path,
    Map<String, dynamic> body,
    String success,
  ) async {
    setState(() => _loading = true);
    try {
      final res = await ApiClient.instance.post(path, body: body);
      if (!mounted) return;
      if (res.statusCode == 201) {
        _message(success, error: false);
        _qtyCtrl.text = '1';
        await _loadProducts();
      } else {
        final data = ApiClient.decodeBody(res);
        _message(
          'Request rejected (${res.statusCode}): ${data ?? 'Invalid server response'}',
        );
      }
    } catch (_) {
      _message(
        'Could not confirm the stock change. Check stock history before retrying.',
      );
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Widget _choice(
    String label,
    List<Map<String, dynamic>> items,
    int? selected,
    ValueChanged<int?> change, {
    String name = 'name',
  }) {
    return DropdownButtonFormField<int>(
      key: ValueKey('$label:$selected:${_product?['id']}'),
      initialValue: items.any((p) => p['id'] == selected) ? selected : null,
      isExpanded: true,
      decoration: InputDecoration(
        labelText: label,
        border: const OutlineInputBorder(),
      ),
      items: items
          .map(
            (p) => DropdownMenuItem(
              value: p['id'] as int,
              child: Text('${p[name]}', overflow: TextOverflow.ellipsis),
            ),
          )
          .toList(),
      onChanged: _loading ? null : change,
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Inventory')),
      body: _alerts.isNotEmpty
          ? _alertsBanner()
          : IndexedStack(
              index: _tab,
              children: [_productsTab(), _receiveTab(), _issueTab()],
            ),
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _tab,
        onTap: _loading ? null : (i) => setState(() => _tab = i),
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.list), label: 'Products'),
          BottomNavigationBarItem(
            icon: Icon(Icons.inventory_2),
            label: 'Receive',
          ),
          BottomNavigationBarItem(icon: Icon(Icons.output), label: 'Issue'),
        ],
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: _loading ? null : _refresh,
        child: const Icon(Icons.refresh),
      ),
    );
  }

  Widget _alertsBanner() {
    return Scaffold(
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            color: Colors.red.shade50,
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      const Icon(Icons.warning_amber, color: Colors.red, size: 24),
                      const SizedBox(width: 12),
                      const Expanded(
                        child: Text(
                          'Low Stock Alerts',
                          style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                        ),
                      ),
                      IconButton(
                        icon: const Icon(Icons.close, color: Colors.red),
                        onPressed: () => setState(() {}),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  ..._alerts.map((a) {
                    final product = a['product'] as Map<String, dynamic>?;
                    return Card(
                      margin: const EdgeInsets.only(bottom: 8),
                      color: Colors.red.shade100,
                      child: ListTile(
                        leading: const Icon(Icons.inventory_2, color: Colors.red),
                        title: Text(product?['name'] ?? 'Product'),
                        subtitle: Text(
                          'Usable: ${product?['usable_stock']} / Min: ${product?['min_stock']} ${product?['unit'] ?? ""}',
                        ),
                      ),
                    );
                  }),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _productsTab() {
    return ListView.builder(
      itemCount: _products.length,
      itemBuilder: (_, i) => Card(
        margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        child: ListTile(
          title: Text(_products[i]['name'] as String? ?? 'Product'),
          subtitle: Text(
            'SKU: ${_products[i]['sku']}  •  Usable: ${_products[i]['usable_stock']} ${_products[i]['unit']}',
          ),
          trailing: Text(
            (_products[i]['is_low_stock'] as bool? ?? false)
                ? 'LOW STOCK'
                : 'OK',
            style: TextStyle(
              color: (_products[i]['is_low_stock'] as bool? ?? false)
                  ? Colors.red
                  : const Color(0xFF0D9488),
              fontWeight: FontWeight.bold,
            ),
          ),
        ),
      ),
    );
  }

  Widget _receiveTab() {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Text(
            'Receive Stock',
            style: TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.bold,
              color: Color(0xFF0F172A),
            ),
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _barcodeCtrl,
                  decoration: const InputDecoration(
                    labelText: 'Scan / enter barcode',
                    border: OutlineInputBorder(),
                  ),
                  onSubmitted: (v) => _lookup(v),
                ),
              ),
              const SizedBox(width: 8),
              IconButton(
                icon: const Icon(Icons.qr_code_scanner),
                onPressed: _loading ? null : () => _lookup(_barcodeCtrl.text),
              ),
            ],
          ),
          const SizedBox(height: 12),
          _choice(
            'Product',
            _products,
            _product?['id'] as int?,
            _selectProduct,
          ),
          const SizedBox(height: 12),
          _choice(
            'Location',
            _locations
                .where((p) => p['business_unit'] == _product?['business_unit'])
                .toList(),
            _locationId,
            (v) => setState(() => _locationId = v),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _batchCtrl,
            decoration: const InputDecoration(
              labelText: 'Batch / lot number',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _qtyCtrl,
                  decoration: const InputDecoration(
                    labelText: 'Quantity',
                    border: OutlineInputBorder(),
                  ),
                  keyboardType: TextInputType.number,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: TextField(
                  controller: _expiryCtrl,
                  decoration: const InputDecoration(
                    labelText: 'Expiry date (YYYY-MM-DD)',
                    border: OutlineInputBorder(),
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 20),
          if (_msg != null)
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: _isError
                    ? Colors.red.withValues(alpha: 0.1)
                    : const Color(0xFF0D9488).withValues(alpha: 0.1),
                border: Border.all(
                  color: _isError ? Colors.red : const Color(0xFF0D9488),
                ),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                _msg!,
                style: TextStyle(
                  color: _isError ? Colors.red : const Color(0xFF0D9488),
                ),
              ),
            ),
          if (_msg != null) const SizedBox(height: 12),
          SizedBox(
            height: 50,
            child: ElevatedButton(
              onPressed: _loading ? null : _receive,
              child: _loading
                  ? const SizedBox(
                      height: 20,
                      width: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Text('Confirm Receive'),
            ),
          ),
        ],
      ),
    );
  }

  Widget _issueTab() {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Text(
            'Issue Stock',
            style: TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.bold,
              color: Color(0xFF0F172A),
            ),
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _barcodeCtrl,
                  decoration: const InputDecoration(
                    labelText: 'Scan / enter barcode',
                    border: OutlineInputBorder(),
                  ),
                  onSubmitted: (v) => _lookup(v),
                ),
              ),
              const SizedBox(width: 8),
              IconButton(
                icon: const Icon(Icons.qr_code_scanner),
                onPressed: _loading ? null : () => _lookup(_barcodeCtrl.text),
              ),
            ],
          ),
          const SizedBox(height: 12),
          _choice(
            'Product',
            _products,
            _product?['id'] as int?,
            _selectProduct,
          ),
          const SizedBox(height: 12),
          _choice(
            'Department',
            _departments
                .where((p) => p['business_unit'] == _product?['business_unit'])
                .toList(),
            _departmentId,
            (v) => setState(() => _departmentId = v),
          ),
          const SizedBox(height: 12),
          _choice(
            'Batch',
            _batches
                .where(
                  (p) =>
                      p['product'] == _product?['id'] &&
                      (p['usable_quantity'] as num? ?? 0) > 0,
                )
                .toList(),
            _batchId,
            (v) => setState(() => _batchId = v),
            name: 'batch_number',
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _qtyCtrl,
            decoration: const InputDecoration(
              labelText: 'Quantity to issue',
              border: OutlineInputBorder(),
            ),
            keyboardType: TextInputType.number,
          ),
          const SizedBox(height: 20),
          if (_msg != null)
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: _isError
                    ? Colors.red.withValues(alpha: 0.1)
                    : const Color(0xFF0D9488).withValues(alpha: 0.1),
                border: Border.all(
                  color: _isError ? Colors.red : const Color(0xFF0D9488),
                ),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                _msg!,
                style: TextStyle(
                  color: _isError ? Colors.red : const Color(0xFF0D9488),
                ),
              ),
            ),
          if (_msg != null) const SizedBox(height: 12),
          SizedBox(
            height: 50,
            child: ElevatedButton(
              onPressed: _loading ? null : _issue,
              child: _loading
                  ? const SizedBox(
                      height: 20,
                      width: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Text('Confirm Issue'),
            ),
          ),
        ],
      ),
    );
  }

  @override
  void dispose() {
    _expiryCtrl.dispose();
    _qtyCtrl.dispose();
    _batchCtrl.dispose();
    _barcodeCtrl.dispose();
    super.dispose();
  }
}
