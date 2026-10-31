from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import DeliveryRequestViewSet

router = DefaultRouter()
router.register(r"requests", DeliveryRequestViewSet)

urlpatterns = [path("", include(router.urls))]
