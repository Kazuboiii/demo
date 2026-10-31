from datetime import timedelta

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from attendance.models import AttendanceEvent
from attendance.serializers import AttendanceEventSerializer
from core.models import BusinessUnit, Employee
from core.permissions import (
    BusinessUnitScoped,
    IsAuthenticatedActive,
    accessible_divisions,
    requested_division,
    role_can,
)
from fleet.models import Vehicle
from inventory.models import (
    LowStockAlert,
    Product,
    ProductBatch,
    PurchaseOrder,
    StockAdjustment,
    StockReceipt,
)
from medicine_delivery.models import DeliveryRequest
from nemt.models import TransportRequest, Trip as NEMTTrip

from . import engine
from .exporters import export_report


def _scope_for(request):
    """Return (unit, divisions, error_response)."""
    unit, error = requested_division(request.user, request)
    if error is not None:
        return None, None, error
    return unit, accessible_divisions(request.user), None


def _filter_scope(qs, unit, divisions, field="business_unit"):
    if unit is not None:
        return qs.filter(**{field: unit})
    return qs.filter(**{f"{field}__in": divisions})


class DashboardView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get(self, request):
        unit, divisions, error = _scope_for(request)
        if error is not None:
            return error

        def scoped(model):
            return _filter_scope(model.objects.all(), unit, divisions)

        today = timezone.localdate()
        events = scoped(AttendanceEvent)
        days = [today - timedelta(days=i) for i in range(6, -1, -1)]
        weekly = []
        for day in days:
            daily = events.filter(timestamp__date=day)
            weekly.append({
                "day": day.isoformat(),
                "checkins": daily.filter(action="check_in").count(),
                "checkouts": daily.filter(action="check_out").count(),
            })

        products = scoped(Product)
        batches = scoped(ProductBatch)
        usable_filter = Q(status=ProductBatch.STATUS_USABLE) & (
            Q(expiry_date__isnull=True) | Q(expiry_date__gte=today)
        )
        value_expr = ExpressionWrapper(
            F("quantity_remaining") * F("unit_cost"),
            output_field=DecimalField(max_digits=20, decimal_places=4),
        )
        stock = batches.filter(usable_filter).aggregate(
            units=Coalesce(Sum("quantity_remaining"), 0),
            value=Coalesce(
                Sum(value_expr), 0,
                output_field=DecimalField(max_digits=20, decimal_places=4),
            ),
        )
        annotated_products = products.annotate(
            usable=Coalesce(
                Sum(
                    "batches__quantity_remaining",
                    filter=Q(batches__status=ProductBatch.STATUS_USABLE)
                    & (Q(batches__expiry_date__isnull=True) | Q(batches__expiry_date__gte=today)),
                ),
                0,
            )
        )
        low_stock = sum(
            1 for product in annotated_products
            if int(product.usable or 0) <= product.min_stock
        )
        near_expiry = batches.filter(
            status=ProductBatch.STATUS_USABLE,
            quantity_remaining__gt=0,
            expiry_date__gte=today,
            expiry_date__lte=today + timedelta(days=30),
        ).count()
        expired = batches.filter(
            status=ProductBatch.STATUS_USABLE,
            quantity_remaining__gt=0,
            expiry_date__lt=today,
        ).count()
        since = timezone.now() - timedelta(days=30)

        inventory = {
            "products": products.filter(is_active=True).count(),
            "batches": batches.count(),
            "usable_units": int(stock["units"] or 0),
            "stock_value": float(stock["value"] or 0),
            "low_stock": low_stock,
            "near_expiry": near_expiry,
            "expired_batches": expired,
            "new_products_30d": products.filter(created_at__gte=since).count(),
            "restocks_30d": _filter_scope(
                StockReceipt.objects.all(), unit, divisions
            ).filter(received_at__gte=since).count(),
            "open_alerts": _filter_scope(
                LowStockAlert.objects.filter(resolved=False),
                unit, divisions, field="product__business_unit",
            ).count(),
            "pending_adjustments": _filter_scope(
                StockAdjustment.objects.filter(status=StockAdjustment.STATUS_DRAFT),
                unit, divisions,
            ).count(),
            "open_purchase_orders": _filter_scope(
                PurchaseOrder.objects.filter(
                    status__in=[
                        PurchaseOrder.STATUS_DRAFT,
                        PurchaseOrder.STATUS_SUBMITTED,
                        PurchaseOrder.STATUS_APPROVED,
                        PurchaseOrder.STATUS_PARTIAL,
                    ]
                ),
                unit, divisions,
            ).count(),
        }

        return Response({
            "employees": scoped(Employee).filter(is_active=True).count(),
            "checked_in_today": events.filter(
                action="check_in", timestamp__date=today
            ).values("employee_id").distinct().count(),
            "active_vehicles": scoped(Vehicle).filter(
                status__in=["available", "in_use"]
            ).count(),
            "pending_requests": scoped(TransportRequest).filter(status="pending").count()
            + scoped(DeliveryRequest).filter(status="requested").count(),
            "weekly": weekly,
            "recent": AttendanceEventSerializer(
                events.select_related("employee__user", "business_unit", "shift")
                .order_by("-timestamp", "-pk")[:8],
                many=True,
            ).data,
            "inventory": inventory,
            "division": (
                {"id": unit.id, "name": unit.name, "code": unit.code}
                if unit is not None else None
            ),
            "divisions": [
                {"id": d.id, "name": d.name, "code": d.code}
                for d in divisions.order_by("name")
            ],
            "updated_at": timezone.now(),
        })


