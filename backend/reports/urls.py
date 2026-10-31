from django.urls import path

from .views import (
    AttendanceReportView,
    DashboardView,
    FleetReportView,
    InventoryReportView,
    ReportCatalogView,
    ReportExportView,
    ReportRunView,
)

urlpatterns = [
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("catalog/", ReportCatalogView.as_view(), name="report-catalog"),
    path("run/<str:key>/", ReportRunView.as_view(), name="report-run"),
    path("export/<str:key>/", ReportExportView.as_view(), name="report-export"),
    # Backwards-compatible summary endpoints.
    path("attendance/", AttendanceReportView.as_view(), name="report-attendance"),
    path("inventory/", InventoryReportView.as_view(), name="report-inventory"),
    path("fleet/", FleetReportView.as_view(), name="report-fleet"),
]
