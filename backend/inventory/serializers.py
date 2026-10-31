"""Inventory API serializers.

Serializers are a thin validation layer. All stock mutation is delegated to
:mod:`inventory.services`, which enforces division ownership and atomicity.
"""

from django.db import transaction
from rest_framework import serializers

from . import services
from .models import (
    Location,
    LowStockAlert,
    Product,
    ProductBatch,
    PurchaseOrder,
    PurchaseOrderLine,
    StockAdjustment,
    StockAdjustmentLine,
    StockCount,
    StockCountLine,
    StockIssue,
    StockIssueLine,
    StockMovement,
    StockReceipt,
    StockReceiptLine,
    StockTransfer,
    StockTransferLine,
    Supplier,
)


def _request_user(serializer):
    request = serializer.context.get("request")
    return getattr(request, "user", None)


def _check_division(serializer, division):
    user = _request_user(serializer)
    if user is not None and division is not None and not user.can_access_business_unit(division):
        raise serializers.ValidationError(
            "You are not authorized for this business division."
        )


def _idempotency_key(serializer):
    request = serializer.context.get("request")
    if request is not None:
        header = request.headers.get("Idempotency-Key") if hasattr(request, "headers") else None
        if header:
            return header
    return serializer.initial_data.get("idempotency_key", "") if hasattr(serializer, "initial_data") else ""


class LocationSerializer(serializers.ModelSerializer):
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")

    class Meta:
        model = Location
        fields = ["id", "name", "business_unit", "business_unit_name", "type", "is_active"]

    def validate_business_unit(self, value):
        _check_division(self, value)
        return value


class SupplierSerializer(serializers.ModelSerializer):
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")

    class Meta:
        model = Supplier
        fields = [
            "id", "business_unit", "business_unit_name", "code", "name",
            "contact_person", "phone", "email", "address", "tax_id",
            "payment_terms_days", "is_active", "created_at",
        ]
        read_only_fields = ["created_at"]

    def validate_business_unit(self, value):
        _check_division(self, value)
        return value


class ProductSerializer(serializers.ModelSerializer):
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")
    usable_stock = serializers.SerializerMethodField()
    is_low_stock = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id", "sku", "barcode", "name", "category", "business_unit",
            "business_unit_name", "unit", "min_stock", "is_perishable",
            "batch_tracking_required", "is_active", "created_at",
            "usable_stock", "is_low_stock",
        ]
        read_only_fields = ["created_at"]

    def validate_business_unit(self, value):
        _check_division(self, value)
        return value

    def get_usable_stock(self, obj):
        return obj.usable_stock()

    def get_is_low_stock(self, obj):
        return obj.low_stock()


class ProductBatchSerializer(serializers.ModelSerializer):
    product_name = serializers.ReadOnlyField(source="product.name")
    product_sku = serializers.ReadOnlyField(source="product.sku")
    product_unit = serializers.ReadOnlyField(source="product.unit")
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")
    supplier_name = serializers.ReadOnlyField(source="supplier.name", default=None)
    location_name = serializers.ReadOnlyField(source="location.name", default=None)
    is_expired = serializers.ReadOnlyField()
    usable_quantity = serializers.SerializerMethodField()

    class Meta:
        model = ProductBatch
        fields = [
            "id", "product", "product_name", "product_sku", "product_unit",
            "business_unit", "business_unit_name", "supplier", "supplier_name",
            "location", "location_name", "batch_number", "lot_number",
            "expiry_date", "quantity_received", "quantity_remaining", "unit_cost",
            "status", "received_at", "updated_at", "is_expired", "usable_quantity",
        ]
        read_only_fields = [
            "business_unit", "quantity_received", "quantity_remaining",
            "received_at", "updated_at",
        ]

    def get_usable_quantity(self, obj):
        return obj.usable_quantity()

    def validate(self, attrs):
        product = attrs.get("product", getattr(self.instance, "product", None))
        if product is not None and self.instance is None:
            raise serializers.ValidationError(
                "Batches are created by posting a goods receipt, not directly."
            )
        return attrs


