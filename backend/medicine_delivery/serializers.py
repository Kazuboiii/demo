from rest_framework import serializers

from .models import DeliveryLineItem, DeliveryRequest


class DeliveryLineItemSerializer(serializers.ModelSerializer):
    batch_number = serializers.ReadOnlyField(source="product_batch.batch_number")
    product_name = serializers.ReadOnlyField(source="product_batch.product.name")

    class Meta:
        model = DeliveryLineItem
        fields = ["id", "product_batch", "batch_number", "product_name",
                  "quantity_reserved", "quantity_delivered"]


class DeliveryRequestSerializer(serializers.ModelSerializer):
    lines = DeliveryLineItemSerializer(source="line_items", many=True, read_only=True)
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")
    created_by_name = serializers.ReadOnlyField(source="created_by.email", default=None)

    class Meta:
        model = DeliveryRequest
        fields = [
            "id", "reference", "business_unit", "business_unit_name", "recipient_name",
            "recipient_address", "status", "created_by", "created_by_name",
            "assigned_driver", "assigned_vehicle", "created_at", "updated_at", "lines",
        ]
        read_only_fields = ["created_by", "created_at", "updated_at"]
