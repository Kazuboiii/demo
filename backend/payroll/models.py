"""Payroll source records.

Payroll is calculated only from configured salary structures and attendance
day counts. It never reads inventory, procurement or transport data.
"""

from decimal import Decimal

from django.db import models
from django.utils import timezone

from core.models import BusinessUnit, Employee


class SalaryStructure(models.Model):
    employee = models.OneToOneField(
        Employee, on_delete=models.CASCADE, related_name="salary_structure"
    )
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.PROTECT, related_name="salary_structures"
    )
    currency = models.CharField(max_length=8, default="NPR")
    basic_salary = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    housing_allowance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    transport_allowance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    other_allowance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax_rate_percent = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    other_deduction = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    effective_from = models.DateField(default=timezone.localdate)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["employee__employee_id"]
        verbose_name = "Salary Structure"
        verbose_name_plural = "Salary Structures"

    def __str__(self):
        return f"{self.employee.employee_id} - {self.basic_salary} {self.currency}"

    @property
    def allowances(self):
        return self.housing_allowance + self.transport_allowance + self.other_allowance

    @property
    def gross(self):
        return self.basic_salary + self.allowances

    def deductions_for(self, gross=None):
        gross = self.gross if gross is None else gross
        tax = (gross * self.tax_rate_percent / Decimal("100")).quantize(Decimal("0.01"))
        return tax + self.other_deduction


class PayrollRun(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_APPROVED = "approved"
    STATUS_PAID = "paid"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_PAID, "Paid"),
    ]

    reference = models.CharField(max_length=60, unique=True)
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.PROTECT, related_name="payroll_runs"
    )
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    currency = models.CharField(max_length=8, default="NPR")
    created_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="payroll_runs",
    )
    approved_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="approved_payroll_runs",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period_end", "-created_at"]
        verbose_name = "Payroll Run"
        verbose_name_plural = "Payroll Runs"

    def __str__(self):
        return f"{self.reference} ({self.period_start}..{self.period_end})"

    @property
    def total_gross(self):
        return sum((line.gross for line in self.lines.all()), Decimal("0"))

    @property
    def total_net(self):
        return sum((line.net for line in self.lines.all()), Decimal("0"))


class PayrollLine(models.Model):
    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name="lines")
    employee = models.ForeignKey(
        Employee, on_delete=models.PROTECT, related_name="payroll_lines"
    )
    basic_salary = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    allowances = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    deductions = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    gross = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    net = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    days_present = models.PositiveIntegerField(default=0)
    notes = models.CharField(max_length=250, blank=True, default="")

    class Meta:
        unique_together = [("run", "employee")]
        ordering = ["employee__employee_id"]
        verbose_name = "Payroll Line"
        verbose_name_plural = "Payroll Lines"

    def __str__(self):
        return f"{self.employee.employee_id} net {self.net}"


# ---------------------------------------------------------------------------
# Human Resources / workforce administration
# ---------------------------------------------------------------------------


class EmploymentContract(models.Model):
    """Employment contract metadata for an employee."""

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="contracts"
    )
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.PROTECT, related_name="employment_contracts"
    )
    contract_type = models.CharField(max_length=40)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    salary_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text="Monetary salary for this contract period, stored as decimal.",
    )
    currency = models.CharField(max_length=8, default="NPR")
    status = models.CharField(max_length=20, default="active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date"]
        verbose_name = "Employment Contract"
        verbose_name_plural = "Employment Contracts"

    def __str__(self):
        return f"{self.employee.employee_id} - {self.contract_type}"


class WorkSchedule(models.Model):
    """Reusable work schedule template."""

    name = models.CharField(max_length=100)
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.CASCADE, related_name="work_schedules"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["business_unit__name", "name"]
        unique_together = [("name", "business_unit")]
        verbose_name = "Work Schedule"
        verbose_name_plural = "Work Schedules"

    def __str__(self):
        return f"{self.business_unit.name} - {self.name}"


class LeaveBalance(models.Model):
    """Leave entitlement/balance snapshot per employee and leave type."""

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="leave_balances"
    )
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.PROTECT, related_name="leave_balances"
    )
    leave_type = models.CharField(max_length=50)
    year = models.PositiveIntegerField()
    entitled_days = models.PositiveIntegerField(default=0)
    used_days = models.PositiveIntegerField(default=0)
    carried_over_days = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["employee__employee_id", "leave_type", "year"]
        unique_together = [("employee", "leave_type", "year")]
        verbose_name = "Leave Balance"
        verbose_name_plural = "Leave Balances"

    def __str__(self):
        return f"{self.employee.employee_id} {self.leave_type} {self.year}"

    @property
    def available_days(self):
        return max(
            self.entitled_days + self.carried_over_days - self.used_days, 0
        )


class EmployeeDocument(models.Model):
    """Employee document metadata only; file storage is app/media specific."""

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="documents"
    )
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.PROTECT, related_name="employee_documents"
    )
    name = models.CharField(max_length=150)
    document_type = models.CharField(max_length=50)
    stored_path = models.CharField(max_length=250, blank=True, default="")
    issued_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Employee Document"
        verbose_name_plural = "Employee Documents"

    def __str__(self):
        return f"{self.employee.employee_id} - {self.name}"


