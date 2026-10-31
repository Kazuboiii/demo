from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    GoodsReceiptViewSet,
    LocationViewSet,
    ProductBatchViewSet,
    ProductViewSet,
    PurchaseOrderViewSet,
    StockAdjustmentViewSet,
    StockCountViewSet,
    StockIssueViewSet,
    StockMovementViewSet,
    StockReceiptViewSet,
    StockTransferViewSet,
    SupplierViewSet,
    WorkspaceViewSet,
)

router = DefaultRouter()
router.register(r"workspaces", WorkspaceViewSet, basename="inventory-workspace")
router.register(r"locations", LocationViewSet)
router.register(r"suppliers", SupplierViewSet)
router.register(r"products", ProductViewSet)
router.register(r"batches", ProductBatchViewSet)
router.register(r"receipts", StockReceiptViewSet)
router.register(r"goods-receipts", GoodsReceiptViewSet, basename="goods-receipt")
router.register(r"issues", StockIssueViewSet)
router.register(r"transfers", StockTransferViewSet)
router.register(r"movements", StockMovementViewSet)
router.register(r"adjustments", StockAdjustmentViewSet)
router.register(r"stock-counts", StockCountViewSet)
router.register(r"purchase-orders", PurchaseOrderViewSet)

urlpatterns = [path("", include(router.urls))]
