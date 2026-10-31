from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("core.urls")),
    path("api/v1/attendance/", include("attendance.urls")),
    path("api/v1/inventory/", include("inventory.urls")),
    path("api/v1/fleet/", include("fleet.urls")),
    path("api/v1/nemt/", include("nemt.urls")),
    path("api/v1/medicine-delivery/", include("medicine_delivery.urls")),
    path("api/v1/payroll/", include("payroll.urls")),
    path("api/v1/reports/", include("reports.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
