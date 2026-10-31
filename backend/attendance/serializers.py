from rest_framework import serializers

from core.models import Employee, User
from core.serializers import UserSerializer

from .models import (
    AttendanceEvent,
    LeaveRequest,
    OneTimeQRToken,
    RotatingQRToken,
    Shift,
    AttendanceCorrectionRequest,
)


class ShiftSerializer(serializers.ModelSerializer):
    class Meta:
        model = Shift
        fields = [
            "id",
            "name",
            "business_unit",
            "start_time",
            "end_time",
            "overnight",
            "grace_minutes",
            "is_active",
            "created_at",
        ]


class AttendanceEventSerializer(serializers.ModelSerializer):
    employee_id = serializers.ReadOnlyField(source="employee.employee_id")
    employee_name = serializers.SerializerMethodField()
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")
    shift_name = serializers.ReadOnlyField(source="shift.name", default=None)

    class Meta:
        model = AttendanceEvent
        fields = [
            "id",
            "employee",
            "employee_id",
            "employee_name",
            "business_unit",
            "business_unit_name",
            "shift",
            "shift_name",
            "action",
            "timestamp",
            "source",
            "notes",
            "created_at",
        ]
        read_only_fields = ["employee_id", "employee_name", "created_at"]

    def get_employee_name(self, obj):
        return obj.employee.user.get_full_name() or obj.employee.user.email


class RotatingQRTokenSerializer(serializers.ModelSerializer):
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")
    seconds_remaining = serializers.SerializerMethodField()
    expired = serializers.SerializerMethodField()
    qr_data = serializers.SerializerMethodField()

    class Meta:
        model = RotatingQRToken
        fields = [
            "id",
            "token",
            "business_unit",
            "business_unit_name",
            "action",
            "issued_at",
            "expires_at",
            "is_active",
            "seconds_remaining",
            "expired",
            "qr_data",
            "created_at",
        ]

    def get_seconds_remaining(self, obj):
        from django.utils import timezone

        remaining = int((obj.expires_at - timezone.now()).total_seconds())
        return max(0, remaining)

    def get_expired(self, obj):
        return obj.is_expired()

    def get_qr_data(self, obj):
        # The payload encoded in the QR: signed-ish short-lived token reference.
        # Never contains employee IDs or predictable data.
        return {
            "token": obj.token,
            "action": obj.action,
            "expires_at": obj.expires_at.isoformat(),
        }


class RotatingQRCurrentSerializer(serializers.Serializer):
    token = RotatingQRTokenSerializer(read_only=True)


class RotatingQRVerifySerializer(serializers.Serializer):
    token = serializers.CharField()
    action = serializers.ChoiceField(
        choices=AttendanceEvent.ACTION_CHOICES, required=False
    )


class OneTimeQRTokenSerializer(serializers.ModelSerializer):
    employee_id = serializers.ReadOnlyField(source="employee.employee_id")
    employee_name = serializers.SerializerMethodField()
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")
    issued_by_name = serializers.ReadOnlyField(source="issued_by.email", default=None)

    class Meta:
        model = OneTimeQRToken
        fields = [
            "id",
            "token",
            "employee",
            "employee_id",
            "employee_name",
            "business_unit",
            "business_unit_name",
            "action",
            "issued_by",
            "issued_by_name",
            "expires_at",
            "status",
            "redeemed_at",
            "created_at",
        ]
        read_only_fields = ["token", "status", "redeemed_at", "created_at"]

    def get_employee_name(self, obj):
        return obj.employee.user.get_full_name() or obj.employee.user.email


class OneTimeQRGenerateSerializer(serializers.Serializer):
    employee = serializers.PrimaryKeyRelatedField(queryset=Employee.objects.all())
    action = serializers.ChoiceField(choices=AttendanceEvent.ACTION_CHOICES)
    validity_minutes = serializers.IntegerField(default=5, min_value=1, max_value=1440)


class OneTimeQRRevokeSerializer(serializers.Serializer):
    pass


class LeaveRequestSerializer(serializers.ModelSerializer):
    employee_id = serializers.ReadOnlyField(source="employee.employee_id")
    employee_name = serializers.SerializerMethodField()

    class Meta:
        model = LeaveRequest
        fields = [
            "id",
            "employee",
            "employee_id",
            "employee_name",
            "start_date",
            "end_date",
            "reason",
            "status",
            "reviewed_by",
            "reviewed_at",
            "created_at",
        ]
        read_only_fields = ["status", "reviewed_by", "reviewed_at", "created_at"]

    def get_employee_name(self, obj):
        return obj.employee.user.get_full_name() or obj.employee.user.email


class AttendanceCorrectionRequestSerializer(serializers.ModelSerializer):
    employee_id = serializers.ReadOnlyField(source="employee.employee_id")
    employee_name = serializers.SerializerMethodField()

    class Meta:
        model = AttendanceCorrectionRequest
        fields = [
            "id",
            "employee",
            "employee_id",
            "employee_name",
            "event",
            "requested_timestamp",
            "requested_action",
            "reason",
            "status",
            "reviewed_by",
            "reviewed_at",
            "created_at",
        ]
        read_only_fields = ["status", "reviewed_by", "reviewed_at", "created_at"]

    def get_employee_name(self, obj):
        return obj.employee.user.get_full_name() or obj.employee.user.email