class StockReceiptLineSerializer(serializers.ModelSerializer):
    quantity = serializers.IntegerField(min_value=1)

    class Meta:
        model = StockReceiptLine
        fields = [
            "id", "product", "batch_number", "lot_number", "expiry_date",
            "quantity", "unit_cost",
        ]


class StockReceiptSerializer(serializers.ModelSerializer):
    lines = StockReceiptLineSerializer(many=True)
    supplier_name = serializers.ReadOnlyField(source="supplier.name", default=None)
    location_name = serializers.ReadOnlyField(source="location.name", default=None)
    received_by_name = serializers.SerializerMethodField()

    class Meta:
        model = StockReceipt
        fields = [
            "id", "reference", "business_unit", "location", "location_name",
            "supplier", "supplier_name", "purchase_order", "received_by",
            "received_by_name", "status", "notes", "received_at", "posted_at",
            "lines",
        ]
        read_only_fields = ["received_by", "received_at", "posted_at", "status"]
        # The service resolves an existing reference as an idempotent replay.
        extra_kwargs = {"reference": {"validators": []}}

    def get_received_by_name(self, obj):
        if not obj.received_by:
            return None
        return obj.received_by.get_full_name() or obj.received_by.email

    def validate(self, attrs):
        division = attrs.get("business_unit", getattr(self.instance, "business_unit", None))
        _check_division(self, division)
        location = attrs.get("location", getattr(self.instance, "location", None))
        if location is None or location.business_unit_id != division.pk:
            raise serializers.ValidationError(
                "Receipt location must belong to the receipt division."
            )
        supplier = attrs.get("supplier", getattr(self.instance, "supplier", None))
        if supplier is not None and supplier.business_unit_id != division.pk:
            raise serializers.ValidationError(
                "Receipt supplier must belong to the receipt division."
            )
        if "lines" in attrs and not attrs["lines"]:
            raise serializers.ValidationError("At least one stock line is required.")
        for line in attrs.get("lines", []):
            if line["product"].business_unit_id != division.pk:
                raise serializers.ValidationError(
                    "Every receipt product must belong to the receipt division."
                )
        return attrs

    def create(self, validated_data):
        lines = validated_data.pop("lines")
        try:
            receipt, created = services.post_receipt(
                division=validated_data["business_unit"],
                location=validated_data["location"],
                reference=validated_data["reference"],
                lines=lines,
                received_by=_request_user(self),
                supplier=validated_data.get("supplier"),
                notes=validated_data.get("notes", ""),
                idempotency_key=_idempotency_key(self),
                purchase_order=validated_data.get("purchase_order"),
            )
        except services.StockError as exc:
            raise serializers.ValidationError(str(exc))
        self.was_created = created
        return receipt


class StockIssueLineSerializer(serializers.ModelSerializer):
    quantity = serializers.IntegerField(min_value=1)
    product = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.all(), required=False, write_only=True
    )

    class Meta:
        model = StockIssueLine
        fields = ["id", "product_batch", "product", "quantity"]
        extra_kwargs = {"product_batch": {"required": False}}

    def validate(self, attrs):
        if not attrs.get("product_batch") and not attrs.get("product"):
            raise serializers.ValidationError(
                "Provide a product_batch or a product for FEFO allocation."
            )
        return attrs


