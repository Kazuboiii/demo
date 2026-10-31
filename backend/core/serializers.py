from rest_framework import serializers

from .models import BusinessUnit, Department, Employee, Role, User


class BusinessUnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessUnit
        fields = ["id", "name", "code", "is_active", "created_at"]


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["id", "name", "code", "business_unit", "is_active", "created_at"]


class DepartmentSerializer(serializers.ModelSerializer):
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")

    class Meta:
        model = Department
        fields = ["id", "name", "business_unit", "business_unit_name", "is_active", "created_at"]


class UserSerializer(serializers.ModelSerializer):
    role_code = serializers.ReadOnlyField()
    business_unit_code = serializers.ReadOnlyField()
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name", default=None)
    role_name = serializers.ReadOnlyField(source="role.name", default=None)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "phone",
            "role",
            "role_name",
            "role_code",
            "business_unit",
            "business_unit_name",
            "business_unit_code",
            "is_active",
            "is_approved",
            "is_staff",
            "created_at",
        ]
        read_only_fields = ["role_code", "business_unit_code"]


class EmployeeSerializer(serializers.ModelSerializer):
    user_email = serializers.ReadOnlyField(source="user.email")
    user_name = serializers.SerializerMethodField()
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")
    department_name = serializers.ReadOnlyField(source="department.name", default=None)

    class Meta:
        model = Employee
        fields = [
            "id",
            "employee_id",
            "user",
            "user_email",
            "user_name",
            "business_unit",
            "business_unit_name",
            "department",
            "department_name",
            "designation",
            "hire_date",
            "is_active",
            "created_at",
        ]

    def get_user_name(self, obj):
        return obj.user.get_full_name() or obj.user.email
