"""
Attendance and QR attendance views.

QR verification is backend-driven: the browser clock is never trusted.
"""

from datetime import timedelta
from functools import wraps

from django.db import OperationalError, connection, transaction
from django.db.models import F
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

import secrets

from core.models import BusinessUnit, Employee
from core.permissions import BusinessUnitScoped, IsAuthenticatedActive, RolePermission

from .models import (
    AttendanceEvent,
    LeaveRequest,
    OneTimeQRToken,
    RotatingQRRedemption,
    RotatingQRToken,
    Shift,
    AttendanceCorrectionRequest,
)
from .serializers import (
    AttendanceEventSerializer,
    LeaveRequestSerializer,
    OneTimeQRGenerateSerializer,
    OneTimeQRRevokeSerializer,
    OneTimeQRTokenSerializer,
    RotatingQRTokenSerializer,
    RotatingQRVerifySerializer,
    ShiftSerializer,
    AttendanceCorrectionRequestSerializer,
)


def _attendance_write(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except OperationalError as exc:
            if connection.vendor != "sqlite" or "locked" not in str(exc).lower():
                raise
            return Response(
                {"detail": "Attendance is busy. Check your history before retrying.", "code": "attendance_busy"},
                status=503, headers={"Retry-After": "1"},
            )
    return wrapped


def _employee_for_user(user):
    try:
        return Employee.objects.select_related("business_unit", "user").get(user=user, is_active=True)
    except Employee.DoesNotExist:
        return None


def _active_check_in_exists(employee):
    """True if the employee has a check-in without a later check-out."""
    last = AttendanceEvent.objects.filter(employee=employee).order_by("-timestamp", "-pk").first()
    return last is not None and last.action == AttendanceEvent.ACTION_CHECK_IN


class ShiftViewSet(viewsets.ModelViewSet):
    queryset = Shift.objects.all().order_by("business_unit__name", "name")
    serializer_class = ShiftSerializer
    permission_classes = [BusinessUnitScoped]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user or not user.is_authenticated:
            return qs.none()
        if user.is_superuser or user.has_role("super_admin"):
            return qs
        return qs.filter(business_unit=user.business_unit)


class AttendanceEventViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AttendanceEvent.objects.all().order_by("-timestamp", "-created_at")
    serializer_class = AttendanceEventSerializer
    permission_classes = [BusinessUnitScoped]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user or not user.is_authenticated:
            return qs.none()
        if user.is_superuser or user.has_role("super_admin"):
            return qs
        return qs.filter(business_unit=user.business_unit)

    @action(detail=False, methods=["get"])
    def mine(self, request):
        employee = _employee_for_user(request.user)
        qs = self.get_queryset()
        if employee:
            qs = qs.filter(employee=employee)
        else:
            qs = qs.none()
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)


