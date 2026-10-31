from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import RideCostEstimateViewSet, TransportRequestViewSet, TripViewSet

router = DefaultRouter()
router.register(r"requests", TransportRequestViewSet)
router.register(r"trips", TripViewSet)
router.register(r"cost-estimates", RideCostEstimateViewSet)

urlpatterns = [path("", include(router.urls))]