class EmploymentHistory(models.Model):
    """Employment history entries (department/designation changes)."""

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="employment_history"
    )
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.PROTECT, related_name="employment_history"
    )
    department = models.ForeignKey(
        "core.Department",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employment_history_entries",
    )
    designation = models.CharField(max_length=100, blank=True, default="")
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=250, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date"]
        verbose_name = "Employment History"
        verbose_name_plural = "Employment History"

    def __str__(self):
        return f"{self.employee.employee_id} - {self.start_date}"


# ---------------------------------------------------------------------------
# Finance and accounting
# ---------------------------------------------------------------------------


class FinancialAccount(models.Model):
    """Chart-of-accounts style financial account."""

    ACCOUNT_TYPE_ASSET = "asset"
    ACCOUNT_TYPE_LIABILITY = "liability"
    ACCOUNT_TYPE_EXPENSE = "expense"
    ACCOUNT_TYPE_REVENUE = "revenue"
    ACCOUNT_TYPE_EQUITY = "equity"
    ACCOUNT_TYPE_CHOICES = [
        (ACCOUNT_TYPE_ASSET, "Asset"),
        (ACCOUNT_TYPE_LIABILITY, "Liability"),
        (ACCOUNT_TYPE_EXPENSE, "Expense"),
        (ACCOUNT_TYPE_REVENUE, "Revenue"),
        (ACCOUNT_TYPE_EQUITY, "Equity"),
    ]

    code = models.CharField(max_length=40)
    name = models.CharField(max_length=150)
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.CASCADE, related_name="financial_accounts"
    )
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPE_CHOICES)
    currency = models.CharField(max_length=8, default="NPR")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["business_unit__name", "code"]
        unique_together = [("business_unit", "code")]
        verbose_name = "Financial Account"
        verbose_name_plural = "Financial Accounts"

    def __str__(self):
        return f"{self.business_unit.code} {self.code} - {self.name}"


class ExpenseCategory(models.Model):
    """Expense/revenue categories for reporting."""

    name = models.CharField(max_length=100)
    code = models.CharField(max_length=40)
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.CASCADE, related_name="expense_categories"
    )
    default_account = models.ForeignKey(
        FinancialAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="category_defaults",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["business_unit__name", "name"]
        unique_together = [("business_unit", "code")]
        verbose_name = "Expense Category"
        verbose_name_plural = "Expense Categories"

    def __str__(self):
        return f"{self.business_unit.code} {self.code} - {self.name}"


class Expense(models.Model):
    """Monetary expense record. Amounts are decimal, never float."""

    STATUS_DRAFT = "draft"
    STATUS_APPROVED = "approved"
    STATUS_PAID = "paid"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_PAID, "Paid"),
        (STATUS_REJECTED, "Rejected"),
    ]

    reference = models.CharField(max_length=60, unique=True)
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.PROTECT, related_name="expenses"
    )
    category = models.ForeignKey(
        ExpenseCategory, on_delete=models.PROTECT, related_name="expenses"
    )
    amount = models.DecimalField(
        max_digits=14, decimal_places=2,
        help_text="Monetary amount, stored precisely as decimal.",
    )
    currency = models.CharField(max_length=8, default="NPR")
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    submitted_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="submitted_expenses",
    )
    approved_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="approved_expenses",
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    transaction_ref = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Expense"
        verbose_name_plural = "Expenses"
        indexes = [models.Index(fields=["business_unit", "-created_at"])]

    def __str__(self):
        return f"{self.reference} {self.amount} {self.currency}"


class RevenueRecord(models.Model):
    """Monetary revenue record."""

    reference = models.CharField(max_length=60, unique=True)
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.PROTECT, related_name="revenue_records"
    )
    category = models.ForeignKey(
        ExpenseCategory, on_delete=models.PROTECT, related_name="revenue_records"
    )
    amount = models.DecimalField(
        max_digits=14, decimal_places=2,
        help_text="Monetary amount, stored precisely as decimal.",
    )
    currency = models.CharField(max_length=8, default="NPR")
    description = models.TextField(blank=True, default="")
    recorded_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="recorded_revenue",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Revenue Record"
        verbose_name_plural = "Revenue Records"
        indexes = [models.Index(fields=["business_unit", "-created_at"])]

    def __str__(self):
        return f"{self.reference} {self.amount} {self.currency}"


class FinancialTransaction(models.Model):
    """General ledger-style financial transaction."""

    STATUS_PENDING = "pending"
    STATUS_POSTED = "posted"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_POSTED, "Posted"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    reference = models.CharField(max_length=60, unique=True)
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.PROTECT, related_name="financial_transactions"
    )
    transaction_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    description = models.TextField(blank=True, default="")
    recorded_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="financial_transactions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-transaction_date", "-created_at"]
        verbose_name = "Financial Transaction"
        verbose_name_plural = "Financial Transactions"
        indexes = [models.Index(fields=["business_unit", "-transaction_date"])]

    def __str__(self):
        return f"{self.reference} {self.transaction_date}"