class RotatingQRViewSet(viewsets.ViewSet):
    """
    Rotating (shared workplace) QR endpoints.

    GET  /qr/rotating/current/?business_unit=<id>&action=check_in
    POST /qr/rotating/verify/   {token, action?}
    """

    permission_classes = [IsAuthenticatedActive, BusinessUnitScoped]

    def list(self, request):
        """Current active rotating token for a workplace + action."""
        bu_id = request.query_params.get("business_unit")
        action = request.query_params.get("action", AttendanceEvent.ACTION_CHECK_IN)
        now = timezone.now()
        if action not in dict(AttendanceEvent.ACTION_CHOICES):
            return Response({"detail": "Invalid attendance action."}, status=400)

        if bu_id:
            try:
                bu = BusinessUnit.objects.get(pk=bu_id)
            except (BusinessUnit.DoesNotExist, ValueError, TypeError):
                return Response({"detail": "Business unit not found."}, status=404)
            if not request.user.can_access_business_unit(bu):
                return Response({"detail": "Not authorized for this unit."}, status=403)
        else:
            bu = request.user.business_unit

        if bu is None:
            return Response({"detail": "No business unit context."}, status=400)

        token = RotatingQRToken.current_for(bu, action, now=now)
        serializer = RotatingQRTokenSerializer(token, context={"request": request})
        return Response(serializer.data)

    @action(detail=False, methods=["post"])
    @_attendance_write
    def verify(self, request):
        ser = RotatingQRVerifySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        token = ser.validated_data["token"]
        action = ser.validated_data.get("action", AttendanceEvent.ACTION_CHECK_IN)
        now = timezone.now()

        employee = _employee_for_user(request.user)
        if employee is None:
            return Response({"detail": "No employee record for this user."}, status=400)

        try:
            qr = RotatingQRToken.objects.get(token=token)
        except RotatingQRToken.DoesNotExist:
            # An explicit discriminator, never a generic route/resource 404.
            one_time = OneTimeQRToken.objects.filter(
                token=token, employee=employee, business_unit=employee.business_unit
            ).exists()
            return Response({"detail": "Invalid rotating QR token.",
                             "code": "one_time_token" if one_time else "invalid_token"}, status=404)

        if not request.user.can_access_business_unit(qr.business_unit):
            return Response({"detail": "Not authorized for this workplace."}, status=403)
        if qr.is_expired(now=now):
            return Response({"detail": "QR code has expired."}, status=410)
        if qr.action != action:
            return Response({"detail": "QR action mismatch."}, status=400)
        if qr.business_unit_id != employee.business_unit_id:
            return Response({"detail": "Employee not assigned to this workplace."}, status=403)

        with transaction.atomic():
            # A write lock also serializes SQLite, whose SELECT FOR UPDATE is a no-op.
            Employee.objects.filter(pk=employee.pk).update(is_active=F("is_active"))
            now = timezone.now()
            if qr.is_expired(now=now):
                return Response({"detail": "QR code has expired."}, status=410)
            if RotatingQRRedemption.objects.filter(token=qr, employee=employee, action=action).exists():
                return Response({"detail": "Attendance already recorded for this QR."}, status=409)
            checked_in = _active_check_in_exists(employee)
            if action == AttendanceEvent.ACTION_CHECK_IN and checked_in:
                return Response({"detail": "Employee already has an active check-in."}, status=409)
            if action == AttendanceEvent.ACTION_CHECK_OUT and not checked_in:
                return Response({"detail": "No active check-in to check out from."}, status=409)
            RotatingQRRedemption.objects.create(token=qr, employee=employee, action=action)
            event = AttendanceEvent.objects.create(
                employee=employee, business_unit=qr.business_unit, action=action,
                timestamp=now, source=AttendanceEvent.SOURCE_QR_ROTATING,
            )

        return Response(
            {
                "detail": "Attendance recorded.",
                "event": AttendanceEventSerializer(event, context={"request": request}).data,
            }
        )


