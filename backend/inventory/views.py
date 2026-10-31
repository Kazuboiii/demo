"""Inventory API views.

All list endpoints are division-scoped on the server. A request for a division
the user cannot access returns 403; filtering is never left to the frontend.
"""

from datetime import timedelta

import qrcode
from django.db.models import Q, Sum
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from core.models import BusinessUnit
from core.permissions import (
    ModulePermission,
    accessible_divisions,
    effective_permissions,
    requested_division,
    role_can,
    scoped_queryset,
)

from . import services
from .models import (
    Location,
    LowStockAlert,
    Product,
    ProductBatch,
    PurchaseOrder,
    StockAdjustment,
    StockCount,
    StockIssue,
    StockMovement,
    StockReceipt,
    StockTransfer,
    Supplier,
)
from .serializers import (
    LocationSerializer,
    LowStockAlertSerializer,
    ProductBatchSerializer,
    ProductSerializer,
    PurchaseOrderSerializer,
    StockAdjustmentSerializer,
    StockCountSerializer,
    StockIssueSerializer,
    StockMovementSerializer,
    StockReceiptSerializer,
    StockTransferSerializer,
    SupplierSerializer,
)


def _scoped(qs, request, field="business_unit"):
    """Apply the division selector and enforce access."""
    user = request.user
    unit, error = requested_division(user, request)
    if error is not None:
        raise PermissionDenied(error.data.get("detail", "Not authorized."))
    if unit is not None:
        return qs.filter(**{field: unit})
    return scoped_queryset(qs, user, field)


def _require_action(request, action_name):
    if not role_can(request.user, "inventory", action_name):
        raise PermissionDenied(f"You do not have '{action_name}' permission for inventory.")


class WorkspaceViewSet(viewsets.ViewSet):
    """Role-aware workspace metadata for the inventory selector."""

    permission_classes = [ModulePermission]
    module = "inventory"

    def list(self, request):
        user = request.user
        units = accessible_divisions(user).order_by("name")
        divisions = []
        for unit in units:
            divisions.append({
                "id": unit.id,
                "name": unit.name,
                "code": unit.code,
                "is_primary": unit.pk == user.business_unit_id,
                "can_read": role_can(user, "inventory", "read"),
                "can_write": role_can(user, "inventory", "create"),
                "can_approve": role_can(user, "inventory", "approve"),
                "can_export": role_can(user, "inventory", "export"),
            })
        default = None
        if divisions:
            default = next(
                (d["id"] for d in divisions if d["is_primary"]), divisions[0]["id"]
            )
        return Response({
            "role": user.role_code,
            "role_name": user.role.name if user.role else None,
            "is_global_scope": user.is_global_scope,
            "organization_overview": user.is_global_scope,
            "default_division": default,
            "divisions": divisions,
            "permissions": effective_permissions(user),
        })


class LocationViewSet(viewsets.ModelViewSet):
    queryset = Location.objects.all().order_by("business_unit__name", "name")
    serializer_class = LocationSerializer
    permission_classes = [ModulePermission]
    module = "inventory"

    def get_queryset(self):
        return _scoped(super().get_queryset(), self.request)


class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.all().order_by("business_unit__name", "name")
    serializer_class = SupplierSerializer
    permission_classes = [ModulePermission]
    module = "inventory"

    def get_queryset(self):
        qs = _scoped(super().get_queryset(), self.request)
        search = self.request.query_params.get("search", "").strip()
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(code__icontains=search))
        return qs


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all().order_by("business_unit__name", "name")
    serializer_class = ProductSerializer
    permission_classes = [ModulePermission]
    module = "inventory"

    def get_queryset(self):
        qs = _scoped(
            super().get_queryset().select_related("business_unit"), self.request
        )
        today = timezone.localdate()
        return qs.annotate(
            annotated_usable_stock=Sum(
                "batches__quantity_remaining",
                filter=Q(batches__status=ProductBatch.STATUS_USABLE)
                & (Q(batches__expiry_date__isnull=True) | Q(batches__expiry_date__gte=today)),
            )
        )

    @action(detail=False, methods=["get"])
    def low_stock(self, request):
        data = [p for p in self.get_queryset() if p.low_stock()]
        return Response(ProductSerializer(data, many=True, context={"request": request}).data)

    @action(detail=False, methods=["get"])
    def near_expiry(self, request):
        days = int(request.query_params.get("days", 30))
        cutoff = timezone.localdate() + timedelta(days=days)
        batches = _scoped(ProductBatch.objects.all(), request).filter(
            status=ProductBatch.STATUS_USABLE,
            quantity_remaining__gt=0,
            expiry_date__lte=cutoff,
            expiry_date__gte=timezone.localdate(),
        ).select_related("product", "business_unit", "supplier", "location")
        return Response(ProductBatchSerializer(batches, many=True, context={"request": request}).data)

    @action(detail=False, methods=["get"])
    def expired(self, request):
        batches = _scoped(ProductBatch.objects.all(), request).filter(
            status=ProductBatch.STATUS_USABLE,
            quantity_remaining__gt=0,
            expiry_date__lt=timezone.localdate(),
        ).select_related("product", "business_unit", "supplier", "location")
        return Response(ProductBatchSerializer(batches, many=True, context={"request": request}).data)

    @action(detail=False, methods=["get"])
    def lookup(self, request):
        """Look up a product by manufacturer barcode / GTIN within the division."""
        barcode = request.query_params.get("barcode", "").strip()
        if not barcode:
            return Response({"detail": "barcode is required."}, status=400)
        product = self.get_queryset().filter(barcode=barcode).first()
        if not product:
            return Response(
                {"detail": "Product not found for this barcode.", "barcode": barcode},
                status=404,
            )
        return Response(ProductSerializer(product, context={"request": request}).data)

    @action(detail=False, methods=["get"])
    def alerts(self, request):
        qs = LowStockAlert.objects.filter(resolved=False).select_related(
            "product", "product__business_unit"
        )
        unit, error = requested_division(request.user, request)
        if error is not None:
            raise PermissionDenied(error.data.get("detail", "Not authorized."))
        if unit is not None:
            qs = qs.filter(product__business_unit=unit)
        else:
            qs = qs.filter(product__business_unit__in=accessible_divisions(request.user))
        data = LowStockAlertSerializer(
            [a for a in qs if not a.is_resolved()],
            many=True, context={"request": request},
        ).data
        return Response(data)


