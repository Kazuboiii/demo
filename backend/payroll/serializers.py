from rest_framework import serializers

from .models import (
    BudgetAllocation,
    EmploymentContract,
    EmploymentHistory,
    EmployeeDocument,
    Expense,
    ExpenseCategory,
    FinancialAccount,
    FinancialTransaction,
    JournalEntry,
    JournalLine,
    LeaveBalance,
    PayrollLine,
    PayrollRun,
    PurchaseCost,
    RevenueRecord,
    SalaryStructure,
    VendorPayment,
    WorkSchedule,
)
from nemt.models import TransportationExpense


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


# ---------------------------------------------------------------------------
# HR and workforce administration serializers
# ---------------------------------------------------------------------------


class EmploymentContractSerializer(serializers.ModelSerializer):
    employee_code = serializers.ReadOnlyField(source="employee.employee_id")
    employee_name = serializers.SerializerMethodField()
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")

    class Meta:
        model = EmploymentContract
        fields = [
            "id", "employee", "employee_code", "employee_name", "business_unit",
            "business_unit_name", "contract_type", "start_date", "end_date",
            "salary_amount", "currency", "status", "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_employee_name(self, obj):
        return obj.employee.user.get_full_name() or obj.employee.user.email

    def validate(self, attrs):
        division = attrs.get("business_unit", getattr(self.instance, "business_unit", None))
        _check_division(self, division)
        employee = attrs.get("employee", getattr(self.instance, "employee", None))
        if employee is not None and division is not None and employee.business_unit_id != division.pk:
            raise serializers.ValidationError(
                "The employee must belong to the employment contract division."
            )
        return attrs


class EmploymentHistorySerializer(serializers.ModelSerializer):
    employee_code = serializers.ReadOnlyField(source="employee.employee_id")
    employee_name = serializers.SerializerMethodField()
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")
    department_name = serializers.ReadOnlyField(source="department.name", default=None)

    class Meta:
        model = EmploymentHistory
        fields = [
            "id", "employee", "employee_code", "employee_name", "business_unit",
            "business_unit_name", "department", "department_name", "designation",
            "start_date", "end_date", "note", "created_at",
        ]
        read_only_fields = ["created_at"]

    def get_employee_name(self, obj):
        return obj.employee.user.get_full_name() or obj.employee.user.email

    def validate(self, attrs):
        division = attrs.get("business_unit", getattr(self.instance, "business_unit", None))
        _check_division(self, division)
        employee = attrs.get("employee", getattr(self.instance, "employee", None))
        if employee is not None and division is not None and employee.business_unit_id != division.pk:
            raise serializers.ValidationError(
                "The employee must belong to the employment history division."
            )
        department = attrs.get("department", getattr(self.instance, "department", None))
        if department is not None and division is not None and department.business_unit_id != division.pk:
            raise serializers.ValidationError(
                "The department must belong to the employment history division."
            )
        return attrs


class LeaveBalanceSerializer(serializers.ModelSerializer):
    employee_code = serializers.ReadOnlyField(source="employee.employee_id")
    employee_name = serializers.SerializerMethodField()
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")
    available_days = serializers.ReadOnlyField()

    class Meta:
        model = LeaveBalance
        fields = [
            "id", "employee", "employee_code", "employee_name", "business_unit",
            "business_unit_name", "leave_type", "year", "entitled_days",
            "used_days", "carried_over_days", "available_days", "updated_at",
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
                "The employee must belong to the leave balance division."
            )
        return attrs


class EmployeeDocumentSerializer(serializers.ModelSerializer):
    employee_code = serializers.ReadOnlyField(source="employee.employee_id")
    employee_name = serializers.SerializerMethodField()
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")

    class Meta:
        model = EmployeeDocument
        fields = [
            "id", "employee", "employee_code", "employee_name", "business_unit",
            "business_unit_name", "name", "document_type", "stored_path",
            "issued_date", "expiry_date", "is_active", "created_at",
        ]
        read_only_fields = ["created_at"]

    def get_employee_name(self, obj):
        return obj.employee.user.get_full_name() or obj.employee.user.email

    def validate(self, attrs):
        division = attrs.get("business_unit", getattr(self.instance, "business_unit", None))
        _check_division(self, division)
        employee = attrs.get("employee", getattr(self.instance, "employee", None))
        if employee is not None and division is not None and employee.business_unit_id != division.pk:
            raise serializers.ValidationError(
                "The employee must belong to the employee document division."
            )
        return attrs


class WorkScheduleSerializer(serializers.ModelSerializer):
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")

    class Meta:
        model = WorkSchedule
        fields = [
            "id", "name", "business_unit", "business_unit_name",
            "is_active", "created_at",
        ]
        read_only_fields = ["created_at"]

    def validate_business_unit(self, value):
        _check_division(self, value)
        return value


# ---------------------------------------------------------------------------
# Finance and accounting serializers
# ---------------------------------------------------------------------------


class FinancialAccountSerializer(serializers.ModelSerializer):
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")

    class Meta:
        model = FinancialAccount
        fields = [
            "id", "code", "name", "business_unit", "business_unit_name",
            "account_type", "currency", "is_active", "created_at",
        ]
        read_only_fields = ["created_at"]

    def validate(self, attrs):
        division = attrs.get("business_unit", getattr(self.instance, "business_unit", None))
        _check_division(self, division)
        return attrs


class ExpenseCategorySerializer(serializers.ModelSerializer):
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")
    default_account_code = serializers.ReadOnlyField(source="default_account.code", default=None)
    default_account_name = serializers.ReadOnlyField(source="default_account.name", default=None)

    class Meta:
        model = ExpenseCategory
        fields = [
            "id", "name", "code", "business_unit", "business_unit_name",
            "default_account", "default_account_code", "default_account_name",
            "is_active", "created_at",
        ]
        read_only_fields = ["created_at"]

    def validate(self, attrs):
        division = attrs.get("business_unit", getattr(self.instance, "business_unit", None))
        _check_division(self, division)
        default_account = attrs.get("default_account", getattr(self.instance, "default_account", None))
        if default_account is not None and division is not None and default_account.business_unit_id != division.pk:
            raise serializers.ValidationError(
                "The default account must belong to the expense category division."
            )
        return attrs


class ExpenseSerializer(serializers.ModelSerializer):
    category_name = serializers.ReadOnlyField(source="category.name")
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")
    submitted_by_name = serializers.ReadOnlyField(source="submitted_by.email", default=None)
    approved_by_name = serializers.ReadOnlyField(source="approved_by.email", default=None)

    class Meta:
        model = Expense
        fields = [
            "id", "reference", "business_unit", "business_unit_name", "category",
            "category_name", "amount", "currency", "description", "status",
            "submitted_by", "submitted_by_name", "approved_by", "approved_by_name",
            "paid_at", "transaction_ref", "created_at",
        ]
        read_only_fields = ["submitted_by", "approved_by", "paid_at", "created_at"]

    def validate(self, attrs):
        division = attrs.get("business_unit", getattr(self.instance, "business_unit", None))
        _check_division(self, division)
        category = attrs.get("category", getattr(self.instance, "category", None))
        if category is not None and division is not None and category.business_unit_id != division.pk:
            raise serializers.ValidationError(
                "The expense category must belong to the expense division."
            )
        return attrs


class RevenueRecordSerializer(serializers.ModelSerializer):
    category_name = serializers.ReadOnlyField(source="category.name")
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")
    recorded_by_name = serializers.ReadOnlyField(source="recorded_by.email", default=None)

    class Meta:
        model = RevenueRecord
        fields = [
            "id", "reference", "business_unit", "business_unit_name", "category",
            "category_name", "amount", "currency", "description", "recorded_by",
            "recorded_by_name", "created_at",
        ]
        read_only_fields = ["recorded_by", "created_at"]

    def validate(self, attrs):
        division = attrs.get("business_unit", getattr(self.instance, "business_unit", None))
        _check_division(self, division)
        category = attrs.get("category", getattr(self.instance, "category", None))
        if category is not None and division is not None and category.business_unit_id != division.pk:
            raise serializers.ValidationError(
                "The revenue category must belong to the revenue division."
            )
        return attrs


class FinancialTransactionSerializer(serializers.ModelSerializer):
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")
    recorded_by_name = serializers.ReadOnlyField(source="recorded_by.email", default=None)
    journal_reference = serializers.ReadOnlyField(source="journal_entry.id", default=None)

    class Meta:
        model = FinancialTransaction
        fields = [
            "id", "reference", "business_unit", "business_unit_name",
            "transaction_date", "status", "description", "recorded_by",
            "recorded_by_name", "journal_reference", "created_at",
        ]
        read_only_fields = ["recorded_by", "created_at", "journal_reference"]

    def validate(self, attrs):
        division = attrs.get("business_unit", getattr(self.instance, "business_unit", None))
        _check_division(self, division)
        return attrs


class _JournalLineInputSerializer(serializers.Serializer):
    account = serializers.PrimaryKeyRelatedField(queryset=FinancialAccount.objects.all())
    debit = serializers.DecimalField(max_digits=14, decimal_places=2, default=0)
    credit = serializers.DecimalField(max_digits=14, decimal_places=2, default=0)
    description = serializers.CharField(max_length=250, required=False, default="")

    def validate(self, attrs):
        debit = attrs.get("debit") or 0
        credit = attrs.get("credit") or 0
        if debit and credit:
            raise serializers.ValidationError("Use either debit or credit, not both.")
        if not debit and not credit:
            raise serializers.ValidationError("A journal line must have either a debit or a credit.")
        return attrs


class JournalLineSerializer(serializers.ModelSerializer):
    account_code = serializers.ReadOnlyField(source="account.code")
    account_name = serializers.ReadOnlyField(source="account.name")

    class Meta:
        model = JournalLine
        fields = [
            "id", "account", "account_code", "account_name", "debit", "credit",
            "description",
        ]


class JournalEntrySerializer(serializers.ModelSerializer):
    financial_transaction_reference = serializers.ReadOnlyField(
        source="financial_transaction.reference"
    )
    business_unit_name = serializers.ReadOnlyField(
        source="financial_transaction.business_unit.name"
    )
    lines = JournalLineSerializer(many=True, read_only=True)

    class Meta:
        model = JournalEntry
        fields = [
            "id", "financial_transaction", "financial_transaction_reference",
            "business_unit_name", "description", "lines", "posted_at",
        ]
        read_only_fields = ["posted_at"]


class VendorPaymentSerializer(serializers.ModelSerializer):
    supplier_name = serializers.ReadOnlyField(source="supplier.name")
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")
    paid_by_name = serializers.ReadOnlyField(source="paid_by.email", default=None)

    class Meta:
        model = VendorPayment
        fields = [
            "id", "reference", "business_unit", "business_unit_name", "supplier",
            "supplier_name", "amount", "currency", "payment_date", "status",
            "paid_by", "paid_by_name", "notes", "created_at",
        ]
        read_only_fields = ["paid_by", "created_at"]

    def validate(self, attrs):
        division = attrs.get("business_unit", getattr(self.instance, "business_unit", None))
        _check_division(self, division)
        supplier = attrs.get("supplier", getattr(self.instance, "supplier", None))
        if supplier is not None and division is not None and supplier.business_unit_id != division.pk:
            raise serializers.ValidationError(
                "The vendor payment supplier must belong to the same division."
            )
        return attrs


class BudgetAllocationSerializer(serializers.ModelSerializer):
    category_name = serializers.ReadOnlyField(source="category.name")
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")

    class Meta:
        model = BudgetAllocation
        fields = [
            "id", "budget_year", "business_unit", "business_unit_name", "category",
            "category_name", "allocated_amount", "currency",
        ]

    def validate(self, attrs):
        division = attrs.get("business_unit", getattr(self.instance, "business_unit", None))
        _check_division(self, division)
        category = attrs.get("category", getattr(self.instance, "category", None))
        if category is not None and division is not None and category.business_unit_id != division.pk:
            raise serializers.ValidationError(
                "The budget category must belong to the same division."
            )
        return attrs


class PurchaseCostSerializer(serializers.ModelSerializer):
    supplier_name = serializers.ReadOnlyField(source="supplier.name")
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")
    receipt_reference = serializers.ReadOnlyField(source="receipt.reference", default=None)
    recorded_by_name = serializers.ReadOnlyField(source="recorded_by.email", default=None)

    class Meta:
        model = PurchaseCost
        fields = [
            "id", "reference", "business_unit", "business_unit_name", "supplier",
            "supplier_name", "receipt", "receipt_reference", "amount", "currency",
            "status", "recorded_by", "recorded_by_name", "recorded_at",
        ]
        read_only_fields = ["recorded_by", "recorded_at"]

    def validate(self, attrs):
        division = attrs.get("business_unit", getattr(self.instance, "business_unit", None))
        _check_division(self, division)
        supplier = attrs.get("supplier", getattr(self.instance, "supplier", None))
        if supplier is not None and division is not None and supplier.business_unit_id != division.pk:
            raise serializers.ValidationError(
                "The purchase cost supplier must belong to the same division."
            )
        receipt = attrs.get("receipt", getattr(self.instance, "receipt", None))
        if receipt is not None and division is not None and receipt.business_unit_id != division.pk:
            raise serializers.ValidationError(
                "The purchase cost receipt must belong to the same division."
            )
        return attrs


class TransportationExpenseSerializer(serializers.ModelSerializer):
    vehicle_plate = serializers.ReadOnlyField(source="vehicle.license_plate", default=None)
    driver_name = serializers.ReadOnlyField(source="driver.user.email", default=None)
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")
    submitted_by_name = serializers.ReadOnlyField(source="submitted_by.email", default=None)
    approved_by_name = serializers.ReadOnlyField(source="approved_by.email", default=None)

    class Meta:
        model = TransportationExpense
        fields = [
            "id", "reference", "business_unit", "business_unit_name", "expense_type",
            "vehicle", "vehicle_plate", "driver", "driver_name", "amount",
            "currency", "description", "status", "submitted_by", "submitted_by_name",
            "approved_by", "approved_by_name", "approved_at", "created_at",
        ]
        read_only_fields = ["submitted_by", "approved_by", "approved_at", "created_at"]

    def validate(self, attrs):
        division = attrs.get("business_unit", getattr(self.instance, "business_unit", None))
        _check_division(self, division)
        vehicle = attrs.get("vehicle", getattr(self.instance, "vehicle", None))
        if vehicle is not None and division is not None and vehicle.business_unit_id != division.pk:
            raise serializers.ValidationError(
                "The transportation expense vehicle must belong to the same division."
            )
        driver = attrs.get("driver", getattr(self.instance, "driver", None))
        if driver is not None and division is not None and driver.user.business_unit_id != division.pk:
            raise serializers.ValidationError(
                "The transportation expense driver must belong to the same division."
            )
        return attrs
