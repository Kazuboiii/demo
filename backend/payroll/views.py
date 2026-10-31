from django.db import transaction
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
    LeaveBalance,
    PayrollRun,
    PurchaseCost,
    RevenueRecord,
    SalaryStructure,
    VendorPayment,
    WorkSchedule,
)
from nemt.models import TransportationExpense
from .serializers import (
    BudgetAllocationSerializer,
    EmploymentContractSerializer,
    EmploymentHistorySerializer,
    EmployeeDocumentSerializer,
    ExpenseCategorySerializer,
    ExpenseSerializer,
    FinancialAccountSerializer,
    FinancialTransactionSerializer,
    JournalEntrySerializer,
    JournalLineSerializer,
    LeaveBalanceSerializer,
    PayrollRunSerializer,
    PurchaseCostSerializer,
    RevenueRecordSerializer,
    SalaryStructureSerializer,
    TransportationExpenseSerializer,
    VendorPaymentSerializer,
    WorkScheduleSerializer,
)


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


# ---------------------------------------------------------------------------
# HR and workforce administration views
# ---------------------------------------------------------------------------


class EmploymentContractViewSet(viewsets.ModelViewSet):
    queryset = EmploymentContract.objects.all().select_related(
        "employee__user", "business_unit"
    ).order_by("-start_date")
    serializer_class = EmploymentContractSerializer
    permission_classes = [ModulePermission]
    module = "hr"

    def get_queryset(self):
        return _scoped(super().get_queryset(), self.request)


class EmploymentHistoryViewSet(viewsets.ModelViewSet):
    queryset = EmploymentHistory.objects.all().select_related(
        "employee__user", "business_unit", "department"
    ).order_by("-start_date")
    serializer_class = EmploymentHistorySerializer
    permission_classes = [ModulePermission]
    module = "hr"

    def get_queryset(self):
        return _scoped(super().get_queryset(), self.request)


class LeaveBalanceViewSet(viewsets.ModelViewSet):
    queryset = LeaveBalance.objects.all().select_related(
        "employee__user", "business_unit"
    ).order_by("employee__employee_id", "leave_type", "year")
    serializer_class = LeaveBalanceSerializer
    permission_classes = [ModulePermission]
    module = "hr"

    def get_queryset(self):
        return _scoped(super().get_queryset(), self.request)


class EmployeeDocumentViewSet(viewsets.ModelViewSet):
    queryset = EmployeeDocument.objects.all().select_related(
        "employee__user", "business_unit"
    ).order_by("-created_at")
    serializer_class = EmployeeDocumentSerializer
    permission_classes = [ModulePermission]
    module = "hr"

    def get_queryset(self):
        return _scoped(super().get_queryset(), self.request)


class WorkScheduleViewSet(viewsets.ModelViewSet):
    queryset = WorkSchedule.objects.all().select_related(
        "business_unit"
    ).order_by("business_unit__name", "name")
    serializer_class = WorkScheduleSerializer
    permission_classes = [ModulePermission]
    module = "hr"

    def get_queryset(self):
        return _scoped(super().get_queryset(), self.request)


# ---------------------------------------------------------------------------
# Finance and accounting views
# ---------------------------------------------------------------------------


class FinancialAccountViewSet(viewsets.ModelViewSet):
    queryset = FinancialAccount.objects.all().select_related(
        "business_unit"
    ).order_by("business_unit__name", "code")
    serializer_class = FinancialAccountSerializer
    permission_classes = [ModulePermission]
    module = "finance"

    def get_queryset(self):
        return _scoped(super().get_queryset(), self.request)


class ExpenseCategoryViewSet(viewsets.ModelViewSet):
    queryset = ExpenseCategory.objects.all().select_related(
        "business_unit", "default_account"
    ).order_by("business_unit__name", "name")
    serializer_class = ExpenseCategorySerializer
    permission_classes = [ModulePermission]
    module = "finance"

    def get_queryset(self):
        return _scoped(super().get_queryset(), self.request)


