from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from django.db import transaction

from core.permissions import BusinessUnitScoped

from inventory.models import StockMovement
from inventory.services import StockError, record_sale
from .models import DeliveryLineItem, DeliveryRequest
from .serializers import DeliveryRequestSerializer


class DeliveryRequestViewSet(viewsets.ModelViewSet):
    queryset = DeliveryRequest.objects.all().order_by("-created_at")
    serializer_class = DeliveryRequestSerializer
    permission_classes = [BusinessUnitScoped]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user or not user.is_authenticated:
            return qs.none()
        if user.is_superuser or user.has_role("super_admin"):
            return qs
        return qs.filter(business_unit=user.business_unit)

    def perform_create(self, serializer):
        user = self.request.user
        bu = serializer.validated_data.get("business_unit") or user.business_unit
        if not user.can_access_business_unit(bu):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Not authorized for this business unit.")
        serializer.save(created_by=user, business_unit=bu)

    @action(detail=True, methods=["post"], url_path="reserve")
    def reserve(self, request, pk=None):
        """Validate usable stock and reserve quantities."""
        delivery = self.get_object()
        if delivery.status != DeliveryRequest.STATUS_REQUESTED:
            return Response({"detail": "Only requested deliveries can be reserved."}, status=400)
        lines = delivery.line_items.select_related("product_batch__product")
        if not lines:
            return Response({"detail": "No line items."}, status=400)
        for line in lines:
            batch = line.product_batch
            if batch.business_unit_id != delivery.business_unit_id:
                return Response(
                    {"detail": "Delivery line belongs to another division."},
                    status=400,
                )
            available = batch.usable_quantity()
            if available < line.quantity_reserved:
                return Response(
                    {"detail": f"Insufficient stock for {batch.batch_number}. Available {available}."},
                    status=400,
                )
        delivery.status = DeliveryRequest.STATUS_RESERVED
        delivery.save(update_fields=["status", "updated_at"])
        return Response({"detail": "Stock reserved.", "status": delivery.status})

    @action(detail=True, methods=["post"], url_path="dispatch")
    def ship_dispatch(self, request, pk=None):
        """Dispatch the reserved delivery: deduct stock and mark as dispatched."""
        delivery = self.get_object()
        if delivery.status != DeliveryRequest.STATUS_RESERVED:
            return Response({"detail": "Only reserved deliveries can be dispatched."}, status=400)
        with transaction.atomic():
            changed = DeliveryRequest.objects.filter(pk=delivery.pk, status=DeliveryRequest.STATUS_RESERVED).update(status=DeliveryRequest.STATUS_DISPATCHED)
            if not changed:
                return Response({"detail": "Delivery has already changed. Refresh before retrying."}, status=409)
            delivery.refresh_from_db()
            for line in delivery.line_items.select_related("product_batch"):
                if line.product_batch.business_unit_id != delivery.business_unit_id:
                    raise ValidationError("Delivery line belongs to another division.")
                try:
                    record_sale(
                        division=delivery.business_unit,
                        reference=delivery.reference,
                        batch=line.product_batch,
                        quantity=line.quantity_reserved,
                        performed_by=request.user,
                        location=delivery.business_unit.locations.filter(is_active=True).first()
                        or delivery.business_unit.locations.first(),
                        idempotency_key=f"delivery-{delivery.pk}-{line.pk}",
                    )
                except StockError as exc:
                    raise ValidationError(str(exc))
            delivery.status = DeliveryRequest.STATUS_DISPATCHED
            delivery.save(update_fields=["status", "updated_at"])
        
        # Check for low stock alerts after deducting
        from inventory.models import LowStockAlert
        LowStockAlert.check_and_create()
        
        return Response({"detail": "Dispatched and stock deducted.", "status": delivery.status})

    @action(detail=True, methods=["post"], url_path="deliver")
    def deliver(self, request, pk=None):
        """Mark delivery as delivered. Stock was already deducted at dispatch."""
        delivery = self.get_object()
        if delivery.status != DeliveryRequest.STATUS_DISPATCHED:
            return Response({"detail": "Only dispatched deliveries can be completed."}, status=400)
        delivery.status = DeliveryRequest.STATUS_DELIVERED
        delivery.save(update_fields=["status", "updated_at"])
        for line in delivery.line_items.all():
            line.quantity_delivered = line.quantity_reserved
            line.save(update_fields=["quantity_delivered"])
        return Response({"detail": "Delivered.", "status": delivery.status})

    @action(detail=True, methods=["post"], url_path="deliver-now")
    def deliver_now(self, request, pk=None):
        """Legacy: dispatch and deliver in one step (deducts at dispatch)."""
        delivery = self.get_object()
        if delivery.status != DeliveryRequest.STATUS_RESERVED:
            return Response({"detail": "Only reserved deliveries can be dispatched."}, status=400)
        with transaction.atomic():
            changed = DeliveryRequest.objects.filter(pk=delivery.pk, status=DeliveryRequest.STATUS_RESERVED).update(status=DeliveryRequest.STATUS_DISPATCHED)
            if not changed:
                return Response({"detail": "Delivery has already changed. Refresh before retrying."}, status=409)
            delivery.refresh_from_db()
            for line in delivery.line_items.select_related("product_batch"):
                if line.product_batch.business_unit_id != delivery.business_unit_id:
                    raise ValidationError("Delivery line belongs to another division.")
                try:
                    record_sale(
                        division=delivery.business_unit,
                        reference=delivery.reference,
                        batch=line.product_batch,
                        quantity=line.quantity_reserved,
                        performed_by=request.user,
                        location=delivery.business_unit.locations.filter(is_active=True).first()
                        or delivery.business_unit.locations.first(),
                        idempotency_key=f"delivery-{delivery.pk}-{line.pk}",
                    )
                except StockError as exc:
                    raise ValidationError(str(exc))
            delivery.status = DeliveryRequest.STATUS_DELIVERED
            delivery.save(update_fields=["status", "updated_at"])
            for line in delivery.line_items.all():
                line.quantity_delivered = line.quantity_reserved
                line.save(update_fields=["quantity_delivered"])
        from inventory.models import LowStockAlert
        LowStockAlert.check_and_create()
        return Response({"detail": "Dispatched, stock deducted, and delivered.", "status": delivery.status})

    @action(detail=True, methods=["post"], url_path="fail")
    def fail(self, request, pk=None):
        delivery = self.get_object()
        if delivery.status not in (DeliveryRequest.STATUS_RESERVED, DeliveryRequest.STATUS_DISPATCHED):
            return Response({"detail": "Cannot fail this delivery."}, status=400)
        delivery.status = DeliveryRequest.STATUS_FAILED
        delivery.save(update_fields=["status", "updated_at"])
        return Response({"detail": "Delivery marked failed.", "status": delivery.status})

