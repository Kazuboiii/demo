"""
Shared inventory engine with strict division ownership.

One codebase serves both Resort and Healthcare/Pharmacy inventory. Every
stock-bearing record carries an explicit ``business_unit`` (the business
division). Ownership is denormalized onto batches and movements so a Resort
movement can never reference a Healthcare batch, and is re-validated in
``save()``, in the central transaction service and in the API serializers.

Stock balances are *never* maintained by arbitrary counters: every change is
posted through :mod:`inventory.services` inside a database transaction and
writes an immutable ledger row (:class:`StockMovement`).
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F, Q, Sum
from django.utils import timezone

from core.models import BusinessUnit, Department


class Location(models.Model):
    """Inventory location (storage, ward, kitchen, ...)."""

    name = models.CharField(max_length=100)
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.CASCADE, related_name="locations"
    )
    type = models.CharField(max_length=50, blank=True, default="storage")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["business_unit__name", "name"]
        unique_together = [("name", "business_unit")]
        verbose_name = "Inventory Location"
        verbose_name_plural = "Inventory Locations"

    def __str__(self):
        return f"{self.business_unit.name} - {self.name}"

    def save(self, *args, **kwargs):
        if self.business_unit_id is None:
            raise ValidationError("A location must belong to a business division.")
        return super().save(*args, **kwargs)


class InventoryLocation(Location):
    """Explicit division-owned inventory location alias."""

    class Meta:
        proxy = True


class Supplier(models.Model):
    """Supplier scoped to one division. A supplier cannot be shared."""

    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.CASCADE, related_name="suppliers"
    )
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=150)
    contact_person = models.CharField(max_length=120, blank=True, default="")
    phone = models.CharField(max_length=40, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    address = models.TextField(blank=True, default="")
    tax_id = models.CharField(max_length=60, blank=True, default="")
    payment_terms_days = models.PositiveIntegerField(default=30)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["business_unit__name", "name"]
        unique_together = [("business_unit", "code")]
        verbose_name = "Supplier"
        verbose_name_plural = "Suppliers"

    def __str__(self):
        return f"{self.name} ({self.business_unit.code})"


class Product(models.Model):
    sku = models.CharField(max_length=60)
    barcode = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        db_index=True,
        help_text="Manufacturer barcode / GTIN when available.",
    )
    name = models.CharField(max_length=150)
    category = models.CharField(max_length=80, blank=True, default="")
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.CASCADE, related_name="products"
    )
    unit = models.CharField(max_length=40, default="piece")
    min_stock = models.PositiveIntegerField(default=0)
    is_perishable = models.BooleanField(default=False)
    batch_tracking_required = models.BooleanField(
        default=False,
        help_text="Whether this product requires batch/lot tracking for stock moves.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        ordering = ["business_unit__name", "name"]
        unique_together = [("sku", "business_unit")]
        verbose_name = "Product"
        verbose_name_plural = "Products"
        indexes = [
            models.Index(fields=["business_unit", "is_active"]),
            models.Index(fields=["business_unit", "created_at"]),
        ]

    def __str__(self):
        return self.name

    def usable_stock(self):
        cached = getattr(self, "annotated_usable_stock", None)
        if cached is not None:
            return int(cached)
        return sum(
            b.usable_quantity()
            for b in self.batches.filter(status=ProductBatch.STATUS_USABLE)
        )

    def low_stock(self):
        return self.usable_stock() <= self.min_stock


class ProductBatch(models.Model):
    STATUS_USABLE = "usable"
    STATUS_QUARANTINED = "quarantined"
    STATUS_EXPIRED = "expired"
    STATUS_DAMAGED = "damaged"
    STATUS_CHOICES = [
        (STATUS_USABLE, "Usable"),
        (STATUS_QUARANTINED, "Quarantined"),
        (STATUS_EXPIRED, "Expired"),
        (STATUS_DAMAGED, "Damaged"),
    ]

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="batches")
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.PROTECT, related_name="product_batches"
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name="batches"
    )
    location = models.ForeignKey(
        Location, on_delete=models.SET_NULL, null=True, blank=True, related_name="batches"
    )
    batch_number = models.CharField(max_length=60)
    lot_number = models.CharField(max_length=60, blank=True, default="")
    expiry_date = models.DateField(null=True, blank=True)
    quantity_received = models.PositiveIntegerField(default=0)
    quantity_remaining = models.PositiveIntegerField(default=0)
    unit_cost = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    received_reference = models.CharField(max_length=100, blank=True, default="")
    received_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_USABLE)

    class Meta:
        ordering = ["product__name", "expiry_date", "batch_number"]
        unique_together = [("business_unit", "product", "batch_number")]
        verbose_name = "Product Batch"
        verbose_name_plural = "Product Batches"
        indexes = [
            models.Index(fields=["business_unit", "status", "expiry_date"]),
            models.Index(fields=["product", "status", "expiry_date"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity_remaining__gte=0),
                name="batch_quantity_remaining_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(quantity_received__gte=0),
                name="batch_quantity_received_non_negative",
            ),
        ]

    def __str__(self):
        return f"{self.product.name} / {self.batch_number}"

    def clean(self):
        if self.product_id and self.business_unit_id and (
            self.product.business_unit_id != self.business_unit_id
        ):
            raise ValidationError(
                "Batch division must match the owning product division."
            )
        if self.location_id and self.location.business_unit_id != self.business_unit_id:
            raise ValidationError("Batch location must belong to the same division.")
        if self.supplier_id and self.supplier.business_unit_id != self.business_unit_id:
            raise ValidationError("Batch supplier must belong to the same division.")

    def save(self, *args, **kwargs):
        if self.product_id:
            self.business_unit_id = self.product.business_unit_id
        self.full_clean(exclude=["quantity_remaining", "quantity_received"])
        return super().save(*args, **kwargs)

    def get_business_unit(self):
        return self.business_unit or (self.product.business_unit if self.product_id else None)

    @property
    def is_expired(self):
        if not self.expiry_date:
            return False
        return self.expiry_date < timezone.now().date()

    def usable_quantity(self):
        if self.status != self.STATUS_USABLE or self.is_expired:
            return 0
        return self.quantity_remaining

    def issue(self, quantity):
        """Atomically deduct usable quantity. Returns remaining or raises."""
        if quantity <= 0:
            raise ValueError("Quantity must be positive.")
        if self.status != self.STATUS_USABLE:
            raise ValueError(f"Batch {self.batch_number} is not usable (status={self.status}).")
        if self.is_expired:
            raise ValueError(f"Batch {self.batch_number} has expired.")
        if self.quantity_remaining < quantity:
            raise ValueError(
                f"Insufficient stock: requested {quantity}, available {self.quantity_remaining}."
            )
        changed = type(self).objects.filter(
            pk=self.pk, status=self.STATUS_USABLE, quantity_remaining__gte=quantity
        ).filter(Q(expiry_date__isnull=True) | Q(expiry_date__gte=timezone.now().date())).update(
            quantity_remaining=F("quantity_remaining") - quantity
        )
        if not changed:
            raise ValueError("Batch is unavailable or has insufficient usable stock.")
        self.refresh_from_db(fields=["quantity_remaining"])
        return self.quantity_remaining


class LowStockAlert(models.Model):
    product = models.ForeignKey(
        "Product", on_delete=models.CASCADE, related_name="low_stock_alerts"
    )
    triggered_at = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-triggered_at"]
        verbose_name = "Low Stock Alert"
        verbose_name_plural = "Low Stock Alerts"

    def __str__(self):
        return f"Low stock: {self.product.name} ({self.product.usable_stock()} / {self.product.min_stock})"

    def is_resolved(self):
        return self.resolved

    def resolve(self):
        self.resolved = True
        self.resolved_at = timezone.now()
        self.save(update_fields=["resolved", "resolved_at"])

    @classmethod
    def check_and_create(cls):
        """Create alerts for products that are low on stock.

        Usable stock includes non-perishable batches (no expiry date) and
        excludes expired, quarantined and damaged batches.
        """
        today = timezone.now().date()
        low_stock_products = Product.objects.annotate(
            uq=Sum(
                "batches__quantity_remaining",
                filter=Q(
                    batches__status=ProductBatch.STATUS_USABLE,
                )
                & (Q(batches__expiry_date__isnull=True) | Q(batches__expiry_date__gte=today)),
            )
        ).filter(uq__lte=F("min_stock"), is_active=True, uq__isnull=False)

        for product in low_stock_products:
            if not cls.objects.filter(product=product, resolved=False).exists():
                cls.objects.create(product=product)

    @classmethod
    def resolve_expired(cls):
        """Resolve alerts for products that have been restocked above the threshold."""
        for alert in cls.objects.filter(resolved=False).select_related("product"):
            if alert.product.usable_stock() > alert.product.min_stock:
                alert.resolve()


class StockReceipt(models.Model):
    """Goods Received Note (goods receipt header). Immutable after posting."""

    STATUS_POSTED = "posted"
    STATUS_VOID = "void"
    STATUS_CHOICES = [(STATUS_POSTED, "Posted"), (STATUS_VOID, "Void")]

    reference = models.CharField(max_length=60, unique=True)
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.PROTECT, related_name="stock_receipts"
    )
    location = models.ForeignKey(
        Location, on_delete=models.PROTECT, related_name="receipts"
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name="receipts"
    )
    purchase_order = models.ForeignKey(
        "PurchaseOrder", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="receipts",
    )
    received_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="receipts"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_POSTED)
    idempotency_key = models.CharField(max_length=100, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    received_at = models.DateTimeField(auto_now_add=True)
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_at"]
        verbose_name = "Stock Receipt"
        verbose_name_plural = "Stock Receipts"
        indexes = [
            models.Index(fields=["business_unit", "-received_at"]),
            models.Index(fields=["supplier", "-received_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["business_unit", "idempotency_key"],
                condition=~Q(idempotency_key=""),
                name="unique_receipt_idempotency_per_division",
            )
        ]

    def __str__(self):
        return self.reference

    def clean(self):
        if self.location_id and self.location.business_unit_id != self.business_unit_id:
            raise ValidationError("Receipt location must belong to the receipt division.")
        if self.supplier_id and self.supplier.business_unit_id != self.business_unit_id:
            raise ValidationError("Receipt supplier must belong to the receipt division.")

    def get_business_unit(self):
        return self.business_unit


class GoodsReceipt(StockReceipt):
    """Terminology alias used by procurement reports."""

    class Meta:
        proxy = True


class StockReceiptLine(models.Model):
    receipt = models.ForeignKey(
        StockReceipt, on_delete=models.CASCADE, related_name="lines"
    )
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="receipt_lines")
    batch_number = models.CharField(max_length=60)
    lot_number = models.CharField(max_length=60, blank=True, default="")
    expiry_date = models.DateField(null=True, blank=True)
    quantity = models.PositiveIntegerField()
    unit_cost = models.DecimalField(max_digits=14, decimal_places=4, default=0)

    class Meta:
        verbose_name = "Stock Receipt Line"
        verbose_name_plural = "Stock Receipt Lines"

    def process(self):
        """Deprecated: posting now goes through inventory.services.post_receipt."""
        from .services import post_receipt_line

        post_receipt_line(self.receipt, self)


class StockIssue(models.Model):
    reference = models.CharField(max_length=60, unique=True)
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.PROTECT, related_name="stock_issues"
    )
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="stock_issues"
    )
    location = models.ForeignKey(
        Location, on_delete=models.PROTECT, null=True, blank=True, related_name="issues"
    )
    issued_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="stock_issues"
    )
    idempotency_key = models.CharField(max_length=100, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    issued_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-issued_at"]
        verbose_name = "Stock Issue"
        verbose_name_plural = "Stock Issues"
        indexes = [models.Index(fields=["business_unit", "-issued_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["business_unit", "idempotency_key"],
                condition=~Q(idempotency_key=""),
                name="unique_issue_idempotency_per_division",
            )
        ]

    def __str__(self):
        return self.reference

    def clean(self):
        if self.department_id and self.department.business_unit_id != self.business_unit_id:
            raise ValidationError("Issue department must belong to the issue division.")
        if self.location_id and self.location.business_unit_id != self.business_unit_id:
            raise ValidationError("Issue location must belong to the issue division.")

    def get_business_unit(self):
        return self.business_unit

    def process(self):
        """Deprecated: posting now goes through inventory.services.post_issue."""
        from .services import post_issue_line

        for line in self.lines.select_related("product_batch"):
            post_issue_line(self, line)


class StockIssueLine(models.Model):
    issue = models.ForeignKey(StockIssue, on_delete=models.CASCADE, related_name="lines")
    product_batch = models.ForeignKey(
        ProductBatch, on_delete=models.PROTECT, related_name="issue_lines"
    )
    quantity = models.PositiveIntegerField()

    class Meta:
        verbose_name = "Stock Issue Line"
        verbose_name_plural = "Stock Issue Lines"


class StockTransfer(models.Model):
    reference = models.CharField(max_length=60, unique=True)
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.PROTECT, related_name="stock_transfers"
    )
    from_location = models.ForeignKey(
        Location, on_delete=models.PROTECT, related_name="transfers_out"
    )
    to_location = models.ForeignKey(
        Location, on_delete=models.PROTECT, related_name="transfers_in"
    )
    transferred_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="transfers"
    )
    notes = models.TextField(blank=True, default="")
    transferred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-transferred_at"]
        verbose_name = "Stock Transfer"
        verbose_name_plural = "Stock Transfers"

    def __str__(self):
        return self.reference

    def clean(self):
        if self.from_location.business_unit_id != self.business_unit_id:
            raise ValidationError("Source location must belong to the transfer division.")
        if self.to_location.business_unit_id != self.business_unit_id:
            raise ValidationError("Destination location must belong to the transfer division.")


class StockTransferLine(models.Model):
    transfer = models.ForeignKey(StockTransfer, on_delete=models.CASCADE, related_name="lines")
    product_batch = models.ForeignKey(
        ProductBatch, on_delete=models.PROTECT, related_name="transfer_lines"
    )
    quantity = models.PositiveIntegerField()

    class Meta:
        verbose_name = "Stock Transfer Line"
        verbose_name_plural = "Stock Transfer Lines"


class StockMovement(models.Model):
    """Immutable ledger row. Created only by the inventory transaction service."""

    TYPE_RECEIPT = "receipt"
    TYPE_ISSUE = "issue"
    TYPE_TRANSFER_IN = "transfer_in"
    TYPE_TRANSFER_OUT = "transfer_out"
    TYPE_ADJUSTMENT = "adjustment"
    TYPE_SALE = "sale"
    TYPE_DAMAGE = "damage"
    TYPE_CHOICES = [
        (TYPE_RECEIPT, "Receipt"),
        (TYPE_ISSUE, "Issue"),
        (TYPE_TRANSFER_IN, "Transfer In"),
        (TYPE_TRANSFER_OUT, "Transfer Out"),
        (TYPE_ADJUSTMENT, "Adjustment"),
        (TYPE_SALE, "Sale"),
        (TYPE_DAMAGE, "Damage"),
    ]

    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.PROTECT, related_name="stock_movements"
    )
    product_batch = models.ForeignKey(
        ProductBatch, on_delete=models.PROTECT, related_name="movements"
    )
    location = models.ForeignKey(
        Location, on_delete=models.PROTECT, null=True, blank=True, related_name="movements"
    )
    movement_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    quantity = models.IntegerField()  # positive for in, negative for out
    unit_cost = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    quantity_before = models.PositiveIntegerField(default=0)
    quantity_after = models.PositiveIntegerField(default=0)
    reference = models.CharField(max_length=100, blank=True, default="")
    source_type = models.CharField(max_length=60, blank=True, default="")
    source_id = models.CharField(max_length=60, blank=True, default="")
    idempotency_key = models.CharField(max_length=120, blank=True, default="")
    performed_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="movements"
    )
    notes = models.CharField(max_length=250, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Stock Movement"
        verbose_name_plural = "Stock Movements"
        indexes = [
            models.Index(fields=["business_unit", "-created_at"]),
            models.Index(fields=["product_batch", "-created_at"]),
            models.Index(fields=["movement_type", "-created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["business_unit", "idempotency_key"],
                condition=~Q(idempotency_key=""),
                name="unique_movement_idempotency_per_division",
            )
        ]

    def __str__(self):
        return f"{self.movement_type} {self.quantity} {self.product_batch}"

    def clean(self):
        if self.product_batch_id and self.business_unit_id and (
            self.product_batch.business_unit_id != self.business_unit_id
        ):
            raise ValidationError(
                "Movement division must match the batch division."
            )

    def save(self, *args, **kwargs):
        if self.product_batch_id:
            self.business_unit_id = self.product_batch.business_unit_id
        if self.location_id and self.location.business_unit_id != self.business_unit_id:
            raise ValidationError("Movement location must belong to the batch division.")
        return super().save(*args, **kwargs)


class StockAdjustment(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]

    reference = models.CharField(max_length=60, unique=True)
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.PROTECT, related_name="stock_adjustments"
    )
    reason = models.CharField(max_length=250)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    requested_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="stock_adjustments",
    )
    approved_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="approved_adjustments",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Stock Adjustment"
        verbose_name_plural = "Stock Adjustments"

    def __str__(self):
        return f"{self.reference} ({self.status})"


class StockAdjustmentLine(models.Model):
    adjustment = models.ForeignKey(
        StockAdjustment, on_delete=models.CASCADE, related_name="lines"
    )
    product_batch = models.ForeignKey(
        ProductBatch, on_delete=models.PROTECT, related_name="adjustment_lines"
    )
    quantity_delta = models.IntegerField(
        help_text="Positive increases stock, negative decreases it."
    )
    notes = models.CharField(max_length=250, blank=True, default="")

    class Meta:
        verbose_name = "Stock Adjustment Line"
        verbose_name_plural = "Stock Adjustment Lines"


class StockCount(models.Model):
    STATUS_OPEN = "open"
    STATUS_POSTED = "posted"
    STATUS_CHOICES = [(STATUS_OPEN, "Open"), (STATUS_POSTED, "Posted")]

    reference = models.CharField(max_length=60, unique=True)
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.PROTECT, related_name="stock_counts"
    )
    location = models.ForeignKey(
        Location, on_delete=models.PROTECT, null=True, blank=True, related_name="counts"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN)
    counted_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="stock_counts",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Stock Count"
        verbose_name_plural = "Stock Counts"

    def __str__(self):
        return self.reference


class StockCountLine(models.Model):
    count = models.ForeignKey(StockCount, on_delete=models.CASCADE, related_name="lines")
    product_batch = models.ForeignKey(
        ProductBatch, on_delete=models.PROTECT, related_name="count_lines"
    )
    system_quantity = models.PositiveIntegerField()
    counted_quantity = models.PositiveIntegerField()

    class Meta:
        verbose_name = "Stock Count Line"
        verbose_name_plural = "Stock Count Lines"

    @property
    def variance(self):
        return self.counted_quantity - self.system_quantity


class PurchaseOrder(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_SUBMITTED = "submitted"
    STATUS_APPROVED = "approved"
    STATUS_PARTIAL = "partially_received"
    STATUS_RECEIVED = "received"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_PARTIAL, "Partially Received"),
        (STATUS_RECEIVED, "Received"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    reference = models.CharField(max_length=60, unique=True)
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.PROTECT, related_name="purchase_orders"
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="purchase_orders"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    order_date = models.DateField(default=timezone.localdate)
    expected_date = models.DateField(null=True, blank=True)
    currency = models.CharField(max_length=8, default="NPR")
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="purchase_orders",
    )
    approved_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="approved_purchase_orders",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Purchase Order"
        verbose_name_plural = "Purchase Orders"
        indexes = [models.Index(fields=["business_unit", "-created_at"])]

    def __str__(self):
        return self.reference

    @property
    def total(self):
        return sum((line.line_total for line in self.lines.all()), Decimal("0"))

    def clean(self):
        if self.supplier_id and self.supplier.business_unit_id != self.business_unit_id:
            raise ValidationError("Purchase order supplier must belong to its division.")


class PurchaseOrderLine(models.Model):
    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE, related_name="lines"
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="purchase_order_lines"
    )
    quantity = models.PositiveIntegerField()
    unit_cost = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    received_quantity = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Purchase Order Line"
        verbose_name_plural = "Purchase Order Lines"

    @property
    def line_total(self):
        return (self.unit_cost or Decimal("0")) * self.quantity