class ExpenseViewSet(viewsets.ModelViewSet):
    queryset = Expense.objects.all().select_related(
        "business_unit", "category", "submitted_by", "approved_by"
    ).order_by("-created_at")
    serializer_class = ExpenseSerializer
    permission_classes = [ModulePermission]
    module = "finance"

    def get_queryset(self):
        return _scoped(super().get_queryset(), self.request)

    def perform_create(self, serializer):
        serializer.save(submitted_by=self.request.user)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        if not role_can(request.user, "finance", "approve"):
            raise PermissionDenied("You do not have finance approval permission.")
        expense = self.get_object()
        if expense.status != Expense.STATUS_DRAFT:
            return Response({"detail": "Only draft expenses can be approved."}, status=400)
        expense.status = Expense.STATUS_APPROVED
        expense.approved_by = request.user
        expense.save(update_fields=["status", "approved_by"])
        return Response(ExpenseSerializer(expense, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def mark_paid(self, request, pk=None):
        if not role_can(request.user, "finance", "approve"):
            raise PermissionDenied("You do not have finance approval permission.")
        expense = self.get_object()
        if expense.status != Expense.STATUS_APPROVED:
            return Response({"detail": "Only approved expenses can be marked paid."}, status=400)
        expense.status = Expense.STATUS_PAID
        expense.paid_at = timezone.now()
        expense.save(update_fields=["status", "paid_at"])
        return Response(ExpenseSerializer(expense, context={"request": request}).data)


class RevenueRecordViewSet(viewsets.ModelViewSet):
    queryset = RevenueRecord.objects.all().select_related(
        "business_unit", "category", "recorded_by"
    ).order_by("-created_at")
    serializer_class = RevenueRecordSerializer
    permission_classes = [ModulePermission]
    module = "finance"

    def get_queryset(self):
        return _scoped(super().get_queryset(), self.request)

    def perform_create(self, serializer):
        serializer.save(recorded_by=self.request.user)


class FinancialTransactionViewSet(viewsets.ModelViewSet):
    queryset = FinancialTransaction.objects.all().select_related(
        "business_unit", "recorded_by", "journal_entry"
    ).order_by("-transaction_date", "-created_at")
    serializer_class = FinancialTransactionSerializer
    permission_classes = [ModulePermission]
    module = "finance"

    def get_queryset(self):
        return _scoped(super().get_queryset(), self.request)

    def perform_create(self, serializer):
        serializer.save(recorded_by=self.request.user)

    @action(detail=True, methods=["post"])
    def post_journal(self, request, pk=None):
        if not role_can(request.user, "finance", "approve"):
            raise PermissionDenied("You do not have finance approval permission.")
        t = self.get_object()
        if t.status != FinancialTransaction.STATUS_PENDING:
            return Response({"detail": "Only pending financial transactions can be posted."}, status=400)
        lines_data = request.data.get("lines")
        if not lines_data:
            return Response({"detail": "Journal lines are required."}, status=400)
        from .serializers import _JournalLineInputSerializer

        line_serializer = _JournalLineInputSerializer(data=lines_data, many=True)
        line_serializer.is_valid(raise_exception=True)
        je = JournalEntry.objects.create(
            financial_transaction=t,
            description=t.description,
            posted_at=timezone.now(),
        )
        for line in line_serializer.validated_data:
            JournalLine.objects.create(
                journal_entry=je,
                account=line["account"],
                debit=line["debit"],
                credit=line["credit"],
                description=line.get("description", ""),
            )
        t.status = FinancialTransaction.STATUS_POSTED
        t.save(update_fields=["status", "updated_at"])
        t.journal_entry = je
        t.save(update_fields=["journal_entry"])
        return Response(JournalEntrySerializer(je, context={"request": request}).data)


class JournalEntryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = JournalEntry.objects.all().select_related(
        "financial_transaction"
    ).prefetch_related("lines__account")
    serializer_class = JournalEntrySerializer
    permission_classes = [ModulePermission]
    module = "finance"

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user or not user.is_authenticated:
            return qs.none()
        if user.is_superuser or user.has_role("super_admin"):
            return qs
        return qs.filter(financial_transaction__business_unit__in=user.accessible_business_units())


class VendorPaymentViewSet(viewsets.ModelViewSet):
    queryset = VendorPayment.objects.all().select_related(
        "business_unit", "supplier", "paid_by"
    ).order_by("-payment_date", "-created_at")
    serializer_class = VendorPaymentSerializer
    permission_classes = [ModulePermission]
    module = "finance"

    def get_queryset(self):
        return _scoped(super().get_queryset(), self.request)

    def perform_create(self, serializer):
        serializer.save(paid_by=self.request.user)

    @action(detail=True, methods=["post"])
    def process_payment(self, request, pk=None):
        payment = self.get_object()
        if payment.status != VendorPayment.STATUS_PENDING:
            return Response({"detail": "Only pending vendor payments can be processed."}, status=400)
        payment.status = VendorPayment.STATUS_PROCESSED
        payment.paid_at = timezone.now()
        payment.save(update_fields=["status", "paid_at", "updated_at"])
        return Response(VendorPaymentSerializer(payment, context={"request": request}).data)


class BudgetAllocationViewSet(viewsets.ModelViewSet):
    queryset = BudgetAllocation.objects.all().select_related(
        "business_unit", "category"
    ).order_by("budget_year", "business_unit__name")
    serializer_class = BudgetAllocationSerializer
    permission_classes = [ModulePermission]
    module = "finance"

    def get_queryset(self):
        return _scoped(super().get_queryset(), self.request)


class PurchaseCostViewSet(viewsets.ModelViewSet):
    queryset = PurchaseCost.objects.all().select_related(
        "business_unit", "supplier", "receipt"
    ).order_by("-recorded_at")
    serializer_class = PurchaseCostSerializer
    permission_classes = [ModulePermission]
    module = "procurement"

    def get_queryset(self):
        return _scoped(super().get_queryset(), self.request)

    def perform_create(self, serializer):
        serializer.save(recorded_by=self.request.user)


class TransportationExpenseViewSet(viewsets.ModelViewSet):
    queryset = TransportationExpense.objects.all().select_related(
        "business_unit", "vehicle", "driver", "submitted_by", "approved_by"
    ).order_by("-created_at")
    serializer_class = TransportationExpenseSerializer
    permission_classes = [ModulePermission]
    module = "transport"

    def get_queryset(self):
        return _scoped(super().get_queryset(), self.request)

    def perform_create(self, serializer):
        serializer.save(submitted_by=self.request.user)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        if not role_can(request.user, "transport", "approve"):
            raise PermissionDenied("You do not have transport approval permission.")
        expense = self.get_object()
        if expense.status != TransportationExpense.STATUS_DRAFT:
            return Response({"detail": "Only draft transportation expenses can be approved."}, status=400)
        expense.status = TransportationExpense.STATUS_APPROVED
        expense.approved_by = request.user
        expense.approved_at = timezone.now()
        expense.save(update_fields=["status", "approved_by", "approved_at"])
        return Response(TransportationExpenseSerializer(expense, context={"request": request}).data)