class ProductBatchViewSet(viewsets.ReadOnlyModelViewSet):
    """Batches are read-only through the API.

    Quantities change only by posting a receipt, issue, adjustment, transfer or
    sale through the central service.
    """

    queryset = ProductBatch.objects.all().order_by("product__name", "expiry_date")
    serializer_class = ProductBatchSerializer
    permission_classes = [ModulePermission]
    module = "inventory"

    def get_queryset(self):
        qs = _scoped(
            super().get_queryset().select_related(
                "product", "business_unit", "supplier", "location"
            ),
            self.request,
        )
        product = self.request.query_params.get("product")
        if product:
            qs = qs.filter(product_id=product)
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    @action(detail=True, methods=["get"])
    def label(self, request, pk=None):
        batch = self.get_object()
        latest = batch.movements.order_by("-created_at").first()
        return Response({
            "lot_id": batch.id,
            "product_name": batch.product.name,
            "sku": batch.product.sku,
            "barcode": batch.product.barcode,
            "batch_number": batch.batch_number,
            "lot_number": batch.lot_number,
            "expiry_date": batch.expiry_date,
            "status": batch.status,
            "usable_quantity": batch.usable_quantity(),
            "unit": batch.product.unit,
            "business_unit": batch.business_unit.id,
            "business_unit_name": batch.business_unit.name,
            "location": latest.location.name if latest and latest.location else None,
            "location_id": latest.location.id if latest and latest.location else None,
        })

    @action(detail=True, methods=["get"])
    def qr_label(self, request, pk=None):
        batch = self.get_object()
        img = qrcode.make(str(batch.id))
        from io import BytesIO

        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return HttpResponse(buf.read(), content_type="image/png")


