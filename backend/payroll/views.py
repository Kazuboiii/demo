from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from core.permissions import (
    ModulePermission,
    accessible_divisions,
    requested_division,
    role_can,
    scoped_queryset,
)

from . import services
from .models import PayrollRun, SalaryStructure
from .serializers import PayrollRunSerializer, SalaryStructureSerializer


def _scoped(qs, request):
    unit, error = requested_division(request.user, request)
    if error is not None:
        raise PermissionDenied(error.data.get("detail", "Not authorized."))
    if unit is not None:
        return qs.filter(business_unit=unit)
    return scoped_queryset(qs, request.user)


def _parse_date(value, label):
    from datetime import date

    if not value:
        raise ValidationError(f"{label} is required.")
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ValidationError(f"{label} must be an ISO date (YYYY-MM-DD).")


class SalaryStructureViewSet(viewsets.ModelViewSet):
    queryset = SalaryStructure.objects.all().select_related(
        "employee__user", "business_unit"
    )
    serializer_class = SalaryStructureSerializer
    permission_classes = [ModulePermission]
    module = "payroll"

    def get_queryset(self):
        return _scoped(super().get_queryset(), self.request)


class PayrollRunViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PayrollRun.objects.all().select_related(
        "business_unit", "created_by", "approved_by"
    ).prefetch_related("lines__employee__user")
    serializer_class = PayrollRunSerializer
    permission_classes = [ModulePermission]
    module = "payroll"

    def get_queryset(self):
        qs = _scoped(super().get_queryset(), self.request)
        start = self.request.query_params.get("start")
        end = self.request.query_params.get("end")
        if start:
            qs = qs.filter(period_end__gte=start)
        if end:
            qs = qs.filter(period_start__lte=end)
        return qs

    @action(detail=False, methods=["post"])
    def calculate(self, request):
        if not role_can(request.user, "payroll", "create"):
            raise PermissionDenied("You do not have payroll creation permission.")
        division, error = requested_division(request.user, request)
        if error is not None:
            raise PermissionDenied(error.data.get("detail", "Not authorized."))
        if division is None:
            divisions = list(accessible_divisions(request.user)[:2])
            if len(divisions) != 1:
                raise ValidationError(
                    "Select one business division before running payroll."
                )
            division = divisions[0]
        period_start = _parse_date(request.data.get("period_start"), "period_start")
        period_end = _parse_date(request.data.get("period_end"), "period_end")
        try:
            run, created = services.calculate_payroll(
                division=division,
                period_start=period_start,
                period_end=period_end,
                created_by=request.user,
                reference=request.data.get("reference", ""),
            )
        except services.PayrollError as exc:
            raise ValidationError(str(exc))
        data = self.get_serializer(run, context={"request": request}).data
        return Response(data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        if not role_can(request.user, "payroll", "approve"):
            raise PermissionDenied("You do not have payroll approval permission.")
        run = self.get_object()
        if run.status != PayrollRun.STATUS_DRAFT:
            return Response({"detail": "Only draft payroll runs can be approved."}, status=400)
        run.status = PayrollRun.STATUS_APPROVED
        run.approved_by = request.user
        run.save(update_fields=["status", "approved_by"])
        return Response(self.get_serializer(run, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def mark_paid(self, request, pk=None):
        if not role_can(request.user, "payroll", "approve"):
            raise PermissionDenied("You do not have payroll approval permission.")
        run = self.get_object()
        if run.status != PayrollRun.STATUS_APPROVED:
            return Response({"detail": "Approve the payroll run before marking it paid."}, status=400)
        run.status = PayrollRun.STATUS_PAID
        run.save(update_fields=["status"])
        return Response(self.get_serializer(run, context={"request": request}).data)