class OneTimeQRTokenViewSet(viewsets.ModelViewSet):
    queryset = OneTimeQRToken.objects.all().order_by("-created_at")
    serializer_class = OneTimeQRTokenSerializer
    permission_classes = [IsAuthenticatedActive, BusinessUnitScoped]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user or not user.is_authenticated:
            return qs.none()
        if user.is_superuser or user.has_role("super_admin"):
            return qs
        qs = qs.filter(business_unit=user.business_unit)
        if not user.has_role("hr_manager"):
            qs = qs.filter(employee__user=user)
        return qs

    def perform_create(self, serializer):
        user = self.request.user
        if not user or not user.is_authenticated:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Authentication required.")
        if not (user.is_superuser or user.has_role("super_admin", "hr_manager")):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Only HR/administrators can generate one-time QR codes.")
        serializer.save(issued_by=user)

    def create(self, request, *args, **kwargs):
        ser = OneTimeQRGenerateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        employee = ser.validated_data["employee"]
        action = ser.validated_data["action"]
        minutes = ser.validated_data["validity_minutes"]

        if not request.user.can_access_business_unit(employee.business_unit):
            return Response({"detail": "Not authorized for this employee's unit."}, status=403)
        if not (request.user.is_superuser or request.user.has_role("super_admin", "hr_manager")):
            return Response({"detail": "Only HR/administrators can generate one-time QR codes."}, status=403)

        now = timezone.now()
        token_str = secrets.token_urlsafe(24)
        token = OneTimeQRToken.objects.create(
            employee=employee,
            business_unit=employee.business_unit,
            action=action,
            issued_by=request.user,
            expires_at=now + timedelta(minutes=minutes),
            status=OneTimeQRToken.STATUS_ACTIVE,
            token=token_str,
        )
        out = OneTimeQRTokenSerializer(token, context={"request": request})
        return Response(out.data, status=201)

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        if not (request.user.is_superuser or request.user.has_role("super_admin", "hr_manager")):
            return Response({"detail": "Only HR/administrators can revoke QR codes."}, status=403)
        token = self.get_object()
        if token.status != OneTimeQRToken.STATUS_ACTIVE:
            return Response({"detail": "Token is not active."}, status=400)
        if not request.user.can_access_business_unit(token.business_unit):
            return Response({"detail": "Not authorized."}, status=403)
        changed = OneTimeQRToken.objects.filter(pk=token.pk, status=OneTimeQRToken.STATUS_ACTIVE).update(
            status=OneTimeQRToken.STATUS_REVOKED
        )
        if not changed:
            return Response({"detail": "Token is not active."}, status=400)
        token.status = OneTimeQRToken.STATUS_REVOKED
        return Response({"detail": "Token revoked.", "status": token.status})

    @action(detail=False, methods=["post"])
    @_attendance_write
    def verify(self, request):
        ser = RotatingQRVerifySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        token = ser.validated_data["token"]
        action = ser.validated_data.get("action", AttendanceEvent.ACTION_CHECK_IN)
        now = timezone.now()

        employee = _employee_for_user(request.user)
        if employee is None:
            return Response({"detail": "No employee record for this user."}, status=400)

        try:
            qr = OneTimeQRToken.objects.get(token=token)
        except OneTimeQRToken.DoesNotExist:
            return Response({"detail": "Invalid QR token."}, status=404)

        if not request.user.can_access_business_unit(qr.business_unit):
            return Response({"detail": "Not authorized for this workplace."}, status=403)

        if qr.action != action:
            return Response({"detail": "QR action mismatch."}, status=400)
        ok, result = qr.redeem(employee)
        if not ok:
            messages = {
                "token-not-active": "This QR code is not active.",
                "token-expired": "This QR code has expired.",
                "wrong-employee": "This QR code was issued for another employee.",
                "wrong-workplace": "This QR code is for another workplace.",
                "already-checked-in": "Employee already has an active check-in.",
                "not-checked-in": "No active check-in to check out from.",
            }
            return Response({"detail": messages.get(result, "Verification failed.")}, status=400)

        out = OneTimeQRTokenSerializer(qr, context={"request": request})
        return Response(
            {
                "detail": "Attendance recorded.",
                "token": out.data,
                "event": AttendanceEventSerializer(
                    result,
                    context={"request": request},
                ).data,
            }
        )


class LeaveRequestViewSet(viewsets.ModelViewSet):
    queryset = LeaveRequest.objects.all().order_by("-created_at")
    serializer_class = LeaveRequestSerializer
    permission_classes = [BusinessUnitScoped]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user or not user.is_authenticated:
            return qs.none()
        if user.is_superuser or user.has_role("super_admin"):
            return qs
        return qs.filter(employee__business_unit=user.business_unit)

    def perform_create(self, serializer):
        employee = _employee_for_user(self.request.user)
        if employee is None:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("No employee record.")
        serializer.save(employee=employee)


class AttendanceCorrectionRequestViewSet(viewsets.ModelViewSet):
    queryset = AttendanceCorrectionRequest.objects.all().order_by("-created_at")
    serializer_class = AttendanceCorrectionRequestSerializer
    permission_classes = [BusinessUnitScoped]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user or not user.is_authenticated:
            return qs.none()
        if user.is_superuser or user.has_role("super_admin"):
            return qs
        return qs.filter(employee__business_unit=user.business_unit)

    def perform_create(self, serializer):
        employee = _employee_for_user(self.request.user)
        if employee is None:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("No employee record.")
        serializer.save(employee=employee)