class _DocumentViewSet(viewsets.ModelViewSet):
    """Shared behaviour for immutable posted stock documents."""

    permission_classes = [ModulePermission]
    module = "inventory"

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        created = getattr(serializer, "was_created", True)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
            headers=headers,
        )

    def update(self, request, *args, **kwargs):
        return Response(
            {"detail": "Posted stock documents are immutable. Reverse with an adjustment."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def destroy(self, request, *args, **kwargs):
        return Response(
            {"detail": "Posted stock documents cannot be deleted."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )


class StockReceiptViewSet(_DocumentViewSet):
    queryset = StockReceipt.objects.all().order_by("-received_at")
    serializer_class = StockReceiptSerializer

    def get_queryset(self):
        qs = _scoped(
            super().get_queryset().select_related(
                "business_unit", "location", "supplier", "received_by"
            ).prefetch_related("lines__product"),
            self.request,
        )
        supplier = self.request.query_params.get("supplier")
        if supplier:
            qs = qs.filter(supplier_id=supplier)
        start = self.request.query_params.get("start")
        end = self.request.query_params.get("end")
        if start:
            qs = qs.filter(received_at__date__gte=start)
        if end:
            qs = qs.filter(received_at__date__lte=end)
        return qs

    def perform_create(self, serializer):
        serializer.save(received_by=self.request.user)


class GoodsReceiptViewSet(StockReceiptViewSet):
    """Procurement-facing alias for goods received notes."""


class StockIssueViewSet(_DocumentViewSet):
    queryset = StockIssue.objects.all().order_by("-issued_at")
    serializer_class = StockIssueSerializer

    def get_queryset(self):
        qs = _scoped(
            super().get_queryset().select_related(
                "business_unit", "department", "issued_by", "location"
            ).prefetch_related("lines__product_batch__product"),
            self.request,
        )
        start = self.request.query_params.get("start")
        end = self.request.query_params.get("end")
        if start:
            qs = qs.filter(issued_at__date__gte=start)
        if end:
            qs = qs.filter(issued_at__date__lte=end)
        return qs

    def perform_create(self, serializer):
        serializer.save(issued_by=self.request.user)


class StockTransferViewSet(_DocumentViewSet):
    queryset = StockTransfer.objects.all().order_by("-transferred_at")
    serializer_class = StockTransferSerializer

    def get_queryset(self):
        return _scoped(
            super().get_queryset().select_related(
                "business_unit", "from_location", "to_location", "transferred_by"
            ).prefetch_related("lines__product_batch__product"),
            self.request,
        )

    def perform_create(self, serializer):
        serializer.save(transferred_by=self.request.user)


class StockMovementViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StockMovement.objects.all().order_by("-created_at")
    serializer_class = StockMovementSerializer
    permission_classes = [ModulePermission]
    module = "inventory"

    def get_queryset(self):
        qs = _scoped(
            super().get_queryset().select_related(
                "business_unit", "product_batch__product", "location", "performed_by"
            ),
            self.request,
        )
        params = self.request.query_params
        if params.get("product"):
            qs = qs.filter(product_batch__product_id=params["product"])
        if params.get("batch"):
            qs = qs.filter(product_batch_id=params["batch"])
        if params.get("movement_type"):
            qs = qs.filter(movement_type=params["movement_type"])
        if params.get("reference"):
            qs = qs.filter(reference__icontains=params["reference"])
        if params.get("start"):
            qs = qs.filter(created_at__date__gte=params["start"])
        if params.get("end"):
            qs = qs.filter(created_at__date__lte=params["end"])
        return qs


class StockAdjustmentViewSet(viewsets.ModelViewSet):
    queryset = StockAdjustment.objects.all().order_by("-created_at")
    serializer_class = StockAdjustmentSerializer
    permission_classes = [ModulePermission]
    module = "inventory"

    def get_queryset(self):
        return _scoped(
            super().get_queryset().select_related(
                "business_unit", "requested_by", "approved_by"
            ).prefetch_related("lines__product_batch__product"),
            self.request,
        )

    def perform_create(self, serializer):
        serializer.save(requested_by=self.request.user)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        _require_action(request, "approve")
        adjustment = self.get_object()
        try:
            services.approve_adjustment(adjustment, approved_by=request.user)
        except services.StockError as exc:
            return Response({"detail": str(exc)}, status=400)
        adjustment.refresh_from_db()
        return Response(
            self.get_serializer(adjustment, context={"request": request}).data
        )


class StockCountViewSet(viewsets.ModelViewSet):
    queryset = StockCount.objects.all().order_by("-created_at")
    serializer_class = StockCountSerializer
    permission_classes = [ModulePermission]
    module = "inventory"

    def get_queryset(self):
        return _scoped(
            super().get_queryset().select_related("business_unit", "location")
            .prefetch_related("lines__product_batch__product"),
            self.request,
        )

    def perform_create(self, serializer):
        serializer.save(counted_by=self.request.user)

    @action(detail=True, methods=["post"])
    def post_count(self, request, pk=None):
        _require_action(request, "approve")
        count = self.get_object()
        try:
            services.post_stock_count(count, counted_by=request.user)
        except services.StockError as exc:
            return Response({"detail": str(exc)}, status=400)
        count.refresh_from_db()
        return Response(self.get_serializer(count, context={"request": request}).data)


class PurchaseOrderViewSet(viewsets.ModelViewSet):
    queryset = PurchaseOrder.objects.all().order_by("-created_at")
    serializer_class = PurchaseOrderSerializer
    permission_classes = [ModulePermission]
    module = "procurement"

    def get_queryset(self):
        qs = _scoped(
            super().get_queryset().select_related("business_unit", "supplier")
            .prefetch_related("lines__product"),
            self.request,
        )
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        if not role_can(request.user, "procurement", "approve"):
            raise PermissionDenied("You do not have approval permission.")
        po = self.get_object()
        if po.status not in (PurchaseOrder.STATUS_DRAFT, PurchaseOrder.STATUS_SUBMITTED):
            return Response({"detail": "Only draft or submitted orders can be approved."}, status=400)
        po.status = PurchaseOrder.STATUS_APPROVED
        po.approved_by = request.user
        po.save(update_fields=["status", "approved_by"])
        return Response(self.get_serializer(po, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        po = self.get_object()
        if po.status in (PurchaseOrder.STATUS_RECEIVED, PurchaseOrder.STATUS_CANCELLED):
            return Response({"detail": "This order cannot be cancelled."}, status=400)
        po.status = PurchaseOrder.STATUS_CANCELLED
        po.save(update_fields=["status"])
        return Response(self.get_serializer(po, context={"request": request}).data)
