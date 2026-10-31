from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import PayrollRunViewSet, SalaryStructureViewSet

router = DefaultRouter()
router.register(r"salary-structures", SalaryStructureViewSet)
router.register(r"runs", PayrollRunViewSet)

urlpatterns = [path("", include(router.urls))]
