import 'package:intl/intl.dart';

class User {
  final int id;
  final String email;
  final String firstName;
  final String lastName;
  final String? roleCode;
  final String? roleName;
  final int? businessUnit;
  final String? businessUnitName;
  final String? businessUnitCode;
  final bool isActive;
  final bool isApproved;

  User({
    required this.id,
    required this.email,
    required this.firstName,
    required this.lastName,
    this.roleCode,
    this.roleName,
    this.businessUnit,
    this.businessUnitName,
    this.businessUnitCode,
    this.isActive = true,
    this.isApproved = true,
  });

  String get displayName =>
      (firstName.isNotEmpty || lastName.isNotEmpty)
          ? '$firstName $lastName'.trim()
          : email;

  factory User.fromJson(Map<String, dynamic> j) => User(
        id: j['id'] as int,
        email: j['email'] as String? ?? '',
        firstName: j['first_name'] as String? ?? '',
        lastName: j['last_name'] as String? ?? '',
        roleCode: j['role_code'] as String?,
        roleName: j['role_name'] as String?,
        businessUnit: j['business_unit'] as int?,
        businessUnitName: j['business_unit_name'] as String?,
        businessUnitCode: j['business_unit_code'] as String?,
        isActive: j['is_active'] as bool? ?? true,
        isApproved: j['is_approved'] as bool? ?? true,
      );
}

class Employee {
  final int id;
  final String employeeId;
  final String designation;
  final bool isActive;
  final String? departmentName;
  final String? businessUnitName;
  final String? employeeName;

  Employee({
    required this.id,
    required this.employeeId,
    required this.designation,
    required this.isActive,
    this.departmentName,
    this.businessUnitName,
    this.employeeName,
  });

  factory Employee.fromJson(Map<String, dynamic> j) => Employee(
        id: j['id'] as int,
        employeeId: j['employee_id'] as String? ?? '',
        designation: j['designation'] as String? ?? '',
        isActive: j['is_active'] as bool? ?? true,
        departmentName: j['department_name'] as String?,
        businessUnitName: j['business_unit_name'] as String?,
        employeeName: j['user_name'] as String?,
      );
}

class Product {
  final int id;
  final String sku;
  final String? barcode;
  final String name;
  final String category;
  final String unit;
  final int minStock;
  final bool isPerishable;
  final bool batchTrackingRequired;
  final bool isActive;
  final int? businessUnit;
  final double usableStock;
  final bool isLowStock;

  Product({
    required this.id,
    required this.sku,
    this.barcode,
    required this.name,
    required this.category,
    required this.unit,
    required this.minStock,
    required this.isPerishable,
    required this.batchTrackingRequired,
    required this.isActive,
    this.businessUnit,
    required this.usableStock,
    required this.isLowStock,
  });

  factory Product.fromJson(Map<String, dynamic> j) => Product(
        id: j['id'] as int,
        sku: j['sku'] as String? ?? '',
        barcode: j['barcode'] as String?,
        name: j['name'] as String? ?? '',
        category: j['category'] as String? ?? '',
        unit: j['unit'] as String? ?? 'piece',
        minStock: (j['min_stock'] as num?)?.toInt() ?? 0,
        isPerishable: j['is_perishable'] as bool? ?? false,
        batchTrackingRequired: j['batch_tracking_required'] as bool? ?? false,
        isActive: j['is_active'] as bool? ?? true,
        businessUnit: j['business_unit'] as int?,
        usableStock: (j['usable_stock'] as num?)?.toDouble() ?? 0.0,
        isLowStock: j['is_low_stock'] as bool? ?? false,
      );
}

class Batch {
  final int lotId;
  final String productName;
  final String sku;
  final String? barcode;
  final String batchNumber;
  final String? expiryDate;
  final String status;
  final int usableQuantity;
  final String unit;
  final int businessUnit;
  final String businessUnitName;
  final String? location;
  final int? locationId;

  Batch({
    required this.lotId,
    required this.productName,
    required this.sku,
    this.barcode,
    required this.batchNumber,
    this.expiryDate,
    required this.status,
    required this.usableQuantity,
    required this.unit,
    required this.businessUnit,
    required this.businessUnitName,
    this.location,
    this.locationId,
  });

