"""
Medicine delivery workflow integrated with the unified inventory engine.

Delivery statuses: requested -> reserved -> dispatched -> delivered / failed.
Stock is reserved at dispatch and reconciled (actually deducted) on delivery.
"""

from django.db import models, transaction
from django.utils import timezone

from core.models import BusinessUnit
from fleet.models import DriverProfile, Vehicle
from inventory.models import ProductBatch


class DeliveryRequest(models.Model):
    STATUS_REQUESTED = "requested"
    STATUS_RESERVED = "reserved"
    STATUS_DISPATCHED = "dispatched"
    STATUS_DELIVERED = "delivered"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_REQUESTED, "Requested"),
        (STATUS_RESERVED, "Reserved"),
        (STATUS_DISPATCHED, "Dispatched"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_FAILED, "Failed"),
    ]

    reference = models.CharField(max_length=60, unique=True)
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.CASCADE, related_name="medicine_deliveries"
    )
    recipient_name = models.CharField(max_length=150)
    recipient_address = models.CharField(max_length=250)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_REQUESTED)
    created_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="deliveries"
    )
    assigned_driver = models.ForeignKey(
        DriverProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name="deliveries"
    )
    assigned_vehicle = models.ForeignKey(
        Vehicle, on_delete=models.SET_NULL, null=True, blank=True, related_name="deliveries"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Medicine Delivery"
        verbose_name_plural = "Medicine Deliveries"

    def __str__(self):
        return self.reference


class DeliveryLineItem(models.Model):
    delivery = models.ForeignKey(
        DeliveryRequest, on_delete=models.CASCADE, related_name="line_items"
    )
    product_batch = models.ForeignKey(ProductBatch, on_delete=models.PROTECT, related_name="delivery_lines")
    quantity_reserved = models.PositiveIntegerField()
    quantity_delivered = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Delivery Line Item"
        verbose_name_plural = "Delivery Line Items"

    def __str__(self):
        return f"{self.product_batch.batch_number} x{self.quantity_reserved}"
