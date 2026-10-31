"""
Central inventory transaction service.

Every stock movement in the platform must go through this module. It:

* resolves and validates the owning business division;
* writes immutable :class:`StockMovement` ledger rows with before/after
  quantities and cost snapshots;
* uses atomic transactions and conditional ``UPDATE`` statements so a batch
  can never be oversold;
* is idempotent: replaying a receipt/issue with the same reference or
  idempotency key returns the original document instead of duplicating stock;
* implements FEFO allocation for expiry-sensitive products.

No view, serializer or report may mutate ``quantity_remaining`` directly.
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from .models import (
    ProductBatch,
    PurchaseOrder,
    StockAdjustment,
    StockAdjustmentLine,
    StockCount,
    StockIssue,
    StockIssueLine,
    StockMovement,
    StockReceipt,
    StockReceiptLine,
    StockTransfer,
    StockTransferLine,
)


class StockError(Exception):
    """Business-rule failure while posting stock."""


class DivisionMismatch(StockError):
    """Raised when a stock operation crosses division ownership."""


def _require_division(obj, division, label):
    if division is None:
        raise DivisionMismatch(f"{label} has no business division.")
    if getattr(obj, "business_unit_id", None) != division.pk:
        raise DivisionMismatch(f"{label} does not belong to the selected division.")


def _lock_batch(batch_id):
    return (
        ProductBatch.objects.select_for_update()
        .select_related("product")
        .get(pk=batch_id)
    )


def _write_movement(batch, division, movement_type, quantity, before, after, *,
                    location=None, reference="", performed_by=None, unit_cost=None,
                    source_type="", source_id="", idempotency_key="", notes=""):
    """Create one immutable ledger row.

    ``quantity`` is signed (positive in, negative out); ``before``/``after`` are
    the exact batch balances around the change.
    """
    if batch.business_unit_id != division.pk:
        raise DivisionMismatch("Movement batch belongs to another division.")
    if location is not None and location.business_unit_id != division.pk:
        raise DivisionMismatch("Movement location belongs to another division.")
    return StockMovement.objects.create(
        business_unit=division,
        product_batch=batch,
        location=location,
        movement_type=movement_type,
        quantity=quantity,
        unit_cost=batch.unit_cost if unit_cost is None else Decimal(str(unit_cost)),
        quantity_before=before,
        quantity_after=after,
        reference=reference,
        performed_by=performed_by,
        source_type=source_type,
        source_id=str(source_id) if source_id else "",
        idempotency_key=idempotency_key,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# FEFO
# ---------------------------------------------------------------------------


def allocate_fefo(product, quantity, division):
    """Return ``[(batch, qty), ...]`` using First-Expiry-First-Out.

    Batches without an expiry date are used only after dated batches. Expired,
    quarantined and damaged batches are never allocated.
    """
    quantity = int(quantity)
    if quantity <= 0:
        raise StockError("Quantity must be positive.")
    _require_division(product, division, "Product")
    today = timezone.localdate()
    batches = (
        ProductBatch.objects.filter(
            product=product,
            business_unit=division,
            status=ProductBatch.STATUS_USABLE,
            quantity_remaining__gt=0,
        )
        .filter(Q(expiry_date__isnull=True) | Q(expiry_date__gte=today))
        .order_by(F("expiry_date").asc(nulls_last=True), "received_at", "id")
    )
    allocations = []
    remaining = quantity
    for batch in batches:
        if remaining <= 0:
            break
        take = min(batch.quantity_remaining, remaining)
        allocations.append((batch, take))
        remaining -= take
    if remaining > 0:
        raise StockError(
            f"Insufficient usable stock for {product.name}: "
            f"short by {remaining} {product.unit}."
        )
    return allocations


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------


@transaction.atomic
def post_receipt(*, division, location, reference, lines, received_by=None,
                 supplier=None, notes="", idempotency_key="", purchase_order=None):
    """Post a goods receipt atomically and idempotently.

    ``lines`` items: ``product``, ``quantity``, ``batch_number``, optional
    ``expiry_date``, ``unit_cost``, ``lot_number``.

    Returns ``(receipt, created)``. A replay of the same reference/key returns
    the original receipt with ``created=False`` and never increases stock twice.
    """
    reference = (reference or "").strip()
    if not reference:
        raise StockError("A receipt reference is required.")
    _require_division(location, division, "Receipt location")
    if supplier is not None:
        _require_division(supplier, division, "Receipt supplier")
    if purchase_order is not None:
        _require_division(purchase_order, division, "Purchase order")

    existing = StockReceipt.objects.filter(reference=reference).first()
    if existing is None and idempotency_key:
        existing = StockReceipt.objects.filter(
            business_unit=division, idempotency_key=idempotency_key
        ).first()
    if existing is not None:
        if existing.business_unit_id != division.pk:
            raise DivisionMismatch("Receipt reference belongs to another division.")
        return existing, False

    if not lines:
        raise StockError("At least one receipt line is required.")

    receipt = StockReceipt.objects.create(
        reference=reference,
        business_unit=division,
        location=location,
        supplier=supplier,
        purchase_order=purchase_order,
        received_by=received_by,
        idempotency_key=idempotency_key or "",
        notes=notes,
        posted_at=timezone.now(),
    )

    for line in lines:
        product = line["product"]
        quantity = int(line["quantity"])
        if quantity <= 0:
            raise StockError("Receipt quantity must be positive.")
        _require_division(product, division, "Receipt product")
        batch_number = (line.get("batch_number") or "").strip()
        if not batch_number:
            raise StockError("A batch number is required for every receipt line.")
        unit_cost = Decimal(str(line.get("unit_cost") or 0))
        expiry = line.get("expiry_date")

        receipt_line = StockReceiptLine.objects.create(
            receipt=receipt,
            product=product,
            batch_number=batch_number,
            lot_number=line.get("lot_number", ""),
            expiry_date=expiry,
            quantity=quantity,
            unit_cost=unit_cost,
        )

        batch = (
            ProductBatch.objects.select_for_update()
            .filter(business_unit=division, product=product, batch_number=batch_number)
            .first()
        )
        if batch is None:
            batch = ProductBatch(
                product=product,
                business_unit=division,
                supplier=supplier,
                location=location,
                batch_number=batch_number,
                lot_number=line.get("lot_number", ""),
                expiry_date=expiry,
                quantity_received=quantity,
                quantity_remaining=quantity,
                unit_cost=unit_cost,
                received_reference=reference,
            )
            batch.save()
            before, after = 0, quantity
        else:
            if expiry and batch.expiry_date and expiry != batch.expiry_date:
                raise StockError(
                    f"Batch {batch_number} already exists with expiry {batch.expiry_date}."
                )
            before = batch.quantity_remaining
            after = before + quantity
            ProductBatch.objects.filter(pk=batch.pk).update(
                quantity_received=F("quantity_received") + quantity,
                quantity_remaining=F("quantity_remaining") + quantity,
                unit_cost=unit_cost,
                supplier=supplier or batch.supplier,
                location=location,
            )
            batch.refresh_from_db()

        _write_movement(
            batch,
            division,
            StockMovement.TYPE_RECEIPT,
            quantity,
            before,
            after,
            location=location,
            reference=reference,
            performed_by=received_by,
            unit_cost=unit_cost,
            source_type="stock_receipt",
            source_id=receipt.pk,
            notes=receipt_line.lot_number,
        )

    if purchase_order is not None:
        _apply_receipt_to_purchase_order(purchase_order, lines)

    from .models import LowStockAlert

    LowStockAlert.resolve_expired()
    return receipt, True


def post_receipt_line(receipt, line):
    """Compatibility helper for the legacy ``StockReceiptLine.process`` API."""
    return post_receipt(
        division=receipt.business_unit,
        location=receipt.location,
        reference=receipt.reference,
        lines=[{
            "product": line.product,
            "quantity": line.quantity,
            "batch_number": line.batch_number,
            "lot_number": line.lot_number,
            "expiry_date": line.expiry_date,
            "unit_cost": line.unit_cost,
        }],
        received_by=receipt.received_by,
        supplier=receipt.supplier,
        notes=receipt.notes,
    )


def _apply_receipt_to_purchase_order(purchase_order, lines):
    by_product = {}
    for line in lines:
        by_product[line["product"].pk] = by_product.get(line["product"].pk, 0) + int(
            line["quantity"]
        )
    for po_line in purchase_order.lines.select_related("product"):
        received = by_product.get(po_line.product_id, 0)
        if received:
            po_line.received_quantity = min(
                po_line.quantity, po_line.received_quantity + received
            )
            po_line.save(update_fields=["received_quantity"])
    if purchase_order.lines.exists() and not purchase_order.lines.filter(
        received_quantity__lt=F("quantity")
    ).exists():
        purchase_order.status = PurchaseOrder.STATUS_RECEIVED
    elif purchase_order.lines.filter(received_quantity__gt=0).exists():
        purchase_order.status = PurchaseOrder.STATUS_PARTIAL
    purchase_order.save(update_fields=["status"])


# ---------------------------------------------------------------------------
# Issues / consumption
# ---------------------------------------------------------------------------


@transaction.atomic
def post_issue(*, division, department, reference, lines, issued_by=None,
               notes="", idempotency_key="", location=None):
    """Post a stock issue/consumption document.

    Each line may specify an explicit ``product_batch`` or a ``product`` to be
    allocated by FEFO. Returns ``(issue, created)``.
    """
    reference = (reference or "").strip()
    if not reference:
        raise StockError("An issue reference is required.")
    _require_division(department, division, "Issue department")
    if location is not None:
        _require_division(location, division, "Issue location")

    existing = StockIssue.objects.filter(reference=reference).first()
    if existing is None and idempotency_key:
        existing = StockIssue.objects.filter(
            business_unit=division, idempotency_key=idempotency_key
        ).first()
    if existing is not None:
        if existing.business_unit_id != division.pk:
            raise DivisionMismatch("Issue reference belongs to another division.")
        return existing, False

    if not lines:
        raise StockError("At least one issue line is required.")

    issue = StockIssue.objects.create(
        reference=reference,
        business_unit=division,
        department=department,
        location=location,
        issued_by=issued_by,
        idempotency_key=idempotency_key or "",
        notes=notes,
    )

    for line in lines:
        quantity = int(line["quantity"])
        if quantity <= 0:
            raise StockError("Issue quantity must be positive.")
        if line.get("product_batch") is not None:
            batch = _lock_batch(line["product_batch"].pk)
            _require_division(batch, division, "Issue batch")
            _require_division(batch.product, division, "Issue batch product")
            allocations = [(batch, quantity)]
        else:
            product = line.get("product")
            if product is None:
                raise StockError("Each issue line needs a batch or a product.")
            _require_division(product, division, "Issue product")
            allocations = allocate_fefo(product, quantity, division)

        for batch, take in allocations:
            before = batch.quantity_remaining
            try:
                remaining = batch.issue(take)
            except ValueError as exc:
                raise StockError(str(exc))
            after = before - take
            StockIssueLine.objects.create(
                issue=issue, product_batch=batch, quantity=take
            )
            _write_movement(
                batch,
                division,
                StockMovement.TYPE_ISSUE,
                -take,
                before,
                after,
                location=location or issue.location,
                reference=reference,
                performed_by=issued_by,
                unit_cost=batch.unit_cost,
                source_type="stock_issue",
                source_id=issue.pk,
            )

    from .models import LowStockAlert

    LowStockAlert.check_and_create()
    return issue, True


def post_issue_line(issue, line):
    """Compatibility helper for the legacy ``StockIssue.process`` API."""
    return post_issue(
        division=issue.business_unit,
        department=issue.department,
        reference=issue.reference,
        lines=[{"product_batch": line.product_batch, "quantity": line.quantity}],
        issued_by=issue.issued_by,
        notes=issue.notes,
        location=issue.location,
    )


# ---------------------------------------------------------------------------
# Adjustments / counts / transfers
# ---------------------------------------------------------------------------


@transaction.atomic
def post_adjustment(*, division, reference, reason, lines, requested_by=None,
                    approve=False, approved_by=None):
    """Create (and optionally approve) a controlled stock adjustment."""
    if StockAdjustment.objects.filter(reference=reference).exists():
        raise StockError("An adjustment with this reference already exists.")
    if not lines:
        raise StockError("At least one adjustment line is required.")
    adjustment = StockAdjustment.objects.create(
        reference=reference,
        business_unit=division,
        reason=reason,
        requested_by=requested_by,
        status=StockAdjustment.STATUS_DRAFT,
    )
    for line in lines:
        batch = _lock_batch(line["product_batch"].pk)
        _require_division(batch, division, "Adjustment batch")
        delta = int(line["quantity_delta"])
        if delta == 0:
            raise StockError("Adjustment delta cannot be zero.")
        if batch.quantity_remaining + delta < 0:
            raise StockError(
                f"Adjustment would make {batch.batch_number} negative."
            )
        StockAdjustmentLine.objects.create(
            adjustment=adjustment,
            product_batch=batch,
            quantity_delta=delta,
            notes=line.get("notes", ""),
        )
    if approve:
        adjustment = approve_adjustment(
            adjustment, approved_by=approved_by or requested_by
        )
    return adjustment


@transaction.atomic
def approve_adjustment(adjustment, approved_by=None):
    """Approve and post an adjustment exactly once."""
    locked = StockAdjustment.objects.select_for_update().get(pk=adjustment.pk)
    if locked.status != StockAdjustment.STATUS_DRAFT:
        raise StockError("Only draft adjustments can be approved.")
    for line in locked.lines.select_related("product_batch"):
        batch = _lock_batch(line.product_batch_id)
        delta = line.quantity_delta
        before = batch.quantity_remaining
        after = before + delta
        if after < 0:
            raise StockError(f"Adjustment would make {batch.batch_number} negative.")
        ProductBatch.objects.filter(pk=batch.pk).update(
            quantity_remaining=F("quantity_remaining") + delta
        )
        batch.refresh_from_db(fields=["quantity_remaining"])
        movement_type = (
            StockMovement.TYPE_DAMAGE if delta < 0 else StockMovement.TYPE_ADJUSTMENT
        )
        _write_movement(
            batch,
            locked.business_unit,
            movement_type,
            delta,
            before,
            after,
            location=batch.location,
            reference=locked.reference,
            performed_by=approved_by,
            source_type="stock_adjustment",
            source_id=locked.pk,
            notes=locked.reason,
        )
    locked.status = StockAdjustment.STATUS_APPROVED
    locked.approved_by = approved_by
    locked.approved_at = timezone.now()
    locked.save(update_fields=["status", "approved_by", "approved_at"])
    from .models import LowStockAlert

    LowStockAlert.check_and_create()
    return locked


@transaction.atomic
def post_stock_count(count, counted_by=None):
    """Post a stock count, generating an approved adjustment for variances."""
    count = StockCount.objects.select_for_update().get(pk=count.pk)
    if count.status == StockCount.STATUS_POSTED:
        raise StockError("This stock count has already been posted.")
    adjustments = []
    for line in count.lines.select_related("product_batch"):
        variance = line.counted_quantity - line.system_quantity
        if variance:
            adjustments.append({
                "product_batch": line.product_batch,
                "quantity_delta": variance,
                "notes": f"Count {count.reference}",
            })
    if adjustments:
        post_adjustment(
            division=count.business_unit,
            reference=f"ADJ-{count.reference}",
            reason=f"Stock count {count.reference}",
            lines=adjustments,
            requested_by=counted_by,
            approve=True,
            approved_by=counted_by,
        )
    count.status = StockCount.STATUS_POSTED
    count.counted_by = counted_by
    count.save(update_fields=["status", "counted_by"])
    return count


@transaction.atomic
def post_transfer(*, division, reference, from_location, to_location, lines,
                  transferred_by=None, notes=""):
    if StockTransfer.objects.filter(reference=reference).exists():
        raise StockError("A transfer with this reference already exists.")
    _require_division(from_location, division, "Transfer source")
    _require_division(to_location, division, "Transfer destination")
    if from_location.pk == to_location.pk:
        raise StockError("Source and destination locations must differ.")
    transfer = StockTransfer.objects.create(
        reference=reference,
        business_unit=division,
        from_location=from_location,
        to_location=to_location,
        transferred_by=transferred_by,
        notes=notes,
    )
    for line in lines:
        batch = _lock_batch(line["product_batch"].pk)
        _require_division(batch, division, "Transfer batch")
        quantity = int(line["quantity"])
        before = batch.quantity_remaining
        try:
            remaining = batch.issue(quantity)
        except ValueError as exc:
            raise StockError(str(exc))
        StockTransferLine.objects.create(
            transfer=transfer, product_batch=batch, quantity=quantity
        )
        _write_movement(
            batch, division, StockMovement.TYPE_TRANSFER_OUT, -quantity,
            before, remaining, location=from_location, reference=reference,
            performed_by=transferred_by, source_type="stock_transfer",
            source_id=transfer.pk,
        )
        _write_movement(
            batch, division, StockMovement.TYPE_TRANSFER_IN, quantity,
            remaining, remaining + quantity, location=to_location,
            reference=reference, performed_by=transferred_by,
            source_type="stock_transfer", source_id=transfer.pk,
        )
    return transfer


def record_sale(*, division, reference, batch, quantity, performed_by=None,
                location=None, idempotency_key=""):
    """Deduct stock for an authorized pharmacy/resort sale. Idempotent by key."""
    quantity = int(quantity)
    with transaction.atomic():
        if idempotency_key and StockMovement.objects.filter(
            business_unit=division, idempotency_key=idempotency_key
        ).exists():
            return False
        locked = _lock_batch(batch.pk)
        _require_division(locked, division, "Sale batch")
        before = locked.quantity_remaining
        try:
            remaining = locked.issue(quantity)
        except ValueError as exc:
            raise StockError(str(exc))
        _write_movement(
            locked, division, StockMovement.TYPE_SALE, -quantity,
            before, remaining, location=location, reference=reference,
            performed_by=performed_by, source_type="sale",
            idempotency_key=idempotency_key,
        )
        return True