  bool get isExpired {
    if (expiryDate == null || expiryDate!.isEmpty) return false;
    try {
      return DateTime.parse(expiryDate!).isBefore(DateTime.now());
    } catch (_) {
      return false;
    }
  }

  factory Batch.fromJson(Map<String, dynamic> j) => Batch(
        lotId: j['lot_id'] as int,
        productName: j['product_name'] as String? ?? '',
        sku: j['sku'] as String? ?? '',
        barcode: j['barcode'] as String?,
        batchNumber: j['batch_number'] as String? ?? '',
        expiryDate: j['expiry_date'] as String?,
        status: j['status'] as String? ?? 'usable',
        usableQuantity: (j['usable_quantity'] as num?)?.toInt() ?? 0,
        unit: j['unit'] as String? ?? 'piece',
        businessUnit: j['business_unit'] as int,
        businessUnitName: j['business_unit_name'] as String? ?? '',
        location: j['location'] as String?,
        locationId: j['location_id'] as int?,
      );
}

class AttendanceEvent {
  final int id;
  final String employeeId;
  final String employeeName;
  final String action; // check_in / check_out
  final DateTime timestamp;
  final String source;
  final String? businessUnitName;

  AttendanceEvent({
    required this.id,
    required this.employeeId,
    required this.employeeName,
    required this.action,
    required this.timestamp,
    required this.source,
    this.businessUnitName,
  });

  String get formattedTime =>
      DateFormat('HH:mm', 'en_NP').format(timestamp.toLocal());
  String get formattedDate =>
      DateFormat('yyyy-MM-dd', 'en_NP').format(timestamp.toLocal());

  factory AttendanceEvent.fromJson(Map<String, dynamic> j) => AttendanceEvent(
        id: j['id'] as int,
        employeeId: j['employee_id'] as String? ?? '',
        employeeName: j['employee_name'] as String? ?? '',
        action: j['action'] as String? ?? '',
        timestamp: DateTime.parse(j['timestamp'] as String).toLocal(),
        source: j['source'] as String? ?? '',
        businessUnitName: j['business_unit_name'] as String?,
      );
}

class Trip {
  final int id;
  final String requestReference;
  final String driverName;
  final String vehiclePlate;
  final String status;
  final DateTime? startTime;
  final DateTime? pickupTime;
  final DateTime? dropoffTime;
  final DateTime? endTime;
  final DateTime createdAt;

  Trip({
    required this.id,
    required this.requestReference,
    required this.driverName,
    required this.vehiclePlate,
    required this.status,
    this.startTime,
    this.pickupTime,
    this.dropoffTime,
    this.endTime,
    required this.createdAt,
  });

  factory Trip.fromJson(Map<String, dynamic> j) => Trip(
        id: j['id'] as int,
        requestReference: j['request_reference'] as String? ?? '',
        driverName: j['driver_name'] as String? ?? '',
        vehiclePlate: j['vehicle_plate'] as String? ?? '',
        status: j['status'] as String? ?? '',
        startTime: j['start_time'] == null
            ? null
            : DateTime.parse(j['start_time']).toLocal(),
        pickupTime: j['pickup_time'] == null
            ? null
            : DateTime.parse(j['pickup_time']).toLocal(),
        dropoffTime: j['dropoff_time'] == null
            ? null
            : DateTime.parse(j['dropoff_time']).toLocal(),
        endTime: j['end_time'] == null
            ? null
            : DateTime.parse(j['end_time']).toLocal(),
        createdAt: j['created_at'] == null
            ? DateTime.now()
            : DateTime.parse(j['created_at']).toLocal(),
      );
}

class TransportRequest {
  final int id;
  final String reference;
  final String patientName;
  final String pickupLocation;
  final String dropoffLocation;
  final String status;

  TransportRequest({
    required this.id,
    required this.reference,
    required this.patientName,
    required this.pickupLocation,
    required this.dropoffLocation,
    required this.status,
  });

  factory TransportRequest.fromJson(Map<String, dynamic> j) => TransportRequest(
        id: j['id'] as int,
        reference: j['reference'] as String? ?? '',
        patientName: j['patient_name'] as String? ?? '',
        pickupLocation: j['pickup_location'] as String? ?? '',
        dropoffLocation: j['dropoff_location'] as String? ?? '',
        status: j['status'] as String? ?? '',
      );
}