class JournalEntry(models.Model):
    """Journal entry header."""

    financial_transaction = models.OneToOneField(
        FinancialTransaction,
        on_delete=models.CASCADE,
        related_name="journal_entry",
    )
    description = models.TextField(blank=True, default="")
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Journal Entry"
        verbose_name_plural = "Journal Entries"

    def __str__(self):
        return f"JE-{self.financial_transaction.reference}"


class JournalLine(models.Model):
    """Double-entry journal line."""

    journal_entry = models.ForeignKey(
        JournalEntry, on_delete=models.CASCADE, related_name="lines"
    )
    account = models.ForeignKey(
        FinancialAccount, on_delete=models.PROTECT, related_name="journal_lines"
    )
    debit = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text="Monetary debit amount, stored precisely as decimal.",
    )
    credit = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text="Monetary credit amount, stored precisely as decimal.",
    )
    description = models.CharField(max_length=250, blank=True, default="")

    class Meta:
        ordering = ["journal_entry", "account__code"]
        verbose_name = "Journal Line"
        verbose_name_plural = "Journal Lines"

    def __str__(self):
        return f"{self.account.code} dr {self.debit} cr {self.credit}"


class VendorPayment(models.Model):
    """Vendor/supplier payment record."""

    STATUS_PENDING = "pending"
    STATUS_PROCESSED = "processed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_PROCESSED, "Processed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    reference = models.CharField(max_length=60, unique=True)
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.PROTECT, related_name="vendor_payments"
    )
    supplier = models.ForeignKey(
        "inventory.Supplier",
        on_delete=models.PROTECT,
        related_name="vendor_payments",
        help_text="Inventory supplier being paid.",
    )
    amount = models.DecimalField(
        max_digits=14, decimal_places=2,
        help_text="Monetary payment amount, stored precisely as decimal.",
    )
    currency = models.CharField(max_length=8, default="NPR")
    payment_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    paid_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="vendor_payments",
    )
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-payment_date", "-created_at"]
        verbose_name = "Vendor Payment"
        verbose_name_plural = "Vendor Payments"
        indexes = [models.Index(fields=["business_unit", "-payment_date"])]

    def clean(self):
        if self.supplier_id and self.supplier.business_unit_id != self.business_unit_id:
            from django.core.exceptions import ValidationError

            raise ValidationError("Vendor payment supplier must belong to the same division.")

    def __str__(self):
        return f"{self.reference} {self.amount} {self.currency}"


class BudgetAllocation(models.Model):
    """Division budget allocation by category."""

    budget_year = models.PositiveIntegerField()
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.CASCADE, related_name="budget_allocations"
    )
    category = models.ForeignKey(
        ExpenseCategory, on_delete=models.PROTECT, related_name="budget_allocations"
    )
    allocated_amount = models.DecimalField(
        max_digits=14, decimal_places=2,
        help_text="Monetary budget allocation, stored precisely as decimal.",
    )
    currency = models.CharField(max_length=8, default="NPR")

    class Meta:
        ordering = ["budget_year", "business_unit__name"]
        unique_together = [("budget_year", "business_unit", "category")]
        verbose_name = "Budget Allocation"
        verbose_name_plural = "Budget Allocations"

    def __str__(self):
        return f"{self.business_unit.code} {self.budget_year} {self.category.code}"


class PurchaseCost(models.Model):
    """Purchase cost record tied to an inventory receipt line so the same
    supplier invoice is not recorded as both an inventory receipt and a
    duplicate expense. This keeps procurement spend and finance records aligned.
    """

    reference = models.CharField(max_length=60, unique=True)
    business_unit = models.ForeignKey(
        BusinessUnit, on_delete=models.PROTECT, related_name="purchase_costs"
    )
    supplier = models.ForeignKey(
        "inventory.Supplier",
        on_delete=models.PROTECT,
        related_name="purchase_costs",
    )
    receipt = models.OneToOneField(
        "inventory.StockReceipt",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="purchase_cost",
    )
    amount = models.DecimalField(
        max_digits=14, decimal_places=2,
        help_text="Monetary purchase cost, stored precisely as decimal.",
    )
    currency = models.CharField(max_length=8, default="NPR")
    status = models.CharField(max_length=20, default="recorded")
    recorded_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="purchase_costs",
    )
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-recorded_at"]
        verbose_name = "Purchase Cost"
        verbose_name_plural = "Purchase Costs"
        indexes = [models.Index(fields=["business_unit", "-recorded_at"])]

    def clean(self):
        if self.supplier_id and self.supplier.business_unit_id != self.business_unit_id:
            from django.core.exceptions import ValidationError

            raise ValidationError("Purchase cost supplier must belong to the same division.")
        if self.receipt_id and self.receipt.business_unit_id != self.business_unit_id:
            from django.core.exceptions import ValidationError

            raise ValidationError("Purchase cost receipt must belong to the same division.")

    def __str__(self):
        return f"{self.reference} {self.amount} {self.currency}"
