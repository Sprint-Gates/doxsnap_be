"""
Journal Posting Service
Handles automatic creation of journal entries from source documents:
- Invoice allocations (when periods are recognized)
- Work orders (when completed)
- Petty cash transactions (when approved)
"""

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, Tuple, List
import json
import logging

from app.models import (
    User, Company, Site,
    AccountType, Account, FiscalPeriod, JournalEntry, JournalEntryLine,
    AccountBalance, DefaultAccountMapping,
    ProcessedImage, InvoiceAllocation, AllocationPeriod,
    WorkOrder, WorkOrderSparePart, WorkOrderTimeEntry,
    PettyCashTransaction, PettyCashReplenishment
)

logger = logging.getLogger(__name__)


class JournalPostingService:
    """Service for creating journal entries from source documents"""

    def __init__(self, db: Session, company_id: int, user_id: int):
        self.db = db
        self.company_id = company_id
        self.user_id = user_id
        self._mappings_cache = None

    def _get_mappings(self) -> dict:
        """Load and cache account mappings"""
        if self._mappings_cache is None:
            mappings = self.db.query(DefaultAccountMapping).filter(
                DefaultAccountMapping.company_id == self.company_id,
                DefaultAccountMapping.is_active == True
            ).all()

            self._mappings_cache = {}
            for m in mappings:
                key = (m.transaction_type, m.category)
                self._mappings_cache[key] = m

        return self._mappings_cache

    def _get_mapping(self, transaction_type: str, category: Optional[str] = None) -> Optional[DefaultAccountMapping]:
        """Get account mapping for a transaction type and optional category"""
        mappings = self._get_mappings()

        # Try specific category first
        if category:
            mapping = mappings.get((transaction_type, category))
            if mapping:
                return mapping

        # Fall back to no category
        return mappings.get((transaction_type, None))

    def _generate_entry_number(self) -> str:
        """Generate unique journal entry number"""
        year = datetime.now().year
        prefix = f"JE-{year}-"

        last_entry = self.db.query(JournalEntry).filter(
            JournalEntry.company_id == self.company_id,
            JournalEntry.entry_number.like(f"{prefix}%")
        ).order_by(desc(JournalEntry.entry_number)).first()

        if last_entry:
            try:
                last_num = int(last_entry.entry_number.split("-")[-1])
                next_num = last_num + 1
            except (ValueError, IndexError):
                next_num = 1
        else:
            next_num = 1

        return f"{prefix}{next_num:06d}"

    def _get_fiscal_period(self, entry_date: date) -> Optional[FiscalPeriod]:
        """Get fiscal period for a date"""
        return self.db.query(FiscalPeriod).filter(
            FiscalPeriod.company_id == self.company_id,
            FiscalPeriod.start_date <= entry_date,
            FiscalPeriod.end_date >= entry_date,
            FiscalPeriod.status != "closed"
        ).first()

    def _update_account_balance(self, entry: JournalEntry):
        """Update account balances after posting"""
        if not entry.fiscal_period_id:
            return

        for line in entry.lines:
            balance = self.db.query(AccountBalance).filter(
                AccountBalance.company_id == self.company_id,
                AccountBalance.account_id == line.account_id,
                AccountBalance.fiscal_period_id == entry.fiscal_period_id,
                AccountBalance.site_id == line.site_id
            ).first()

            if not balance:
                balance = AccountBalance(
                    company_id=self.company_id,
                    account_id=line.account_id,
                    fiscal_period_id=entry.fiscal_period_id,
                    site_id=line.site_id,
                    period_debit=0,
                    period_credit=0,
                    opening_balance=0,
                    closing_balance=0
                )
                self.db.add(balance)

            balance.period_debit = float(Decimal(str(balance.period_debit)) + Decimal(str(line.debit)))
            balance.period_credit = float(Decimal(str(balance.period_credit)) + Decimal(str(line.credit)))

            # Get account's normal balance
            account = self.db.query(Account).options(
                joinedload(Account.account_type)
            ).filter(Account.id == line.account_id).first()

            if account and account.account_type:
                if account.account_type.normal_balance == "debit":
                    balance.closing_balance = float(
                        Decimal(str(balance.opening_balance)) +
                        Decimal(str(balance.period_debit)) -
                        Decimal(str(balance.period_credit))
                    )
                else:
                    balance.closing_balance = float(
                        Decimal(str(balance.opening_balance)) +
                        Decimal(str(balance.period_credit)) -
                        Decimal(str(balance.period_debit))
                    )

    def post_invoice_allocation(
        self,
        period: AllocationPeriod,
        post_immediately: bool = True
    ) -> Optional[JournalEntry]:
        """
        Create journal entry for an invoice allocation period recognition.
        Called when an allocation period is marked as recognized.
        """
        allocation = period.allocation
        invoice = allocation.invoice

        if not invoice:
            logger.warning(f"No invoice found for allocation {allocation.id}")
            return None

        # Determine site from allocation
        site_id = allocation.site_id
        if not site_id and allocation.contract_id:
            # Get site from contract if available
            from app.models import Contract
            contract = self.db.query(Contract).filter(Contract.id == allocation.contract_id).first()
            if contract and contract.sites:
                site_id = contract.sites[0].id  # Use first site

        # Parse invoice data
        try:
            invoice_data = json.loads(invoice.structured_data) if invoice.structured_data else {}
        except json.JSONDecodeError:
            invoice_data = {}

        # Get invoice category
        invoice_category = invoice.invoice_category or "expense"

        # Get account mapping
        mapping = self._get_mapping("invoice_expense", invoice_category)
        if not mapping:
            logger.warning(f"No account mapping for invoice_expense/{invoice_category}")
            return None

        # Calculate amounts
        amount = float(period.amount)
        vat_amount = 0

        # Check for VAT in invoice
        financial_details = invoice_data.get("financial_details", {})
        total_tax = float(financial_details.get("total_tax_amount", 0) or 0)

        if total_tax > 0 and allocation.number_of_periods > 0:
            # Proportional VAT for this period
            vat_amount = total_tax / allocation.number_of_periods

        # Get vendor info
        vendor_id = invoice.vendor_id
        supplier_info = invoice_data.get("supplier", {})
        invoice_number = invoice_data.get("document_info", {}).get("invoice_number", "")

        # Create journal entry
        entry_date = period.period_end or date.today()
        fiscal_period = self._get_fiscal_period(entry_date)

        entry = JournalEntry(
            company_id=self.company_id,
            entry_number=self._generate_entry_number(),
            entry_date=entry_date,
            description=f"Invoice {invoice_number} - {supplier_info.get('company_name', 'Unknown')} - Period {period.period_number}",
            reference=period.recognition_number,
            source_type="invoice",
            source_id=period.id,
            source_number=f"INV-{invoice.id}/P{period.period_number}",
            fiscal_period_id=fiscal_period.id if fiscal_period else None,
            status="draft",
            is_auto_generated=True,
            created_by=self.user_id
        )
        self.db.add(entry)
        self.db.flush()

        lines = []
        line_number = 1

        # Debit: Expense account
        if mapping.debit_account_id:
            expense_line = JournalEntryLine(
                journal_entry_id=entry.id,
                account_id=mapping.debit_account_id,
                debit=amount - vat_amount,  # Net amount
                credit=0,
                description=f"Invoice expense - {invoice_category}",
                site_id=site_id,
                contract_id=allocation.contract_id,
                vendor_id=vendor_id,
                project_id=allocation.project_id,
                line_number=line_number
            )
            self.db.add(expense_line)
            lines.append(expense_line)
            line_number += 1

        # Debit: VAT Input (if applicable)
        if vat_amount > 0:
            vat_mapping = self._get_mapping("invoice_vat")
            if vat_mapping and vat_mapping.debit_account_id:
                vat_line = JournalEntryLine(
                    journal_entry_id=entry.id,
                    account_id=vat_mapping.debit_account_id,
                    debit=vat_amount,
                    credit=0,
                    description="VAT Input",
                    site_id=site_id,
                    vendor_id=vendor_id,
                    line_number=line_number
                )
                self.db.add(vat_line)
                lines.append(vat_line)
                line_number += 1

        # Credit: Accounts Payable
        if mapping.credit_account_id:
            payable_line = JournalEntryLine(
                journal_entry_id=entry.id,
                account_id=mapping.credit_account_id,
                debit=0,
                credit=amount,  # Full amount including VAT
                description=f"Payable to {supplier_info.get('company_name', 'vendor')}",
                site_id=site_id,
                vendor_id=vendor_id,
                line_number=line_number
            )
            self.db.add(payable_line)
            lines.append(payable_line)

        # Update totals
        entry.total_debit = sum(float(l.debit) for l in lines)
        entry.total_credit = sum(float(l.credit) for l in lines)

        if post_immediately:
            entry.status = "posted"
            entry.posted_at = datetime.utcnow()
            entry.posted_by = self.user_id
            self._update_account_balance(entry)

        self.db.commit()
        logger.info(f"Created journal entry {entry.entry_number} for allocation period {period.id}")

        return entry

    def post_work_order_completion(
        self,
        work_order: WorkOrder,
        post_immediately: bool = True
    ) -> Optional[JournalEntry]:
        """
        Create journal entry when a work order is completed.
        Posts labor costs and spare parts usage.
        """
        if work_order.status != "completed":
            logger.warning(f"Work order {work_order.id} is not completed")
            return None

        site_id = work_order.site_id
        contract_id = work_order.contract_id

        # Calculate labor cost from time entries
        labor_cost = 0
        time_entries = self.db.query(WorkOrderTimeEntry).filter(
            WorkOrderTimeEntry.work_order_id == work_order.id
        ).all()

        for te in time_entries:
            labor_cost += float(te.total_cost or 0)

        # Calculate parts cost
        parts_cost = 0
        spare_parts = self.db.query(WorkOrderSparePart).filter(
            WorkOrderSparePart.work_order_id == work_order.id
        ).all()

        for sp in spare_parts:
            parts_cost += float(sp.total_cost or 0)

        # Skip if no costs
        if labor_cost == 0 and parts_cost == 0:
            logger.info(f"Work order {work_order.id} has no costs to post")
            return None

        # Get account mappings
        labor_mapping = self._get_mapping("work_order_labor")
        parts_mapping = self._get_mapping("work_order_parts")

        if not labor_mapping and not parts_mapping:
            logger.warning("No account mappings for work order costs")
            return None

        # Create journal entry
        entry_date = work_order.completed_at.date() if work_order.completed_at else date.today()
        fiscal_period = self._get_fiscal_period(entry_date)

        entry = JournalEntry(
            company_id=self.company_id,
            entry_number=self._generate_entry_number(),
            entry_date=entry_date,
            description=f"Work Order {work_order.wo_number} - {work_order.title or 'Completion'}",
            reference=work_order.wo_number,
            source_type="work_order",
            source_id=work_order.id,
            source_number=work_order.wo_number,
            fiscal_period_id=fiscal_period.id if fiscal_period else None,
            status="draft",
            is_auto_generated=True,
            created_by=self.user_id
        )
        self.db.add(entry)
        self.db.flush()

        lines = []
        line_number = 1

        # Labor cost entries
        if labor_cost > 0 and labor_mapping:
            if labor_mapping.debit_account_id:
                labor_debit = JournalEntryLine(
                    journal_entry_id=entry.id,
                    account_id=labor_mapping.debit_account_id,
                    debit=labor_cost,
                    credit=0,
                    description="Labor cost",
                    site_id=site_id,
                    contract_id=contract_id,
                    work_order_id=work_order.id,
                    line_number=line_number
                )
                self.db.add(labor_debit)
                lines.append(labor_debit)
                line_number += 1

            if labor_mapping.credit_account_id:
                labor_credit = JournalEntryLine(
                    journal_entry_id=entry.id,
                    account_id=labor_mapping.credit_account_id,
                    debit=0,
                    credit=labor_cost,
                    description="Accrued labor",
                    site_id=site_id,
                    work_order_id=work_order.id,
                    line_number=line_number
                )
                self.db.add(labor_credit)
                lines.append(labor_credit)
                line_number += 1

        # Parts cost entries
        if parts_cost > 0 and parts_mapping:
            if parts_mapping.debit_account_id:
                parts_debit = JournalEntryLine(
                    journal_entry_id=entry.id,
                    account_id=parts_mapping.debit_account_id,
                    debit=parts_cost,
                    credit=0,
                    description="Spare parts cost",
                    site_id=site_id,
                    contract_id=contract_id,
                    work_order_id=work_order.id,
                    line_number=line_number
                )
                self.db.add(parts_debit)
                lines.append(parts_debit)
                line_number += 1

            if parts_mapping.credit_account_id:
                parts_credit = JournalEntryLine(
                    journal_entry_id=entry.id,
                    account_id=parts_mapping.credit_account_id,
                    debit=0,
                    credit=parts_cost,
                    description="Inventory reduction",
                    site_id=site_id,
                    work_order_id=work_order.id,
                    line_number=line_number
                )
                self.db.add(parts_credit)
                lines.append(parts_credit)

        # Update totals
        entry.total_debit = sum(float(l.debit) for l in lines)
        entry.total_credit = sum(float(l.credit) for l in lines)

        if post_immediately:
            entry.status = "posted"
            entry.posted_at = datetime.utcnow()
            entry.posted_by = self.user_id
            self._update_account_balance(entry)

        self.db.commit()
        logger.info(f"Created journal entry {entry.entry_number} for work order {work_order.id}")

        return entry

    def post_petty_cash_transaction(
        self,
        transaction: PettyCashTransaction,
        post_immediately: bool = True
    ) -> Optional[JournalEntry]:
        """
        Create journal entry when a petty cash transaction is approved.
        """
        if transaction.status != "approved":
            logger.warning(f"Petty cash transaction {transaction.id} is not approved")
            return None

        # Get site from work order if linked
        site_id = None
        if transaction.work_order_id:
            wo = self.db.query(WorkOrder).filter(WorkOrder.id == transaction.work_order_id).first()
            if wo:
                site_id = wo.site_id

        # Get account mapping based on category
        category = transaction.category or "other"
        mapping = self._get_mapping("petty_cash_expense", category)

        if not mapping:
            # Try generic petty cash mapping
            mapping = self._get_mapping("petty_cash_expense")

        if not mapping:
            logger.warning(f"No account mapping for petty_cash_expense/{category}")
            return None

        amount = float(transaction.amount)

        # Create journal entry
        entry_date = transaction.transaction_date or date.today()
        fiscal_period = self._get_fiscal_period(entry_date)

        entry = JournalEntry(
            company_id=self.company_id,
            entry_number=self._generate_entry_number(),
            entry_date=entry_date,
            description=f"Petty Cash - {transaction.description or category}",
            reference=transaction.transaction_number,
            source_type="petty_cash",
            source_id=transaction.id,
            source_number=transaction.transaction_number,
            fiscal_period_id=fiscal_period.id if fiscal_period else None,
            status="draft",
            is_auto_generated=True,
            created_by=self.user_id
        )
        self.db.add(entry)
        self.db.flush()

        lines = []
        line_number = 1

        # Debit: Expense account
        if mapping.debit_account_id:
            expense_line = JournalEntryLine(
                journal_entry_id=entry.id,
                account_id=mapping.debit_account_id,
                debit=amount,
                credit=0,
                description=transaction.description or f"Petty cash - {category}",
                site_id=site_id,
                work_order_id=transaction.work_order_id,
                contract_id=transaction.contract_id,
                line_number=line_number
            )
            self.db.add(expense_line)
            lines.append(expense_line)
            line_number += 1

        # Credit: Petty Cash Fund
        if mapping.credit_account_id:
            fund_line = JournalEntryLine(
                journal_entry_id=entry.id,
                account_id=mapping.credit_account_id,
                debit=0,
                credit=amount,
                description="Petty cash fund reduction",
                line_number=line_number
            )
            self.db.add(fund_line)
            lines.append(fund_line)

        # Update totals
        entry.total_debit = sum(float(l.debit) for l in lines)
        entry.total_credit = sum(float(l.credit) for l in lines)

        if post_immediately:
            entry.status = "posted"
            entry.posted_at = datetime.utcnow()
            entry.posted_by = self.user_id
            self._update_account_balance(entry)

        self.db.commit()
        logger.info(f"Created journal entry {entry.entry_number} for petty cash {transaction.id}")

        return entry

    def post_petty_cash_replenishment(
        self,
        replenishment: PettyCashReplenishment,
        post_immediately: bool = True
    ) -> Optional[JournalEntry]:
        """
        Create journal entry when a petty cash fund is replenished.
        """
        mapping = self._get_mapping("petty_cash_replenishment")

        if not mapping:
            logger.warning("No account mapping for petty_cash_replenishment")
            return None

        amount = float(replenishment.amount)

        # Create journal entry
        entry_date = replenishment.replenishment_date or date.today()
        fiscal_period = self._get_fiscal_period(entry_date)

        entry = JournalEntry(
            company_id=self.company_id,
            entry_number=self._generate_entry_number(),
            entry_date=entry_date,
            description=f"Petty Cash Replenishment - {replenishment.method}",
            reference=replenishment.replenishment_number,
            source_type="petty_cash_replenishment",
            source_id=replenishment.id,
            source_number=replenishment.replenishment_number,
            fiscal_period_id=fiscal_period.id if fiscal_period else None,
            status="draft",
            is_auto_generated=True,
            created_by=self.user_id
        )
        self.db.add(entry)
        self.db.flush()

        lines = []
        line_number = 1

        # Debit: Petty Cash Fund
        if mapping.debit_account_id:
            fund_line = JournalEntryLine(
                journal_entry_id=entry.id,
                account_id=mapping.debit_account_id,
                debit=amount,
                credit=0,
                description="Petty cash fund increase",
                line_number=line_number
            )
            self.db.add(fund_line)
            lines.append(fund_line)
            line_number += 1

        # Credit: Cash/Bank
        if mapping.credit_account_id:
            cash_line = JournalEntryLine(
                journal_entry_id=entry.id,
                account_id=mapping.credit_account_id,
                debit=0,
                credit=amount,
                description=f"Cash disbursement - {replenishment.reference_number or replenishment.method}",
                line_number=line_number
            )
            self.db.add(cash_line)
            lines.append(cash_line)

        # Update totals
        entry.total_debit = sum(float(l.debit) for l in lines)
        entry.total_credit = sum(float(l.credit) for l in lines)

        if post_immediately:
            entry.status = "posted"
            entry.posted_at = datetime.utcnow()
            entry.posted_by = self.user_id
            self._update_account_balance(entry)

        self.db.commit()
        logger.info(f"Created journal entry {entry.entry_number} for replenishment {replenishment.id}")

        return entry
