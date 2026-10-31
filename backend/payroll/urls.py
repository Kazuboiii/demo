from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    EmploymentContractViewSet,
    EmploymentHistoryViewSet,
    ExpenseViewSet,
    ExpenseCategoryViewSet,
    FinancialAccountViewSet,
    FinancialTransactionViewSet,
    JournalEntryViewSet,
    PayrollRunViewSet,
    SalaryStructureViewSet,
    TransportationExpenseViewSet,
    VendorPaymentViewSet,
    BudgetAllocationViewSet,
    PurchaseCostViewSet,
    LeaveBalanceViewSet,
    EmployeeDocumentViewSet,
    WorkScheduleViewSet,
    RevenueRecordViewSet,
)

router = DefaultRouter()
router.register(r"salary-structures", SalaryStructureViewSet)
router.register(r"runs", PayrollRunViewSet)
router.register(r"employment-contracts", EmploymentContractViewSet)
router.register(r"employment-history", EmploymentHistoryViewSet)
router.register(r"leave-balances", LeaveBalanceViewSet)
router.register(r"employee-documents", EmployeeDocumentViewSet)
router.register(r"work-schedules", WorkScheduleViewSet)
router.register(r"financial-accounts", FinancialAccountViewSet)
router.register(r"expense-categories", ExpenseCategoryViewSet)
router.register(r"expenses", ExpenseViewSet)
router.register(r"revenue", RevenueRecordViewSet)
router.register(r"financial-transactions", FinancialTransactionViewSet)
router.register(r"journal-entries", JournalEntryViewSet)
router.register(r"vendor-payments", VendorPaymentViewSet)
router.register(r"budget-allocations", BudgetAllocationViewSet)
router.register(r"purchase-costs", PurchaseCostViewSet)
router.register(r"transportation-expenses", TransportationExpenseViewSet)

urlpatterns = [path("", include(router.urls))]