class StockIssueSerializer(serializers.ModelSerializer):
    lines = StockIssueLineSerializer(many=True)
    department_name = serializers.ReadOnlyField(source="department.name", default=None)

    class Meta:
        model = StockIssue
        fields = [
            "id", "reference", "business_unit", "department", "department_name",
            "location", "issued_by", "notes", "issued_at", "lines",
        ]
        read_only_fields = ["issued_by", "issued_at"]
        # The service resolves an existing reference as an idempotent replay.
        extra_kwargs = {"reference": {"validators": []}}

    def validate(self, attrs):
        division = attrs.get("business_unit", getattr(self.instance, "business_unit", None))
        _check_division(self, division)
        department = attrs.get("department", getattr(self.instance, "department", None))
        if department is None or department.business_unit_id != division.pk:
            raise serializers.ValidationError(
                "Issue department must belong to the issue division."
            )
        location = attrs.get("location")
        if location is not None and location.business_unit_id != division.pk:
            raise serializers.ValidationError(
                "Issue location must belong to the issue division."
            )
        if "lines" in attrs and not attrs["lines"]:
            raise serializers.ValidationError("At least one stock line is required.")
        for line in attrs.get("lines", []):
            batch = line.get("product_batch")
            product = line.get("product")
            if batch is not None and batch.business_unit_id != division.pk:
                raise serializers.ValidationError(
                    "Every issue batch must belong to the issue division."
                )
            if product is not None and product.business_unit_id != division.pk:
                raise serializers.ValidationError(
                    "Every issue product must belong to the issue division."
                )
        return attrs

    def create(self, validated_data):
        lines = validated_data.pop("lines")
        try:
            issue, created = services.post_issue(
                division=validated_data["business_unit"],
                department=validated_data["department"],
                reference=validated_data["reference"],
                lines=lines,
                issued_by=_request_user(self),
                notes=validated_data.get("notes", ""),
                idempotency_key=_idempotency_key(self),
                location=validated_data.get("location"),
            )
        except services.StockError as exc:
            raise serializers.ValidationError(str(exc))
        self.was_created = created
        return issue


class StockAdjustmentLineSerializer(serializers.ModelSerializer):
    quantity_delta = serializers.IntegerField()

    class Meta:
        model = StockAdjustmentLine
        fields = ["id", "product_batch", "quantity_delta", "notes"]


class StockAdjustmentSerializer(serializers.ModelSerializer):
    lines = StockAdjustmentLineSerializer(many=True)
    requested_by_name = serializers.SerializerMethodField()

    class Meta:
        model = StockAdjustment
        fields = [
            "id", "reference", "business_unit", "reason", "status",
            "requested_by", "requested_by_name", "approved_by", "approved_at",
            "created_at", "lines",
        ]
        read_only_fields = ["requested_by", "approved_by", "approved_at", "status"]

    def get_requested_by_name(self, obj):
        if not obj.requested_by:
            return None
        return obj.requested_by.get_full_name() or obj.requested_by.email

    def validate(self, attrs):
        division = attrs.get("business_unit", getattr(self.instance, "business_unit", None))
        _check_division(self, division)
        for line in attrs.get("lines", []):
            if line["product_batch"].business_unit_id != division.pk:
                raise serializers.ValidationError(
                    "Every adjustment batch must belong to the adjustment division."
                )
        return attrs

    def create(self, validated_data):
        lines = validated_data.pop("lines")
        try:
            return services.post_adjustment(
                division=validated_data["business_unit"],
                reference=validated_data["reference"],
                reason=validated_data["reason"],
                lines=lines,
                requested_by=_request_user(self),
            )
        except services.StockError as exc:
            raise serializers.ValidationError(str(exc))


class StockCountLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockCountLine
        fields = ["id", "product_batch", "system_quantity", "counted_quantity"]


class StockCountSerializer(serializers.ModelSerializer):
    lines = StockCountLineSerializer(many=True)

    class Meta:
        model = StockCount
        fields = ["id", "reference", "business_unit", "location", "status",
                  "counted_by", "created_at", "lines"]
        read_only_fields = ["counted_by", "status", "created_at"]

    def validate(self, attrs):
        division = attrs.get("business_unit", getattr(self.instance, "business_unit", None))
        _check_division(self, division)
        for line in attrs.get("lines", []):
            if line["product_batch"].business_unit_id != division.pk:
                raise serializers.ValidationError(
                    "Every count batch must belong to the count division."
                )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        lines = validated_data.pop("lines")
        count = StockCount.objects.create(**validated_data)
        for line in lines:
            StockCountLine.objects.create(count=count, **line)
        return count


class PurchaseOrderLineSerializer(serializers.ModelSerializer):
    product_name = serializers.ReadOnlyField(source="product.name")

    class Meta:
        model = PurchaseOrderLine
        fields = ["id", "product", "product_name", "quantity", "unit_cost",
                  "received_quantity"]
        read_only_fields = ["received_quantity"]


