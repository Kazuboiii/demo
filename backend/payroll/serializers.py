from rest_framework import serializers

from .models import PayrollLine, PayrollRun, SalaryStructure


def _check_division(serializer, division):
    request = serializer.context.get("request")
    user = getattr(request, "user", None)
    if user is not None and division is not None and not user.can_access_business_unit(division):
        raise serializers.ValidationError(
            "You are not authorized for this business division."
        )


class SalaryStructureSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    employee_code = serializers.ReadOnlyField(source="employee.employee_id")
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")
    gross = serializers.ReadOnlyField()

    class Meta:
        model = SalaryStructure
        fields = [
            "id", "employee", "employee_code", "employee_name", "business_unit",
            "business_unit_name", "currency", "basic_salary", "housing_allowance",
            "transport_allowance", "other_allowance", "tax_rate_percent",
            "other_deduction", "gross", "effective_from", "is_active", "updated_at",
        ]
        read_only_fields = ["updated_at"]

    def get_employee_name(self, obj):
        return obj.employee.user.get_full_name() or obj.employee.user.email

    def validate(self, attrs):
        division = attrs.get("business_unit", getattr(self.instance, "business_unit", None))
        _check_division(self, division)
        employee = attrs.get("employee", getattr(self.instance, "employee", None))
        if employee is not None and division is not None and employee.business_unit_id != division.pk:
            raise serializers.ValidationError(
                "The employee must belong to the salary structure division."
            )
        return attrs


class PayrollLineSerializer(serializers.ModelSerializer):
    employee_code = serializers.ReadOnlyField(source="employee.employee_id")
    employee_name = serializers.SerializerMethodField()

    class Meta:
        model = PayrollLine
        fields = [
            "id", "employee", "employee_code", "employee_name", "basic_salary",
            "allowances", "deductions", "gross", "net", "days_present", "notes",
        ]

    def get_employee_name(self, obj):
        return obj.employee.user.get_full_name() or obj.employee.user.email


class PayrollRunSerializer(serializers.ModelSerializer):
    lines = PayrollLineSerializer(many=True, read_only=True)
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")
    total_gross = serializers.ReadOnlyField()
    total_net = serializers.ReadOnlyField()
    employee_count = serializers.SerializerMethodField()

    class Meta:
        model = PayrollRun
        fields = [
            "id", "reference", "business_unit", "business_unit_name",
            "period_start", "period_end", "status", "currency", "created_by",
            "approved_by", "created_at", "total_gross", "total_net",
            "employee_count", "lines",
        ]
        read_only_fields = [
            "created_by", "approved_by", "created_at", "status", "reference",
        ]

    def get_employee_count(self, obj):
        return obj.lines.count()
