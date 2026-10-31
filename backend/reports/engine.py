"""Central reporting engine.

Every report shown in the UI, printed, or exported is produced here so the
dashboard, table view and downloaded file always use the same queryset,
division scope, date filters and totals. Totals are summed from the report
rows; nothing is hard-coded or estimated.

Payroll and transport figures are read from their own source records. They are
never derived from inventory quantities.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from attendance.models import AttendanceEvent, LeaveRequest
from core.models import Employee
from core.permissions import accessible_divisions, role_can
from fleet.models import Vehicle
from inventory.models import (
    Product,
    ProductBatch,
    PurchaseOrder,
    StockMovement,
    StockReceipt,
    StockReceiptLine,
    Supplier,
)
from nemt.models import RideCostEstimate, TransportRequest, Trip
from payroll.models import PayrollLine, PayrollRun, SalaryStructure


class ReportError(Exception):
    """Base class for report failures."""


class ReportNotFound(ReportError):
    pass


class ReportPermissionDenied(ReportError):
    pass


def _col(key, label, kind="text"):
    return {"key": key, "label": label, "type": kind}


@dataclass(frozen=True)
class ReportSpec:
    key: str
    title: str
    module: str
    description: str
    columns: tuple
    totals: tuple = ()
    filters: tuple = ("business_unit", "start", "end")
    default_days: int | None = None
    builder: str = ""

    def as_dict(self):
        return {
            "key": self.key,
            "title": self.title,
            "module": self.module,
            "description": self.description,
            "columns": list(self.columns),
            "totals": list(self.totals),
            "filters": list(self.filters),
        }


REPORTS = {}


def _register(spec):
    REPORTS[spec.key] = spec
    return spec


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

_register(ReportSpec(
    "inventory-stock-summary", "Inventory Stock Summary", "inventory",
    "Usable stock, minimum levels and valuation per product for the selected division.",
    (
        _col("sku", "SKU"), _col("name", "Product"), _col("category", "Category"),
        _col("division", "Division"), _col("unit", "Unit"),
        _col("usable_stock", "Usable Stock", "number"),
        _col("min_stock", "Minimum", "number"),
        _col("low_stock", "Low Stock", "boolean"),
        _col("stock_value", "Stock Value", "money"),
    ),
    totals=("usable_stock", "stock_value"),
    filters=("business_unit", "status", "search"),
    builder="stock_summary",
))
_register(ReportSpec(
    "inventory-batches", "Inventory Batches", "inventory",
    "Every batch/lot with expiry, remaining quantity and value.",
    (
        _col("batch_number", "Batch"), _col("product", "Product"),
        _col("sku", "SKU"), _col("division", "Division"),
        _col("expiry_date", "Expiry", "date"), _col("status", "Status"),
        _col("quantity_remaining", "Remaining", "number"),
        _col("unit_cost", "Unit Cost", "money"),
        _col("stock_value", "Value", "money"),
    ),
    totals=("quantity_remaining", "stock_value"),
    filters=("business_unit", "status", "search", "start", "end"),
    builder="batches",
))
_register(ReportSpec(
    "inventory-movements", "Stock Movement Ledger", "inventory",
    "Immutable ledger of every receipt, issue, adjustment, transfer and sale.",
    (
        _col("created_at", "Time", "datetime"), _col("division", "Division"),
        _col("reference", "Reference"), _col("movement_type", "Type"),
        _col("product", "Product"), _col("batch_number", "Batch"),
        _col("quantity", "Quantity", "number"),
        _col("quantity_before", "Before", "number"),
        _col("quantity_after", "After", "number"),
        _col("performed_by", "Performed By"),
    ),
    totals=("quantity",),
    filters=("business_unit", "start", "end", "status", "search"),
    default_days=30,
    builder="movements",
))
_register(ReportSpec(
    "inventory-low-stock", "Low Stock", "inventory",
    "Products whose usable stock is at or below the configured minimum.",
    (
        _col("sku", "SKU"), _col("name", "Product"), _col("division", "Division"),
        _col("usable_stock", "Usable", "number"), _col("min_stock", "Minimum", "number"),
        _col("shortfall", "Shortfall", "number"), _col("unit", "Unit"),
    ),
    totals=("usable_stock", "shortfall"),
    filters=("business_unit", "search"),
    builder="low_stock",
))
_register(ReportSpec(
    "inventory-expiry", "Expiry Watch", "inventory",
    "Usable batches expiring within the selected window, including already expired lots.",
    (
        _col("product", "Product"), _col("batch_number", "Batch"),
        _col("division", "Division"), _col("expiry_date", "Expiry", "date"),
        _col("days_to_expiry", "Days To Expiry", "number"),
        _col("quantity_remaining", "Remaining", "number"),
        _col("stock_value", "Value", "money"),
    ),
    totals=("quantity_remaining", "stock_value"),
    filters=("business_unit", "start", "end", "search"),
    builder="expiry",
))
_register(ReportSpec(
    "procurement-spend", "Procurement Spend", "procurement",
    "Received goods value by supplier and division, from posted receipts only.",
    (
        _col("division", "Division"), _col("supplier", "Supplier"),
        _col("receipts", "Receipts", "number"),
        _col("quantity", "Quantity", "number"),
        _col("total_value", "Total Value", "money"),
    ),
    totals=("receipts", "quantity", "total_value"),
    filters=("business_unit", "start", "end", "search"),
    builder="procurement_spend",
))
_register(ReportSpec(
    "procurement-suppliers", "Supplier Directory", "procurement",
    "Active suppliers scoped to the selected division.",
    (
        _col("code", "Code"), _col("name", "Supplier"), _col("division", "Division"),
        _col("contact_person", "Contact"), _col("phone", "Phone"),
        _col("email", "Email"), _col("payment_terms_days", "Terms (days)", "number"),
    ),
    filters=("business_unit", "search"),
    builder="suppliers",
))
_register(ReportSpec(
    "procurement-purchase-orders", "Purchase Orders", "procurement",
    "Purchase orders with ordered value and receipt progress.",
    (
        _col("reference", "Reference"), _col("division", "Division"),
        _col("supplier", "Supplier"), _col("status", "Status"),
        _col("order_date", "Order Date", "date"), _col("expected_date", "Expected", "date"),
        _col("ordered", "Ordered", "number"), _col("received", "Received", "number"),
        _col("total_value", "Value", "money"),
    ),
    totals=("ordered", "received", "total_value"),
    filters=("business_unit", "start", "end", "status", "search"),
    builder="purchase_orders",
))
_register(ReportSpec(
    "accounting-inventory-valuation", "Inventory Valuation", "finance",
    "Stock value grouped by division and product category.",
    (
        _col("division", "Division"), _col("category", "Category"),
        _col("products", "Products", "number"),
        _col("quantity", "Quantity", "number"),
        _col("stock_value", "Stock Value", "money"),
    ),
    totals=("products", "quantity", "stock_value"),
    filters=("business_unit", "search"),
    builder="inventory_valuation",
))
_register(ReportSpec(
    "accounting-payroll-summary", "Payroll Summary", "finance",
    "Payroll runs and totals calculated from salary structures and attendance.",
    (
        _col("reference", "Reference"), _col("division", "Division"),
        _col("period_start", "Period Start", "date"), _col("period_end", "Period End", "date"),
        _col("status", "Status"), _col("employees", "Employees", "number"),
        _col("gross", "Gross", "money"), _col("deductions", "Deductions", "money"),
        _col("net", "Net", "money"),
    ),
    totals=("employees", "gross", "deductions", "net"),
    filters=("business_unit", "start", "end", "status"),
    builder="payroll_summary",
))
_register(ReportSpec(
    "accounting-transport-cost", "Transport Cost", "finance",
    "Transport cost estimates computed from documented distance, time and rate inputs.",
    (
        _col("reference", "Reference"), _col("division", "Division"),
        _col("request_reference", "Request"), _col("distance_km", "Distance (km)", "number"),
        _col("duration_minutes", "Minutes", "number"),
        _col("base_fee", "Base Fee", "money"), _col("tolls", "Tolls", "money"),
        _col("total_cost", "Total", "money"), _col("created_at", "Created", "datetime"),
    ),
    totals=("distance_km", "duration_minutes", "base_fee", "tolls", "total_cost"),
    filters=("business_unit", "start", "end", "search"),
    builder="transport_cost",
))
_register(ReportSpec(
    "hr-employees", "Employee Directory", "hr",
    "Active and inactive employee records by division and department.",
    (
        _col("employee_id", "Employee ID"), _col("name", "Name"),
        _col("division", "Division"), _col("department", "Department"),
        _col("designation", "Designation"), _col("hire_date", "Hire Date", "date"),
        _col("is_active", "Active", "boolean"),
    ),
    totals=("is_active",),
    filters=("business_unit", "status", "search"),
    builder="hr_employees",
))
_register(ReportSpec(
    "hr-attendance", "Attendance Summary", "hr",
    "Check-in/check-out counts and distinct attendance days per employee.",
    (
        _col("employee_id", "Employee ID"), _col("name", "Name"),
        _col("division", "Division"), _col("check_ins", "Check-ins", "number"),
        _col("check_outs", "Check-outs", "number"),
        _col("days_present", "Days Present", "number"),
    ),
    totals=("check_ins", "check_outs", "days_present"),
    filters=("business_unit", "start", "end", "search"),
    default_days=30,
    builder="hr_attendance",
))
_register(ReportSpec(
    "hr-leave", "Leave Requests", "hr",
    "Leave requests overlapping the selected period.",
    (
        _col("employee_id", "Employee ID"), _col("name", "Name"),
        _col("division", "Division"), _col("start_date", "Start", "date"),
        _col("end_date", "End", "date"), _col("status", "Status"),
        _col("reason", "Reason"),
    ),
    filters=("business_unit", "start", "end", "status", "search"),
    builder="hr_leave",
))
_register(ReportSpec(
    "payroll-register", "Payroll Register", "payroll",
    "Employee-level payroll lines with gross, deductions and net pay.",
    (
        _col("reference", "Run"), _col("division", "Division"),
        _col("employee_id", "Employee ID"), _col("name", "Name"),
        _col("basic_salary", "Basic", "money"), _col("allowances", "Allowances", "money"),
        _col("deductions", "Deductions", "money"), _col("gross", "Gross", "money"),
        _col("net", "Net", "money"), _col("days_present", "Days", "number"),
    ),
    totals=("basic_salary", "allowances", "deductions", "gross", "net", "days_present"),
    filters=("business_unit", "start", "end", "status", "search"),
    builder="payroll_register",
))
_register(ReportSpec(
    "payroll-salary-structures", "Salary Structures", "payroll",
    "Configured salary components used to calculate payroll.",
    (
        _col("employee_id", "Employee ID"), _col("name", "Name"),
        _col("division", "Division"), _col("basic_salary", "Basic", "money"),
        _col("housing_allowance", "Housing", "money"),
        _col("transport_allowance", "Transport", "money"),
        _col("other_allowance", "Other", "money"),
        _col("tax_rate_percent", "Tax %", "number"),
        _col("other_deduction", "Other Deduction", "money"),
        _col("gross", "Gross", "money"),
    ),
    totals=("basic_salary", "housing_allowance", "transport_allowance",
            "other_allowance", "other_deduction", "gross"),
    filters=("business_unit", "status", "search"),
    builder="salary_structures",
))
_register(ReportSpec(
    "transport-requests", "Transport Requests", "transport",
    "Patient transport requests by division and status.",
    (
        _col("reference", "Reference"), _col("division", "Division"),
        _col("patient_name", "Patient"), _col("pickup_location", "Pickup"),
        _col("dropoff_location", "Drop-off"), _col("pickup_time", "Pickup Time", "datetime"),
        _col("status", "Status"), _col("driver", "Driver"), _col("vehicle", "Vehicle"),
    ),
    filters=("business_unit", "start", "end", "status", "search"),
    builder="transport_requests",
))
_register(ReportSpec(
    "transport-trips", "Trip Log", "transport",
    "Completed and in-progress trips with driver, vehicle and timings.",
    (
        _col("request_reference", "Request"), _col("division", "Division"),
        _col("driver", "Driver"), _col("vehicle", "Vehicle"),
        _col("status", "Status"), _col("start_time", "Start", "datetime"),
        _col("end_time", "End", "datetime"),
    ),
    filters=("business_unit", "start", "end", "status", "search"),
    builder="transport_trips",
))
_register(ReportSpec(
    "transport-cost-estimates", "Transport Cost Estimates", "transport",
    "Ride cost estimates with their rate breakdown.",
    (
        _col("reference", "Reference"), _col("division", "Division"),
        _col("distance_km", "Distance (km)", "number"),
        _col("duration_minutes", "Minutes", "number"),
        _col("per_km_rate", "Per km", "money"),
        _col("driver_hourly_rate", "Driver / hour", "money"),
        _col("tolls", "Tolls", "money"), _col("total_cost", "Total", "money"),
    ),
    totals=("distance_km", "duration_minutes", "tolls", "total_cost"),
    filters=("business_unit", "start", "end", "search"),
    builder="transport_cost_estimates",
))
_register(ReportSpec(
    "management-overview", "Organization Overview", "reports",
    "Division scorecard combining HR, inventory, fleet, transport and payroll facts.",
    (
        _col("division", "Division"), _col("employees", "Employees", "number"),
        _col("products", "Products", "number"),
        _col("usable_stock", "Usable Stock", "number"),
        _col("stock_value", "Stock Value", "money"),
        _col("low_stock", "Low Stock", "number"),
        _col("vehicles", "Vehicles", "number"),
        _col("pending_transport", "Pending Transport", "number"),
        _col("open_purchase_orders", "Open POs", "number"),
        _col("payroll_net", "Payroll Net", "money"),
    ),
    totals=("employees", "products", "usable_stock", "stock_value", "low_stock",
            "vehicles", "pending_transport", "open_purchase_orders", "payroll_net"),
    filters=("business_unit", "start", "end"),
    builder="management_overview",
))


def catalog():
    return [spec.as_dict() for spec in REPORTS.values()]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_date(value, label):
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ReportError(f"{label} must be an ISO date (YYYY-MM-DD).")


def _to_decimal(value):
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _json_safe(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _scope(qs, division, divisions, field="business_unit"):
    if division is not None:
        return qs.filter(**{field: division})
    return qs.filter(**{f"{field}__in": divisions})


def _date_between(qs, field, start, end):
    if start is not None:
        qs = qs.filter(**{f"{field}__date__gte": start})
    if end is not None:
        qs = qs.filter(**{f"{field}__date__lte": end})
    return qs


def resolve_division(user, params):
    """Resolve a division selector from query params with access enforcement."""
    divisions = accessible_divisions(user)
    raw = params.get("business_unit") or params.get("division")
    if raw in (None, "", "all", "ALL"):
        if divisions.count() == 1:
            return divisions.first(), divisions
        return None, divisions
    unit = None
    try:
        unit = divisions.get(pk=int(raw))
    except (ValueError, TypeError, divisions.model.DoesNotExist):
        unit = divisions.filter(code__iexact=str(raw)).first()
    if unit is None:
        from core.models import BusinessUnit

        if str(raw).isdigit() and BusinessUnit.objects.filter(pk=int(raw)).exists():
            raise ReportPermissionDenied(
                "You are not authorized for this business division."
            )
        raise ReportNotFound("Business division not found.")
    return unit, divisions


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _usable_batch_filter(today):
    return Q(batches__status=ProductBatch.STATUS_USABLE) & (
        Q(batches__expiry_date__isnull=True) | Q(batches__expiry_date__gte=today)
    )


def _product_rows(division, divisions, start, end, status, search, params):
    today = timezone.localdate()
    usable = _usable_batch_filter(today)
    value_expr = ExpressionWrapper(
        F("batches__quantity_remaining") * F("batches__unit_cost"),
        output_field=DecimalField(max_digits=20, decimal_places=4),
    )
    qs = _scope(Product.objects.select_related("business_unit"), division, divisions)
    qs = qs.annotate(
        usable=Coalesce(
            Sum("batches__quantity_remaining", filter=usable),
            0,
        ),
        stock_value=Coalesce(
            Sum(value_expr, filter=usable),
            Decimal("0"),
            output_field=DecimalField(max_digits=20, decimal_places=4),
        ),
    )
    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(sku__icontains=search))
    if status == "low":
        qs = qs.filter(usable__lte=F("min_stock"))
    elif status == "active":
        qs = qs.filter(is_active=True)
    rows = []
    for product in qs.order_by("business_unit__name", "name"):
        usable_qty = int(product.usable or 0)
        rows.append({
            "sku": product.sku,
            "name": product.name,
            "category": product.category,
            "division": product.business_unit.name,
            "unit": product.unit,
            "usable_stock": usable_qty,
            "min_stock": product.min_stock,
            "low_stock": usable_qty <= product.min_stock,
            "stock_value": _to_decimal(product.stock_value),
        })
    return rows


def _batch_rows(division, divisions, start, end, status, search, params):
    qs = _scope(
        ProductBatch.objects.select_related("product", "business_unit"),
        division, divisions,
    )
    if status:
        qs = qs.filter(status=status)
    if search:
        qs = qs.filter(
            Q(product__name__icontains=search)
            | Q(product__sku__icontains=search)
            | Q(batch_number__icontains=search)
        )
    qs = _date_between(qs, "received_at", start, end)
    rows = []
    for batch in qs.order_by("business_unit__name", "product__name", "expiry_date"):
        rows.append({
            "batch_number": batch.batch_number,
            "product": batch.product.name,
            "sku": batch.product.sku,
            "division": batch.business_unit.name,
            "expiry_date": batch.expiry_date,
            "status": batch.status,
            "quantity_remaining": batch.quantity_remaining,
            "unit_cost": _to_decimal(batch.unit_cost),
            "stock_value": _to_decimal(batch.quantity_remaining) * _to_decimal(batch.unit_cost),
        })
    return rows


def _movement_rows(division, divisions, start, end, status, search, params):
    qs = _scope(
        StockMovement.objects.select_related(
            "business_unit", "product_batch__product", "performed_by"
        ),
        division, divisions,
    )
    if status:
        qs = qs.filter(movement_type=status)
    if search:
        qs = qs.filter(
            Q(reference__icontains=search)
            | Q(product_batch__product__name__icontains=search)
            | Q(product_batch__batch_number__icontains=search)
        )
    qs = _date_between(qs, "created_at", start, end)
    rows = []
    for movement in qs.order_by("-created_at", "-pk"):
        performer = movement.performed_by
        rows.append({
            "created_at": movement.created_at,
            "division": movement.business_unit.name,
            "reference": movement.reference,
            "movement_type": movement.movement_type,
            "product": movement.product_batch.product.name,
            "batch_number": movement.product_batch.batch_number,
            "quantity": movement.quantity,
            "quantity_before": movement.quantity_before,
            "quantity_after": movement.quantity_after,
            "performed_by": (
                (performer.get_full_name() or performer.email) if performer else ""
            ),
        })
    return rows


def _low_stock_rows(division, divisions, start, end, status, search, params):
    rows = _product_rows(division, divisions, None, None, "low", search, params)
    for row in rows:
        row["shortfall"] = max(0, row["min_stock"] - row["usable_stock"])
    return rows


def _expiry_rows(division, divisions, start, end, status, search, params):
    today = timezone.localdate()
    try:
        window = int(params.get("window") or 90)
    except (TypeError, ValueError):
        window = 90
    cutoff = end or (today + timedelta(days=window))
    qs = _scope(
        ProductBatch.objects.select_related("product", "business_unit"),
        division, divisions,
    ).filter(
        status=ProductBatch.STATUS_USABLE,
        quantity_remaining__gt=0,
        expiry_date__isnull=False,
        expiry_date__lte=cutoff,
    )
    if start is not None:
        qs = qs.filter(expiry_date__gte=start)
    if search:
        qs = qs.filter(
            Q(product__name__icontains=search) | Q(batch_number__icontains=search)
        )
    rows = []
    for batch in qs.order_by("expiry_date", "business_unit__name", "product__name"):
        rows.append({
            "product": batch.product.name,
            "batch_number": batch.batch_number,
            "division": batch.business_unit.name,
            "expiry_date": batch.expiry_date,
            "days_to_expiry": (batch.expiry_date - today).days,
            "quantity_remaining": batch.quantity_remaining,
            "stock_value": _to_decimal(batch.quantity_remaining) * _to_decimal(batch.unit_cost),
        })
    return rows


def _procurement_spend_rows(division, divisions, start, end, status, search, params):
    value_expr = ExpressionWrapper(
        F("quantity") * F("unit_cost"),
        output_field=DecimalField(max_digits=20, decimal_places=4),
    )
    qs = StockReceiptLine.objects.filter(
        receipt__status=StockReceipt.STATUS_POSTED,
    ).select_related("receipt__business_unit", "receipt__supplier")
    if division is not None:
        qs = qs.filter(receipt__business_unit=division)
    else:
        qs = qs.filter(receipt__business_unit__in=divisions)
    if start is not None:
        qs = qs.filter(receipt__received_at__date__gte=start)
    if end is not None:
        qs = qs.filter(receipt__received_at__date__lte=end)
    if search:
        qs = qs.filter(
            Q(receipt__supplier__name__icontains=search)
            | Q(product__name__icontains=search)
        )
    grouped = qs.values(
        "receipt__business_unit__name", "receipt__supplier__name"
    ).annotate(
        receipts=Count("receipt_id", distinct=True),
        quantity=Sum("quantity"),
        total_value=Sum(value_expr),
    ).order_by("receipt__business_unit__name", "receipt__supplier__name")
    return [
        {
            "division": row["receipt__business_unit__name"],
            "supplier": row["receipt__supplier__name"] or "Unspecified",
            "receipts": row["receipts"],
            "quantity": row["quantity"] or 0,
            "total_value": _to_decimal(row["total_value"]),
        }
        for row in grouped
    ]


def _supplier_rows(division, divisions, start, end, status, search, params):
    qs = _scope(Supplier.objects.select_related("business_unit"), division, divisions)
    if status == "active":
        qs = qs.filter(is_active=True)
    if search:
        qs = qs.filter(
            Q(name__icontains=search) | Q(code__icontains=search)
            | Q(contact_person__icontains=search)
        )
    return [
        {
            "code": s.code, "name": s.name, "division": s.business_unit.name,
            "contact_person": s.contact_person, "phone": s.phone, "email": s.email,
            "payment_terms_days": s.payment_terms_days,
        }
        for s in qs.order_by("business_unit__name", "name")
    ]


def _purchase_order_rows(division, divisions, start, end, status, search, params):
    value_expr = ExpressionWrapper(
        F("lines__quantity") * F("lines__unit_cost"),
        output_field=DecimalField(max_digits=20, decimal_places=4),
    )
    qs = _scope(
        PurchaseOrder.objects.select_related("business_unit", "supplier"),
        division, divisions,
    )
    if status:
        qs = qs.filter(status=status)
    if search:
        qs = qs.filter(
            Q(reference__icontains=search) | Q(supplier__name__icontains=search)
        )
    qs = _date_between(qs, "order_date", start, end)
    qs = qs.annotate(
        ordered=Coalesce(Sum("lines__quantity"), 0),
        received=Coalesce(Sum("lines__received_quantity"), 0),
        total_value=Coalesce(
            Sum(value_expr), Decimal("0"),
            output_field=DecimalField(max_digits=20, decimal_places=4),
        ),
    )
    return [
        {
            "reference": po.reference, "division": po.business_unit.name,
            "supplier": po.supplier.name, "status": po.status,
            "order_date": po.order_date, "expected_date": po.expected_date,
            "ordered": int(po.ordered or 0), "received": int(po.received or 0),
            "total_value": _to_decimal(po.total_value),
        }
        for po in qs.order_by("-created_at")
    ]


def _inventory_valuation_rows(division, divisions, start, end, status, search, params):
    today = timezone.localdate()
    usable = Q(batches__status=ProductBatch.STATUS_USABLE) & (
        Q(batches__expiry_date__isnull=True) | Q(batches__expiry_date__gte=today)
    )
    value_expr = ExpressionWrapper(
        F("batches__quantity_remaining") * F("batches__unit_cost"),
        output_field=DecimalField(max_digits=20, decimal_places=4),
    )
    qs = _scope(Product.objects.all(), division, divisions)
    if search:
        qs = qs.filter(category__icontains=search)
    grouped = qs.values("business_unit__name", "category").annotate(
        products=Count("id", distinct=True),
        quantity=Coalesce(Sum("batches__quantity_remaining", filter=usable), 0),
        stock_value=Coalesce(
            Sum(value_expr, filter=usable), Decimal("0"),
            output_field=DecimalField(max_digits=20, decimal_places=4),
        ),
    ).order_by("business_unit__name", "category")
    return [
        {
            "division": row["business_unit__name"],
            "category": row["category"] or "Uncategorised",
            "products": row["products"],
            "quantity": int(row["quantity"] or 0),
            "stock_value": _to_decimal(row["stock_value"]),
        }
        for row in grouped
    ]


def _payroll_summary_rows(division, divisions, start, end, status, search, params):
    qs = _scope(
        PayrollRun.objects.select_related("business_unit"), division, divisions
    )
    if status:
        qs = qs.filter(status=status)
    if start is not None:
        qs = qs.filter(period_end__gte=start)
    if end is not None:
        qs = qs.filter(period_start__lte=end)
    qs = qs.annotate(
        employees=Count("lines", distinct=True),
        gross=Coalesce(Sum("lines__gross"), Decimal("0"),
                       output_field=DecimalField(max_digits=20, decimal_places=2)),
        deductions=Coalesce(Sum("lines__deductions"), Decimal("0"),
                            output_field=DecimalField(max_digits=20, decimal_places=2)),
        net=Coalesce(Sum("lines__net"), Decimal("0"),
                     output_field=DecimalField(max_digits=20, decimal_places=2)),
    )
    return [
        {
            "reference": run.reference, "division": run.business_unit.name,
            "period_start": run.period_start, "period_end": run.period_end,
            "status": run.status, "employees": run.employees,
            "gross": _to_decimal(run.gross), "deductions": _to_decimal(run.deductions),
            "net": _to_decimal(run.net),
        }
        for run in qs.order_by("-period_end", "-created_at")
    ]


def _transport_cost_rows(division, divisions, start, end, status, search, params):
    qs = _scope(
        RideCostEstimate.objects.select_related(
            "business_unit", "transport_request"
        ),
        division, divisions,
    )
    if search:
        qs = qs.filter(
            Q(reference__icontains=search)
            | Q(transport_request__reference__icontains=search)
        )
    qs = _date_between(qs, "created_at", start, end)
    return [
        {
            "reference": est.reference, "division": est.business_unit.name,
            "request_reference": (
                est.transport_request.reference if est.transport_request else ""
            ),
            "distance_km": _to_decimal(est.distance_km),
            "duration_minutes": est.duration_minutes,
            "base_fee": _to_decimal(est.base_fee),
            "tolls": _to_decimal(est.tolls),
            "total_cost": _to_decimal(est.total_cost),
            "created_at": est.created_at,
        }
        for est in qs.order_by("-created_at")
    ]


def _hr_employee_rows(division, divisions, start, end, status, search, params):
    qs = _scope(
        Employee.objects.select_related("user", "business_unit", "department"),
        division, divisions,
    )
    if status == "active":
        qs = qs.filter(is_active=True)
    elif status == "inactive":
        qs = qs.filter(is_active=False)
    if search:
        qs = qs.filter(
            Q(employee_id__icontains=search)
            | Q(user__first_name__icontains=search)
            | Q(user__last_name__icontains=search)
            | Q(user__email__icontains=search)
            | Q(designation__icontains=search)
        )
    return [
        {
            "employee_id": e.employee_id,
            "name": e.user.get_full_name() or e.user.email,
            "division": e.business_unit.name,
            "department": e.department.name if e.department else "",
            "designation": e.designation,
            "hire_date": e.hire_date,
            "is_active": e.is_active,
        }
        for e in qs.order_by("employee_id")
    ]


def _hr_attendance_rows(division, divisions, start, end, status, search, params):
    qs = _scope(
        AttendanceEvent.objects.select_related(
            "employee__user", "employee__business_unit"
        ),
        division, divisions,
    )
    qs = _date_between(qs, "timestamp", start, end)
    if search:
        qs = qs.filter(
            Q(employee__employee_id__icontains=search)
            | Q(employee__user__first_name__icontains=search)
            | Q(employee__user__last_name__icontains=search)
        )
    grouped = qs.values(
        "employee__employee_id", "employee__user__first_name",
        "employee__user__last_name", "employee__user__email",
        "employee__business_unit__name",
    ).annotate(
        check_ins=Count("id", filter=Q(action=AttendanceEvent.ACTION_CHECK_IN)),
        check_outs=Count("id", filter=Q(action=AttendanceEvent.ACTION_CHECK_OUT)),
        days_present=Count("timestamp__date", distinct=True),
    ).order_by("employee__employee_id")
    return [
        {
            "employee_id": row["employee__employee_id"],
            "name": (
                f"{row['employee__user__first_name']} {row['employee__user__last_name']}".strip()
                or row["employee__user__email"]
            ),
            "division": row["employee__business_unit__name"],
            "check_ins": row["check_ins"],
            "check_outs": row["check_outs"],
            "days_present": row["days_present"],
        }
        for row in grouped
    ]


def _hr_leave_rows(division, divisions, start, end, status, search, params):
    qs = LeaveRequest.objects.select_related(
        "employee__user", "employee__business_unit"
    )
    if division is not None:
        qs = qs.filter(employee__business_unit=division)
    else:
        qs = qs.filter(employee__business_unit__in=divisions)
    if start is not None:
        qs = qs.filter(end_date__gte=start)
    if end is not None:
        qs = qs.filter(start_date__lte=end)
    if status:
        qs = qs.filter(status=status)
    if search:
        qs = qs.filter(
            Q(employee__employee_id__icontains=search)
            | Q(employee__user__first_name__icontains=search)
            | Q(employee__user__last_name__icontains=search)
        )
    return [
        {
            "employee_id": leave.employee.employee_id,
            "name": leave.employee.user.get_full_name() or leave.employee.user.email,
            "division": leave.employee.business_unit.name,
            "start_date": leave.start_date,
            "end_date": leave.end_date,
            "status": leave.status,
            "reason": leave.reason,
        }
        for leave in qs.order_by("-start_date")
    ]


def _payroll_register_rows(division, divisions, start, end, status, search, params):
    qs = PayrollLine.objects.select_related(
        "run__business_unit", "employee__user"
    )
    if division is not None:
        qs = qs.filter(run__business_unit=division)
    else:
        qs = qs.filter(run__business_unit__in=divisions)
    if start is not None:
        qs = qs.filter(run__period_end__gte=start)
    if end is not None:
        qs = qs.filter(run__period_start__lte=end)
    if status:
        qs = qs.filter(run__status=status)
    if search:
        qs = qs.filter(
            Q(employee__employee_id__icontains=search)
            | Q(employee__user__first_name__icontains=search)
            | Q(employee__user__last_name__icontains=search)
            | Q(run__reference__icontains=search)
        )
    return [
        {
            "reference": line.run.reference,
            "division": line.run.business_unit.name,
            "employee_id": line.employee.employee_id,
            "name": line.employee.user.get_full_name() or line.employee.user.email,
            "basic_salary": _to_decimal(line.basic_salary),
            "allowances": _to_decimal(line.allowances),
            "deductions": _to_decimal(line.deductions),
            "gross": _to_decimal(line.gross),
            "net": _to_decimal(line.net),
            "days_present": line.days_present,
        }
        for line in qs.order_by("run__period_end", "employee__employee_id")
    ]


def _salary_structure_rows(division, divisions, start, end, status, search, params):
    qs = _scope(
        SalaryStructure.objects.select_related(
            "employee__user", "business_unit"
        ),
        division, divisions,
    )
    if status == "active":
        qs = qs.filter(is_active=True)
    if search:
        qs = qs.filter(
            Q(employee__employee_id__icontains=search)
            | Q(employee__user__first_name__icontains=search)
            | Q(employee__user__last_name__icontains=search)
        )
    return [
        {
            "employee_id": s.employee.employee_id,
            "name": s.employee.user.get_full_name() or s.employee.user.email,
            "division": s.business_unit.name,
            "basic_salary": _to_decimal(s.basic_salary),
            "housing_allowance": _to_decimal(s.housing_allowance),
            "transport_allowance": _to_decimal(s.transport_allowance),
            "other_allowance": _to_decimal(s.other_allowance),
            "tax_rate_percent": _to_decimal(s.tax_rate_percent),
            "other_deduction": _to_decimal(s.other_deduction),
            "gross": _to_decimal(s.gross),
        }
        for s in qs.order_by("employee__employee_id")
    ]


def _transport_request_rows(division, divisions, start, end, status, search, params):
    qs = _scope(
        TransportRequest.objects.select_related(
            "business_unit", "assigned_driver__user", "assigned_vehicle"
        ),
        division, divisions,
    )
    if status:
        qs = qs.filter(status=status)
    if search:
        qs = qs.filter(
            Q(reference__icontains=search)
            | Q(patient_name__icontains=search)
            | Q(pickup_location__icontains=search)
            | Q(dropoff_location__icontains=search)
        )
    qs = _date_between(qs, "pickup_time", start, end)
    return [
        {
            "reference": req.reference, "division": req.business_unit.name,
            "patient_name": req.patient_name,
            "pickup_location": req.pickup_location,
            "dropoff_location": req.dropoff_location,
            "pickup_time": req.pickup_time, "status": req.status,
            "driver": (
                (req.assigned_driver.user.get_full_name()
                 or req.assigned_driver.user.email)
                if req.assigned_driver else ""
            ),
            "vehicle": (
                req.assigned_vehicle.license_plate if req.assigned_vehicle else ""
            ),
        }
        for req in qs.order_by("-pickup_time")
    ]


def _transport_trip_rows(division, divisions, start, end, status, search, params):
    qs = Trip.objects.select_related(
        "request__business_unit", "driver__user", "vehicle"
    )
    if division is not None:
        qs = qs.filter(request__business_unit=division)
    else:
        qs = qs.filter(request__business_unit__in=divisions)
    if status:
        qs = qs.filter(status=status)
    if search:
        qs = qs.filter(
            Q(request__reference__icontains=search)
            | Q(request__patient_name__icontains=search)
            | Q(vehicle__license_plate__icontains=search)
        )
    qs = _date_between(qs, "created_at", start, end)
    return [
        {
            "request_reference": trip.request.reference,
            "division": trip.request.business_unit.name,
            "driver": trip.driver.user.get_full_name() or trip.driver.user.email,
            "vehicle": trip.vehicle.license_plate,
            "status": trip.status,
            "start_time": trip.start_time,
            "end_time": trip.end_time,
        }
        for trip in qs.order_by("-created_at")
    ]


def _transport_cost_estimate_rows(division, divisions, start, end, status, search, params):
    qs = _scope(
        RideCostEstimate.objects.select_related("business_unit"),
        division, divisions,
    )
    if search:
        qs = qs.filter(reference__icontains=search)
    qs = _date_between(qs, "created_at", start, end)
    return [
        {
            "reference": est.reference, "division": est.business_unit.name,
            "distance_km": _to_decimal(est.distance_km),
            "duration_minutes": est.duration_minutes,
            "per_km_rate": _to_decimal(est.per_km_rate),
            "driver_hourly_rate": _to_decimal(est.driver_hourly_rate),
            "tolls": _to_decimal(est.tolls),
            "total_cost": _to_decimal(est.total_cost),
        }
        for est in qs.order_by("-created_at")
    ]


def _management_overview_rows(division, divisions, start, end, status, search, params):
    today = timezone.localdate()
    usable = Q(batches__status=ProductBatch.STATUS_USABLE) & (
        Q(batches__expiry_date__isnull=True) | Q(batches__expiry_date__gte=today)
    )
    value_expr = ExpressionWrapper(
        F("batches__quantity_remaining") * F("batches__unit_cost"),
        output_field=DecimalField(max_digits=20, decimal_places=4),
    )
    units = divisions.filter(pk=division.pk) if division is not None else divisions
    rows = []
    for unit in units.order_by("name"):
        products = Product.objects.filter(business_unit=unit)
        product_stats = products.aggregate(
            products=Count("id", distinct=True),
            usable_stock=Coalesce(Sum("batches__quantity_remaining", filter=usable), 0),
            stock_value=Coalesce(
                Sum(value_expr, filter=usable), Decimal("0"),
                output_field=DecimalField(max_digits=20, decimal_places=4),
            ),
        )
        low_stock = sum(1 for p in products.annotate(
            usable=Coalesce(Sum("batches__quantity_remaining", filter=usable), 0)
        ) if int(p.usable or 0) <= p.min_stock)
        payroll_qs = PayrollLine.objects.filter(run__business_unit=unit)
        if start is not None:
            payroll_qs = payroll_qs.filter(run__period_end__gte=start)
        if end is not None:
            payroll_qs = payroll_qs.filter(run__period_start__lte=end)
        rows.append({
            "division": unit.name,
            "employees": Employee.objects.filter(
                business_unit=unit, is_active=True
            ).count(),
            "products": product_stats["products"] or 0,
            "usable_stock": int(product_stats["usable_stock"] or 0),
            "stock_value": _to_decimal(product_stats["stock_value"]),
            "low_stock": low_stock,
            "vehicles": Vehicle.objects.filter(business_unit=unit).count(),
            "pending_transport": TransportRequest.objects.filter(
                business_unit=unit, status=TransportRequest.STATUS_PENDING
            ).count(),
            "open_purchase_orders": PurchaseOrder.objects.filter(
                business_unit=unit,
                status__in=[
                    PurchaseOrder.STATUS_DRAFT,
                    PurchaseOrder.STATUS_SUBMITTED,
                    PurchaseOrder.STATUS_APPROVED,
                    PurchaseOrder.STATUS_PARTIAL,
                ],
            ).count(),
            "payroll_net": _to_decimal(payroll_qs.aggregate(
                total=Coalesce(Sum("net"), Decimal("0"),
                               output_field=DecimalField(max_digits=20, decimal_places=2))
            )["total"]),
        })
    return rows


BUILDERS = {
    "stock_summary": _product_rows,
    "batches": _batch_rows,
    "movements": _movement_rows,
    "low_stock": _low_stock_rows,
    "expiry": _expiry_rows,
    "procurement_spend": _procurement_spend_rows,
    "suppliers": _supplier_rows,
    "purchase_orders": _purchase_order_rows,
    "inventory_valuation": _inventory_valuation_rows,
    "payroll_summary": _payroll_summary_rows,
    "transport_cost": _transport_cost_rows,
    "hr_employees": _hr_employee_rows,
    "hr_attendance": _hr_attendance_rows,
    "hr_leave": _hr_leave_rows,
    "payroll_register": _payroll_register_rows,
    "salary_structures": _salary_structure_rows,
    "transport_requests": _transport_request_rows,
    "transport_trips": _transport_trip_rows,
    "transport_cost_estimates": _transport_cost_estimate_rows,
    "management_overview": _management_overview_rows,
}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _totals_for(spec, rows):
    totals = {}
    for key in spec.totals:
        total = Decimal("0")
        found = False
        for row in rows:
            value = row.get(key)
            if isinstance(value, bool):
                total += Decimal(1) if value else Decimal(0)
                found = True
            elif isinstance(value, (int, float, Decimal)):
                total += _to_decimal(value)
                found = True
        if found:
            if total == total.to_integral_value():
                totals[key] = int(total)
            else:
                totals[key] = total
    return totals


def run_report(user, key, params, page=1, page_size=50, paginate=True):
    spec = REPORTS.get(key)
    if spec is None:
        raise ReportNotFound("Unknown report.")
    if not role_can(user, spec.module, "read"):
        raise ReportPermissionDenied(
            f"You do not have read permission for {spec.module} reports."
        )

    division, divisions = resolve_division(user, params)
    start = _parse_date(params.get("start"), "start")
    end = _parse_date(params.get("end"), "end")
    if spec.default_days and start is None and end is None:
        end = timezone.localdate()
        start = end - timedelta(days=spec.default_days)

    status = (params.get("status") or "").strip()
    search = (params.get("search") or "").strip()
    builder = BUILDERS[spec.builder]
    rows = builder(division, divisions, start, end, status, search, params)

    totals = _totals_for(spec, rows)
    count = len(rows)
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 50), 500))
    if paginate:
        offset = (page - 1) * page_size
        page_rows = rows[offset:offset + page_size]
    else:
        page_rows = rows
        page_size = max(count, 1)
    pages = max(1, (count + page_size - 1) // page_size)

    return {
        "key": spec.key,
        "title": spec.title,
        "module": spec.module,
        "description": spec.description,
        "columns": list(spec.columns),
        "rows": [{k: _json_safe(v) for k, v in row.items()} for row in page_rows],
        "totals": {k: _json_safe(v) for k, v in totals.items()},
        "count": count,
        "page": page if paginate else 1,
        "page_size": page_size,
        "pages": pages if paginate else 1,
        "generated_at": _json_safe(timezone.now()),
        "division": (
            {"id": division.id, "name": division.name, "code": division.code}
            if division is not None else None
        ),
        "divisions": [
            {"id": unit.id, "name": unit.name, "code": unit.code}
            for unit in divisions.order_by("name")
        ],
        "aggregate": division is None,
        "filters": {
            "business_unit": division.code if division is not None else "all",
            "start": start.isoformat() if start else "",
            "end": end.isoformat() if end else "",
            "status": status,
            "search": search,
        },
    }