class AttendanceReportView(APIView):
    permission_classes = [BusinessUnitScoped]

    def get(self, request):
        unit, divisions, error = _scope_for(request)
        if error is not None:
            return error
        qs = _filter_scope(AttendanceEvent.objects.all(), unit, divisions)
        today = timezone.localdate()
        data = {
            "total_events": qs.count(),
            "check_ins_today": qs.filter(
                action="check_in", timestamp__date=today
            ).count(),
            "by_unit": list(
                qs.values("business_unit__name").annotate(n=Count("id")).order_by("-n")
            ),
            "recent": list(
                qs.order_by("-timestamp")[:10].values(
                    "employee__employee_id", "action", "timestamp",
                    "business_unit__name",
                )
            ),
        }
        return Response(data)


class InventoryReportView(APIView):
    permission_classes = [BusinessUnitScoped]

    def get(self, request):
        unit, divisions, error = _scope_for(request)
        if error is not None:
            return error
        qs = _filter_scope(Product.objects.all(), unit, divisions)
        today = timezone.localdate()
        low = [p.sku for p in qs if p.low_stock()]
        batches = _filter_scope(
            ProductBatch.objects.filter(status=ProductBatch.STATUS_USABLE),
            unit, divisions,
        )
        expired = batches.filter(expiry_date__lt=today).count()
        near = batches.filter(
            expiry_date__lte=today + timedelta(days=30),
            expiry_date__gte=today,
        ).count()
        return Response({
            "low_stock": low, "expired_batches": expired, "near_expiry": near,
        })


class FleetReportView(APIView):
    permission_classes = [BusinessUnitScoped]

    def get(self, request):
        unit, divisions, error = _scope_for(request)
        if error is not None:
            return error
        qs = _filter_scope(Vehicle.objects.all(), unit, divisions)
        return Response({
            "vehicles": qs.count(),
            "available": qs.filter(status="available").count(),
            "in_use": qs.filter(status="in_use").count(),
            "maintenance": qs.filter(status="maintenance").count(),
            "trips": NEMTTrip.objects.filter(
                request__business_unit__in=qs.values_list("business_unit", flat=True)
            ).count(),
        })


class ReportCatalogView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get(self, request):
        user = request.user
        return Response({
            "reports": [
                spec for spec in engine.catalog()
                if role_can(user, spec["module"], "read")
            ],
            "permissions": {
                "can_export": {
                    module: role_can(user, module, "export")
                    for module in ["inventory", "procurement", "finance", "hr",
                                   "payroll", "transport", "reports"]
                },
            },
        })


def _report_response(request, key):
    params = request.query_params
    try:
        page = int(params.get("page", 1))
        page_size = int(params.get("page_size", 50))
    except (TypeError, ValueError):
        return Response({"detail": "page and page_size must be integers."}, status=400)
    try:
        return engine.run_report(
            request.user, key, params, page=page, page_size=page_size, paginate=True
        )
    except engine.ReportPermissionDenied as exc:
        return Response({"detail": str(exc)}, status=403)
    except engine.ReportNotFound as exc:
        return Response({"detail": str(exc)}, status=404)
    except engine.ReportError as exc:
        return Response({"detail": str(exc)}, status=400)


class ReportRunView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get(self, request, key):
        data = _report_response(request, key)
        if isinstance(data, Response):
            return data
        return Response(data)


class ReportExportView(APIView):
    permission_classes = [IsAuthenticatedActive]

    def get(self, request, key):
        spec = engine.REPORTS.get(key)
        if spec is None:
            return Response({"detail": "Unknown report."}, status=404)
        if not role_can(request.user, spec.module, "export"):
            return Response(
                {"detail": f"You do not have export permission for {spec.module} reports."},
                status=403,
            )
        fmt = (request.query_params.get("format") or "csv").lower()
        if fmt not in ("csv", "xlsx", "pdf"):
            return Response(
                {"detail": "format must be csv, xlsx or pdf."}, status=400
            )
        try:
            report = engine.run_report(
                request.user, key, request.query_params, paginate=False
            )
        except engine.ReportPermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        except engine.ReportNotFound as exc:
            return Response({"detail": str(exc)}, status=404)
        except engine.ReportError as exc:
            return Response({"detail": str(exc)}, status=400)
        try:
            payload, content_type, filename = export_report(report, fmt)
        except ImportError as exc:
            return Response(
                {"detail": f"Export dependency missing: {exc}. Install backend requirements."},
                status=500,
            )
        response = HttpResponse(payload, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["X-Report-Rows"] = str(report["count"])
        return response
