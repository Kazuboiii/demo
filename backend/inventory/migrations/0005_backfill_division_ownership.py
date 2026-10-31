"""Backfill division ownership for pre-existing inventory records.

Ownership is derived from the verified ``product.business_unit`` relationship
only. Records that cannot be resolved are left unowned (NULL) and are listed
for manual review by the ``audit_inventory_ownership`` management command; the
following migration refuses to run if any remain.
"""

from django.db import migrations


def backfill(apps, schema_editor):
    ProductBatch = apps.get_model("inventory", "ProductBatch")
    StockMovement = apps.get_model("inventory", "StockMovement")
    StockReceipt = apps.get_model("inventory", "StockReceipt")
    StockIssue = apps.get_model("inventory", "StockIssue")
    StockTransfer = apps.get_model("inventory", "StockTransfer")

    for batch in ProductBatch.objects.select_related("product").iterator():
        if batch.business_unit_id is None and batch.product_id:
            batch.business_unit_id = batch.product.business_unit_id
            batch.save(update_fields=["business_unit"])

    for movement in StockMovement.objects.select_related(
        "product_batch", "product_batch__product"
    ).iterator():
        if movement.business_unit_id is None and movement.product_batch_id:
            movement.business_unit_id = movement.product_batch.business_unit_id
            movement.save(update_fields=["business_unit"])

    # Existing headers already carry an explicit business_unit. Mark them as
    # posted so the new status field is meaningful.
    StockReceipt.objects.filter(posted_at__isnull=True).update(status="posted")
    for model in (StockReceipt, StockIssue, StockTransfer):
        for row in model.objects.all().iterator():
            model.objects.filter(pk=row.pk, business_unit__isnull=True).update(
                business_unit_id=row.business_unit_id
            )


def unbackfill(apps, schema_editor):
    # Ownership is authoritative; nothing to reverse safely.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0004_purchaseorder_purchaseorderline_stockadjustment_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