class PurchaseOrderSerializer(serializers.ModelSerializer):
    lines = PurchaseOrderLineSerializer(many=True)
    supplier_name = serializers.ReadOnlyField(source="supplier.name")
    total = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = [
            "id", "reference", "business_unit", "supplier", "supplier_name",
            "status", "order_date", "expected_date", "currency", "notes",
            "created_by", "approved_by", "created_at", "lines", "total",
        ]
        read_only_fields = ["created_by", "approved_by", "created_at"]

    def get_total(self, obj):
        return str(obj.total)

    def validate(self, attrs):
        division = attrs.get("business_unit", getattr(self.instance, "business_unit", None))
        _check_division(self, division)
        supplier = attrs.get("supplier", getattr(self.instance, "supplier", None))
        if supplier is not None and supplier.business_unit_id != division.pk:
            raise serializers.ValidationError(
                "Purchase order supplier must belong to its division."
            )
        for line in attrs.get("lines", []):
            if line["product"].business_unit_id != division.pk:
                raise serializers.ValidationError(
                    "Every purchase order product must belong to its division."
                )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        lines = validated_data.pop("lines")
        po = PurchaseOrder.objects.create(
            **validated_data, created_by=_request_user(self)
        )
        for line in lines:
            PurchaseOrderLine.objects.create(purchase_order=po, **line)
        return po


class StockTransferLineSerializer(serializers.ModelSerializer):
    quantity = serializers.IntegerField(min_value=1)

    class Meta:
        model = StockTransferLine
        fields = ["id", "product_batch", "quantity"]


class StockTransferSerializer(serializers.ModelSerializer):
    lines = StockTransferLineSerializer(many=True)

    class Meta:
        model = StockTransfer
        fields = ["id", "reference", "business_unit", "from_location", "to_location",
                  "transferred_by", "notes", "transferred_at", "lines"]
        read_only_fields = ["transferred_by", "transferred_at"]

    def validate(self, attrs):
        division = attrs.get("business_unit", getattr(self.instance, "business_unit", None))
        _check_division(self, division)
        for line in attrs.get("lines", []):
            if line["product_batch"].business_unit_id != division.pk:
                raise serializers.ValidationError(
                    "Every transfer batch must belong to the transfer division."
                )
        return attrs

    def create(self, validated_data):
        lines = validated_data.pop("lines")
        try:
            return services.post_transfer(
                division=validated_data["business_unit"],
                reference=validated_data["reference"],
                from_location=validated_data["from_location"],
                to_location=validated_data["to_location"],
                lines=lines,
                transferred_by=_request_user(self),
                notes=validated_data.get("notes", ""),
            )
        except services.StockError as exc:
            raise serializers.ValidationError(str(exc))


class LowStockAlertSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)

    class Meta:
        model = LowStockAlert
        fields = ["id", "product", "triggered_at", "resolved", "resolved_at"]


class StockMovementSerializer(serializers.ModelSerializer):
    product_batch_name = serializers.ReadOnlyField(source="product_batch.__str__")
    product_name = serializers.ReadOnlyField(source="product_batch.product.name")
    product_sku = serializers.ReadOnlyField(source="product_batch.product.sku")
    batch_number = serializers.ReadOnlyField(source="product_batch.batch_number")
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")
    location_name = serializers.ReadOnlyField(source="location.name", default=None)
    performed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = StockMovement
        fields = [
            "id", "business_unit", "business_unit_name", "product_batch",
            "product_batch_name", "product_name", "product_sku", "batch_number",
            "location", "location_name", "movement_type", "quantity", "unit_cost",
            "quantity_before", "quantity_after", "reference", "source_type",
            "source_id", "performed_by", "performed_by_name", "notes", "created_at",
        ]

    def get_performed_by_name(self, obj):
        if not obj.performed_by:
            return None
        return obj.performed_by.get_full_name() or obj.performed_by.email
