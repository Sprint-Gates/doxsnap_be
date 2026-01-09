"""
Journal Posting Service
Handles automatic creation of journal entries from source documents:
- Invoice allocations (when periods are recognized)
- Work orders (when completed)
- Petty cash transactions (when approved)
- Inventory transactions (PO receiving, adjustments, transfers)
"""

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, Tuple, List, Dict, Any
import json
import logging

from app.models import (
    User, Company, Site, Warehouse, BusinessUnit, Client, Contract, AddressBook,
    AccountType, Account, FiscalPeriod, JournalEntry, JournalEntryLine,
    AccountBalance, DefaultAccountMapping,
    ProcessedImage, InvoiceAllocation, AllocationPeriod,
    WorkOrder, WorkOrderSparePart, WorkOrderTimeEntry, ItemLedger as WorkOrderItemLedger,
    PettyCashTransaction, PettyCashReplenishment,
    PurchaseOrder, PurchaseOrderLine, ItemLedger, ItemMaster, ExchangeRate,
    GoodsReceiptExtraCost
)

logger = logging.getLogger(__name__)


class JournalPostingService:
    """Service for creating journal entries from source documents"""

    def __init__(self, db: Session, company_id: int, user_id: int):
        self.db = db
        self.company_id = company_id
        self.user_id = user_id
        self._mappings_cache = None
        self._warehouse_bu_cache = {}

    def _get_business_unit_from_warehouse(self, warehouse_id: Optional[int]) -> Optional[int]:
        """Get business_unit_id from a warehouse, with caching"""
        if not warehouse_id:
            return None

        if warehouse_id in self._warehouse_bu_cache:
            return self._warehouse_bu_cache[warehouse_id]

        warehouse = self.db.query(Warehouse).filter(
            Warehouse.id == warehouse_id,
            Warehouse.company_id == self.company_id
        ).first()

        bu_id = warehouse.business_unit_id if warehouse else None
        self._warehouse_bu_cache[warehouse_id] = bu_id
        return bu_id

    def _get_default_business_unit(self, bu_type: str = "profit_loss") -> Optional[int]:
        """Get the default business unit for a given type (balance_sheet or profit_loss)"""
        bu = self.db.query(BusinessUnit).filter(
            BusinessUnit.company_id == self.company_id,
            BusinessUnit.bu_type == bu_type,
            BusinessUnit.is_active == True,
            BusinessUnit.parent_id == None  # Top-level BU
        ).first()
        return bu.id if bu else None

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
            # Query by both site_id and business_unit_id for proper balance tracking
            balance = self.db.query(AccountBalance).filter(
                AccountBalance.company_id == self.company_id,
                AccountBalance.account_id == line.account_id,
                AccountBalance.fiscal_period_id == entry.fiscal_period_id,
                AccountBalance.site_id == line.site_id,
                AccountBalance.business_unit_id == line.business_unit_id
            ).first()

            if not balance:
                balance = AccountBalance(
                    company_id=self.company_id,
                    account_id=line.account_id,
                    fiscal_period_id=entry.fiscal_period_id,
                    site_id=line.site_id,
                    business_unit_id=line.business_unit_id,
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
                address_book_id=vendor_id,
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
                    address_book_id=vendor_id,
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
                address_book_id=vendor_id,
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
        project_id = work_order.project_id  # Track project for cost accounting

        # Calculate labor cost from time entries
        labor_cost = 0
        time_entries = self.db.query(WorkOrderTimeEntry).filter(
            WorkOrderTimeEntry.work_order_id == work_order.id
        ).all()

        for te in time_entries:
            labor_cost += float(te.total_cost or 0)

        # Calculate parts cost from ItemLedger (actual inventory movements)
        # This is consistent with post_work_order_billing() calculation
        parts_cost = 0
        issued_items = self.db.query(ItemLedger).filter(
            ItemLedger.work_order_id == work_order.id,
            ItemLedger.transaction_type == "ISSUE_WORK_ORDER"
        ).all()
        for item in issued_items:
            parts_cost += float(abs(item.total_cost or 0))

        # Subtract returned items
        returned_items = self.db.query(ItemLedger).filter(
            ItemLedger.work_order_id == work_order.id,
            ItemLedger.transaction_type == "RETURN_WORK_ORDER"
        ).all()
        for item in returned_items:
            parts_cost -= float(abs(item.total_cost or 0))

        parts_cost = max(0, parts_cost)

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

        # Create journal entry - use approved_at date since JE is created at approval
        entry_date = work_order.approved_at.date() if work_order.approved_at else (
            work_order.completed_at.date() if work_order.completed_at else date.today()
        )
        fiscal_period = self._get_fiscal_period(entry_date)

        entry = JournalEntry(
            company_id=self.company_id,
            entry_number=self._generate_entry_number(),
            entry_date=entry_date,
            description=f"Work Order Cost Recognition - {work_order.wo_number} - {work_order.title or 'Non-Billable'}",
            reference=work_order.wo_number,
            source_type="work_order_cost",
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
                    project_id=project_id,
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
                    project_id=project_id,
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
                    project_id=project_id,
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
                    project_id=project_id,
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

    def post_work_order_billing(
        self,
        work_order: WorkOrder,
        post_immediately: bool = True
    ) -> Optional[JournalEntry]:
        """
        Create journal entries when a billable work order is approved.
        This handles proper accounting for charging the client.

        As a CFO, the correct journal entries for a billable work order are:

        ENTRY 1 - Revenue Recognition (Charge to Client):
        ================================================
        DR: Accounts Receivable (Client)     = Billable Amount + VAT
          CR: Service Revenue                = Net Billable Amount
          CR: VAT Output (if applicable)     = VAT Amount

        ENTRY 2 - Cost Recognition (COGS for Labor):
        =============================================
        DR: Cost of Goods Sold - Labor       = Actual Labor Cost
          CR: Accrued Labor / Labor Payable  = Actual Labor Cost

        ENTRY 3 - Cost Recognition (COGS for Parts/Inventory):
        ======================================================
        DR: Cost of Goods Sold - Parts       = Actual Parts Cost
          CR: Inventory                      = Actual Parts Cost

        This ensures:
        - Revenue is matched with costs (matching principle)
        - Client is properly charged (AR created)
        - Inventory is properly relieved
        - VAT is correctly recorded for tax reporting
        - Profit margin is visible (Revenue - COGS)
        """
        if not work_order.is_billable:
            logger.info(f"Work order {work_order.id} is not billable, skipping billing entry")
            return None

        if work_order.approved_at is None:
            logger.warning(f"Work order {work_order.id} is not approved yet")
            return None

        site_id = work_order.site_id
        contract_id = work_order.contract_id
        project_id = work_order.project_id  # Track project for financial reporting

        # Get client info from site
        client_id = None
        client_address_book_id = None
        client_name = "Client"

        if site_id:
            site = self.db.query(Site).filter(Site.id == site_id).first()
            if site and site.client_id:
                client = self.db.query(Client).filter(Client.id == site.client_id).first()
                if client:
                    client_id = client.id
                    client_address_book_id = client.address_book_id
                    client_name = client.name

        # Calculate costs
        # Labor cost from time entries
        labor_cost = Decimal("0")
        time_entries = self.db.query(WorkOrderTimeEntry).filter(
            WorkOrderTimeEntry.work_order_id == work_order.id
        ).all()
        for te in time_entries:
            labor_cost += Decimal(str(te.total_cost or 0))

        # Parts cost from issued items (ItemLedger)
        parts_cost = Decimal("0")
        issued_items = self.db.query(ItemLedger).filter(
            ItemLedger.work_order_id == work_order.id,
            ItemLedger.transaction_type == "ISSUE_WORK_ORDER"
        ).all()
        for item in issued_items:
            parts_cost += Decimal(str(abs(item.total_cost or 0)))

        # Subtract returned items
        returned_items = self.db.query(ItemLedger).filter(
            ItemLedger.work_order_id == work_order.id,
            ItemLedger.transaction_type == "RETURN_WORK_ORDER"
        ).all()
        for item in returned_items:
            parts_cost -= Decimal(str(abs(item.total_cost or 0)))

        parts_cost = max(Decimal("0"), parts_cost)

        # Calculate billable amount with markup
        labor_markup = Decimal(str(work_order.labor_markup_percent or 0)) / Decimal("100")
        parts_markup = Decimal(str(work_order.parts_markup_percent or 0)) / Decimal("100")

        billable_labor = labor_cost * (Decimal("1") + labor_markup)
        billable_parts = parts_cost * (Decimal("1") + parts_markup)

        # Use work order's billable_amount if set, otherwise calculate
        if work_order.billable_amount:
            billable_amount = Decimal(str(work_order.billable_amount))
        else:
            billable_amount = billable_labor + billable_parts

        if billable_amount <= 0 and labor_cost <= 0 and parts_cost <= 0:
            logger.info(f"Work order {work_order.id} has no billable amount or costs")
            return None

        # Get VAT rate from company
        company = self.db.query(Company).filter(Company.id == self.company_id).first()
        vat_rate = Decimal(str(company.default_vat_rate or 0)) / Decimal("100") if company else Decimal("0")

        # Calculate VAT on billable amount
        vat_amount = billable_amount * vat_rate
        total_receivable = billable_amount + vat_amount

        # Get account mappings
        revenue_mapping = self._get_mapping("work_order_revenue")
        ar_mapping = self._get_mapping("accounts_receivable")
        vat_output_mapping = self._get_mapping("vat_output")
        labor_cogs_mapping = self._get_mapping("work_order_labor_cogs") or self._get_mapping("work_order_labor")
        parts_cogs_mapping = self._get_mapping("work_order_parts_cogs") or self._get_mapping("work_order_parts")

        if not revenue_mapping and not ar_mapping:
            logger.warning("No account mappings for work order billing (revenue/AR)")
            return None

        # ============================================
        # COST CENTER DETERMINATION
        # ============================================
        # Priority: Site's AddressBook -> Client's AddressBook -> Contract -> Default P&L Business Unit
        # This ensures costs are properly allocated to the correct cost center
        #
        # In JDE-style accounting, Business Unit (BU) is the primary cost center dimension.
        # Each site/client can have its own BU for P&L tracking.
        business_unit_id = None

        # 1. Try to get business unit from site's address book (site = cost center)
        if site_id:
            site = self.db.query(Site).filter(Site.id == site_id).first()
            if site and site.address_book_id:
                site_ab = self.db.query(AddressBook).filter(AddressBook.id == site.address_book_id).first()
                if site_ab and site_ab.business_unit_id:
                    business_unit_id = site_ab.business_unit_id
                    logger.debug(f"Using site address book business unit: {business_unit_id}")

        # 2. Try client's address book if no site BU
        if not business_unit_id and client_address_book_id:
            client_ab = self.db.query(AddressBook).filter(AddressBook.id == client_address_book_id).first()
            if client_ab and client_ab.business_unit_id:
                business_unit_id = client_ab.business_unit_id
                logger.debug(f"Using client address book business unit: {business_unit_id}")

        # 3. Try contract's address book
        if not business_unit_id and contract_id:
            contract = self.db.query(Contract).filter(Contract.id == contract_id).first()
            if contract and contract.address_book_id:
                contract_ab = self.db.query(AddressBook).filter(AddressBook.id == contract.address_book_id).first()
                if contract_ab and contract_ab.business_unit_id:
                    business_unit_id = contract_ab.business_unit_id
                    logger.debug(f"Using contract address book business unit: {business_unit_id}")

        # 4. Fall back to default P&L business unit
        if not business_unit_id:
            business_unit_id = self._get_default_business_unit("profit_loss")
            logger.debug(f"Using default P&L business unit: {business_unit_id}")

        # Create journal entry
        entry_date = work_order.approved_at.date() if work_order.approved_at else date.today()
        fiscal_period = self._get_fiscal_period(entry_date)

        entry = JournalEntry(
            company_id=self.company_id,
            entry_number=self._generate_entry_number(),
            entry_date=entry_date,
            description=f"Work Order Billing - {work_order.wo_number} - {work_order.title or 'Services'}",
            reference=work_order.wo_number,
            source_type="work_order_billing",
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

        # ============================================
        # REVENUE RECOGNITION - Charge to Client
        # ============================================

        # DR: Accounts Receivable (total amount including VAT)
        ar_account_id = ar_mapping.debit_account_id if ar_mapping else None
        if ar_account_id and total_receivable > 0:
            ar_line = JournalEntryLine(
                journal_entry_id=entry.id,
                account_id=ar_account_id,
                debit=float(total_receivable),
                credit=0,
                description=f"Accounts Receivable - {client_name} - WO {work_order.wo_number}",
                site_id=site_id,
                contract_id=contract_id,
                work_order_id=work_order.id,
                project_id=project_id,
                address_book_id=client_address_book_id,
                business_unit_id=business_unit_id,
                line_number=line_number
            )
            self.db.add(ar_line)
            lines.append(ar_line)
            line_number += 1

        # CR: Service Revenue (net of VAT)
        revenue_account_id = revenue_mapping.credit_account_id if revenue_mapping else None
        if revenue_account_id and billable_amount > 0:
            revenue_line = JournalEntryLine(
                journal_entry_id=entry.id,
                account_id=revenue_account_id,
                debit=0,
                credit=float(billable_amount),
                description=f"Service Revenue - WO {work_order.wo_number}",
                site_id=site_id,
                contract_id=contract_id,
                work_order_id=work_order.id,
                project_id=project_id,
                address_book_id=client_address_book_id,
                business_unit_id=business_unit_id,
                line_number=line_number
            )
            self.db.add(revenue_line)
            lines.append(revenue_line)
            line_number += 1

        # CR: VAT Output (if applicable)
        vat_account_id = vat_output_mapping.credit_account_id if vat_output_mapping else None
        if vat_account_id and vat_amount > 0:
            vat_line = JournalEntryLine(
                journal_entry_id=entry.id,
                account_id=vat_account_id,
                debit=0,
                credit=float(vat_amount),
                description=f"VAT Output - WO {work_order.wo_number}",
                site_id=site_id,
                work_order_id=work_order.id,
                project_id=project_id,
                business_unit_id=business_unit_id,
                line_number=line_number
            )
            self.db.add(vat_line)
            lines.append(vat_line)
            line_number += 1

        # ============================================
        # COST RECOGNITION - Labor COGS
        # ============================================
        if labor_cost > 0 and labor_cogs_mapping:
            # DR: Cost of Goods Sold - Labor
            if labor_cogs_mapping.debit_account_id:
                labor_cogs_line = JournalEntryLine(
                    journal_entry_id=entry.id,
                    account_id=labor_cogs_mapping.debit_account_id,
                    debit=float(labor_cost),
                    credit=0,
                    description=f"COGS - Labor - WO {work_order.wo_number}",
                    site_id=site_id,
                    contract_id=contract_id,
                    work_order_id=work_order.id,
                    project_id=project_id,
                    business_unit_id=business_unit_id,
                    line_number=line_number
                )
                self.db.add(labor_cogs_line)
                lines.append(labor_cogs_line)
                line_number += 1

            # CR: Accrued Labor / Labor Payable
            if labor_cogs_mapping.credit_account_id:
                labor_payable_line = JournalEntryLine(
                    journal_entry_id=entry.id,
                    account_id=labor_cogs_mapping.credit_account_id,
                    debit=0,
                    credit=float(labor_cost),
                    description=f"Labor Payable - WO {work_order.wo_number}",
                    site_id=site_id,
                    work_order_id=work_order.id,
                    project_id=project_id,
                    business_unit_id=business_unit_id,
                    line_number=line_number
                )
                self.db.add(labor_payable_line)
                lines.append(labor_payable_line)
                line_number += 1

        # ============================================
        # COST RECOGNITION - Parts/Inventory COGS
        # ============================================
        if parts_cost > 0 and parts_cogs_mapping:
            # DR: Cost of Goods Sold - Parts
            if parts_cogs_mapping.debit_account_id:
                parts_cogs_line = JournalEntryLine(
                    journal_entry_id=entry.id,
                    account_id=parts_cogs_mapping.debit_account_id,
                    debit=float(parts_cost),
                    credit=0,
                    description=f"COGS - Parts/Materials - WO {work_order.wo_number}",
                    site_id=site_id,
                    contract_id=contract_id,
                    work_order_id=work_order.id,
                    project_id=project_id,
                    business_unit_id=business_unit_id,
                    line_number=line_number
                )
                self.db.add(parts_cogs_line)
                lines.append(parts_cogs_line)
                line_number += 1

            # CR: Inventory
            if parts_cogs_mapping.credit_account_id:
                inventory_line = JournalEntryLine(
                    journal_entry_id=entry.id,
                    account_id=parts_cogs_mapping.credit_account_id,
                    debit=0,
                    credit=float(parts_cost),
                    description=f"Inventory Relief - WO {work_order.wo_number}",
                    site_id=site_id,
                    work_order_id=work_order.id,
                    project_id=project_id,
                    business_unit_id=business_unit_id,
                    line_number=line_number
                )
                self.db.add(inventory_line)
                lines.append(inventory_line)
                line_number += 1

        # Update totals
        entry.total_debit = sum(float(l.debit) for l in lines)
        entry.total_credit = sum(float(l.credit) for l in lines)

        # Update work order with calculated amounts
        work_order.actual_labor_cost = float(labor_cost)
        work_order.actual_parts_cost = float(parts_cost)
        work_order.actual_total_cost = float(labor_cost + parts_cost)
        work_order.billable_amount = float(billable_amount)
        work_order.billing_status = "pending"  # Mark as pending invoice/payment

        if post_immediately:
            entry.status = "posted"
            entry.posted_at = datetime.utcnow()
            entry.posted_by = self.user_id
            self._update_account_balance(entry)

        self.db.commit()
        logger.info(f"Created billing journal entry {entry.entry_number} for work order {work_order.id} - "
                   f"Revenue: {billable_amount}, VAT: {vat_amount}, Labor COGS: {labor_cost}, Parts COGS: {parts_cost}")

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

    def _get_exchange_rate(self, from_currency: str, to_currency: str) -> Decimal:
        """
        Get exchange rate between two currencies.
        Returns 1 if same currency or rate not found (fallback).
        """
        if from_currency.upper() == to_currency.upper():
            return Decimal("1")

        # Check for manual rate in database
        rate = self.db.query(ExchangeRate).filter(
            ExchangeRate.company_id == self.company_id,
            ExchangeRate.from_currency == from_currency.upper(),
            ExchangeRate.to_currency == to_currency.upper(),
            ExchangeRate.is_active == True
        ).first()

        if rate:
            return rate.rate

        # Fallback to 1 if no rate found
        logger.warning(f"No exchange rate found for {from_currency}/{to_currency}, using 1:1")
        return Decimal("1")

    def _get_company_currency(self) -> str:
        """Get the company's primary currency"""
        company = self.db.query(Company).filter(Company.id == self.company_id).first()
        return company.primary_currency if company and company.primary_currency else "USD"

    def post_po_receiving(
        self,
        po: PurchaseOrder,
        line: PurchaseOrderLine,
        quantity_received: Decimal,
        ledger_entry: ItemLedger,
        post_immediately: bool = True
    ) -> Optional[JournalEntry]:
        """
        Create journal entry when goods are received from a Purchase Order.

        Accounting entries:
        - DR: Inventory (asset increases)
        - CR: Accounts Payable or Goods Received Not Invoiced (liability)

        Handles:
        - Currency conversion if PO currency differs from company currency
        - Tax/VAT if applicable
        """
        # Get account mapping
        mapping = self._get_mapping("po_receive_inventory")
        if not mapping:
            # Try fallback mapping
            mapping = self._get_mapping("inventory_increase")

        if not mapping:
            logger.warning("No account mapping for po_receive_inventory")
            return None

        # Calculate amounts
        unit_cost = line.unit_price or Decimal("0")
        line_total = quantity_received * unit_cost

        # Currency conversion
        company_currency = self._get_company_currency()
        po_currency = po.currency or "USD"

        if po_currency != company_currency:
            exchange_rate = self._get_exchange_rate(po_currency, company_currency)
            line_total_base = line_total * exchange_rate
            exchange_gain_loss = line_total_base - line_total
        else:
            line_total_base = line_total
            exchange_gain_loss = Decimal("0")

        # Calculate proportional tax
        tax_amount = Decimal("0")
        if po.tax_amount and po.subtotal and po.subtotal > 0:
            tax_rate = po.tax_amount / po.subtotal
            tax_amount = line_total * tax_rate
            if po_currency != company_currency:
                tax_amount = tax_amount * exchange_rate

        # Get business_unit_id from ledger entry's warehouse (inventory is balance sheet)
        business_unit_id = self._get_business_unit_from_warehouse(ledger_entry.to_warehouse_id)
        if not business_unit_id:
            # Fall back to default balance sheet BU for inventory
            business_unit_id = self._get_default_business_unit("balance_sheet")

        # Create journal entry
        entry_date = date.today()
        fiscal_period = self._get_fiscal_period(entry_date)

        entry = JournalEntry(
            company_id=self.company_id,
            entry_number=self._generate_entry_number(),
            entry_date=entry_date,
            description=f"PO Receiving - {po.po_number} - {line.description or line.item_number}",
            reference=ledger_entry.transaction_number,
            source_type="po_receive",
            source_id=ledger_entry.id,
            source_number=po.po_number,
            fiscal_period_id=fiscal_period.id if fiscal_period else None,
            status="draft",
            is_auto_generated=True,
            created_by=self.user_id
        )
        self.db.add(entry)
        self.db.flush()

        lines = []
        line_number = 1

        # Debit: Inventory account (asset increases)
        if mapping.debit_account_id:
            inv_line = JournalEntryLine(
                journal_entry_id=entry.id,
                account_id=mapping.debit_account_id,
                debit=float(line_total_base),
                credit=0,
                description=f"Inventory - {line.description or line.item_number} x {quantity_received}",
                address_book_id=po.address_book_id,
                work_order_id=po.work_order_id,
                contract_id=po.contract_id,
                line_number=line_number,
                business_unit_id=business_unit_id
            )
            self.db.add(inv_line)
            lines.append(inv_line)
            line_number += 1

        # Debit: VAT Input (if applicable)
        if tax_amount > 0:
            vat_mapping = self._get_mapping("po_receive_vat")
            if vat_mapping and vat_mapping.debit_account_id:
                vat_line = JournalEntryLine(
                    journal_entry_id=entry.id,
                    account_id=vat_mapping.debit_account_id,
                    debit=float(tax_amount),
                    credit=0,
                    description="VAT Input - PO Receiving",
                    address_book_id=po.address_book_id,
                    line_number=line_number,
                    business_unit_id=business_unit_id
                )
                self.db.add(vat_line)
                lines.append(vat_line)
                line_number += 1

        # Credit: Accounts Payable / Goods Received Not Invoiced
        total_credit = float(line_total_base + tax_amount)
        if mapping.credit_account_id:
            payable_line = JournalEntryLine(
                journal_entry_id=entry.id,
                account_id=mapping.credit_account_id,
                debit=0,
                credit=total_credit,
                description=f"Payable for PO {po.po_number}",
                address_book_id=po.address_book_id,
                line_number=line_number,
                business_unit_id=business_unit_id
            )
            self.db.add(payable_line)
            lines.append(payable_line)
            line_number += 1

        # Handle exchange gain/loss if applicable
        if exchange_gain_loss != Decimal("0"):
            fx_mapping = self._get_mapping("exchange_gain_loss")
            if fx_mapping:
                fx_account_id = fx_mapping.debit_account_id if exchange_gain_loss > 0 else fx_mapping.credit_account_id
                if fx_account_id:
                    fx_line = JournalEntryLine(
                        journal_entry_id=entry.id,
                        account_id=fx_account_id,
                        debit=float(exchange_gain_loss) if exchange_gain_loss > 0 else 0,
                        credit=float(abs(exchange_gain_loss)) if exchange_gain_loss < 0 else 0,
                        description=f"Exchange {'gain' if exchange_gain_loss > 0 else 'loss'} on PO {po.po_number}",
                        line_number=line_number,
                        business_unit_id=business_unit_id
                    )
                    self.db.add(fx_line)
                    lines.append(fx_line)

        # Update totals
        entry.total_debit = sum(float(l.debit) for l in lines)
        entry.total_credit = sum(float(l.credit) for l in lines)

        if post_immediately:
            entry.status = "posted"
            entry.posted_at = datetime.utcnow()
            entry.posted_by = self.user_id
            self._update_account_balance(entry)

        self.db.commit()
        logger.info(f"Created journal entry {entry.entry_number} for PO receiving {po.po_number}")

        return entry

    def post_stock_adjustment(
        self,
        ledger_entry: ItemLedger,
        item: ItemMaster,
        adjustment_type: str,  # 'plus' or 'minus'
        reason: Optional[str] = None,
        post_immediately: bool = True
    ) -> Optional[JournalEntry]:
        """
        Create journal entry for stock adjustment.

        For ADJUSTMENT_PLUS (increase):
        - DR: Inventory (asset increases)
        - CR: Inventory Adjustment Expense/Income

        For ADJUSTMENT_MINUS (decrease):
        - DR: Inventory Adjustment Expense
        - CR: Inventory (asset decreases)
        """
        mapping_type = "stock_adjustment_plus" if adjustment_type == "plus" else "stock_adjustment_minus"
        mapping = self._get_mapping(mapping_type)

        if not mapping:
            # Try generic adjustment mapping
            mapping = self._get_mapping("stock_adjustment")

        if not mapping:
            logger.warning(f"No account mapping for {mapping_type}")
            return None

        quantity = abs(float(ledger_entry.quantity))
        unit_cost = float(ledger_entry.unit_cost or 0)
        total_cost = float(ledger_entry.total_cost or (quantity * unit_cost))

        if total_cost == 0:
            logger.info(f"Skipping journal entry for zero-cost adjustment {ledger_entry.transaction_number}")
            return None

        # Get business_unit_id from ledger entry's warehouse
        warehouse_id = ledger_entry.to_warehouse_id or ledger_entry.from_warehouse_id
        business_unit_id = self._get_business_unit_from_warehouse(warehouse_id)
        if not business_unit_id:
            business_unit_id = self._get_default_business_unit("balance_sheet")

        # Create journal entry
        entry_date = ledger_entry.transaction_date.date() if ledger_entry.transaction_date else date.today()
        fiscal_period = self._get_fiscal_period(entry_date)

        entry = JournalEntry(
            company_id=self.company_id,
            entry_number=self._generate_entry_number(),
            entry_date=entry_date,
            description=f"Stock Adjustment - {item.item_number} - {reason or adjustment_type.upper()}",
            reference=ledger_entry.transaction_number,
            source_type="stock_adjustment",
            source_id=ledger_entry.id,
            source_number=ledger_entry.transaction_number,
            fiscal_period_id=fiscal_period.id if fiscal_period else None,
            status="draft",
            is_auto_generated=True,
            created_by=self.user_id
        )
        self.db.add(entry)
        self.db.flush()

        lines = []
        line_number = 1

        if adjustment_type == "plus":
            # DR: Inventory (asset increases)
            if mapping.debit_account_id:
                inv_line = JournalEntryLine(
                    journal_entry_id=entry.id,
                    account_id=mapping.debit_account_id,
                    debit=total_cost,
                    credit=0,
                    description=f"Inventory increase - {item.item_number} x {quantity}",
                    line_number=line_number,
                    business_unit_id=business_unit_id
                )
                self.db.add(inv_line)
                lines.append(inv_line)
                line_number += 1

            # CR: Adjustment account
            if mapping.credit_account_id:
                adj_line = JournalEntryLine(
                    journal_entry_id=entry.id,
                    account_id=mapping.credit_account_id,
                    debit=0,
                    credit=total_cost,
                    description=f"Stock adjustment gain - {reason or 'inventory adjustment'}",
                    line_number=line_number,
                    business_unit_id=business_unit_id
                )
                self.db.add(adj_line)
                lines.append(adj_line)
        else:
            # DR: Adjustment/Expense account
            if mapping.debit_account_id:
                adj_line = JournalEntryLine(
                    journal_entry_id=entry.id,
                    account_id=mapping.debit_account_id,
                    debit=total_cost,
                    credit=0,
                    description=f"Stock adjustment loss - {reason or 'inventory adjustment'}",
                    line_number=line_number,
                    business_unit_id=business_unit_id
                )
                self.db.add(adj_line)
                lines.append(adj_line)
                line_number += 1

            # CR: Inventory (asset decreases)
            if mapping.credit_account_id:
                inv_line = JournalEntryLine(
                    journal_entry_id=entry.id,
                    account_id=mapping.credit_account_id,
                    debit=0,
                    credit=total_cost,
                    description=f"Inventory decrease - {item.item_number} x {quantity}",
                    line_number=line_number,
                    business_unit_id=business_unit_id
                )
                self.db.add(inv_line)
                lines.append(inv_line)

        # Update totals
        entry.total_debit = sum(float(l.debit) for l in lines)
        entry.total_credit = sum(float(l.credit) for l in lines)

        if post_immediately:
            entry.status = "posted"
            entry.posted_at = datetime.utcnow()
            entry.posted_by = self.user_id
            self._update_account_balance(entry)

        self.db.commit()
        logger.info(f"Created journal entry {entry.entry_number} for stock adjustment {ledger_entry.transaction_number}")

        return entry

    def post_cycle_count_adjustment(
        self,
        ledger_entry: ItemLedger,
        item: ItemMaster,
        adjustment_type: str,  # 'plus' or 'minus'
        cycle_count_number: str,
        post_immediately: bool = True
    ) -> Optional[JournalEntry]:
        """
        Create journal entry for cycle count variance adjustment.
        Uses same logic as stock adjustment but with different description.
        """
        mapping_type = "cycle_count_plus" if adjustment_type == "plus" else "cycle_count_minus"
        mapping = self._get_mapping(mapping_type)

        if not mapping:
            # Fall back to stock adjustment mapping
            mapping_type = "stock_adjustment_plus" if adjustment_type == "plus" else "stock_adjustment_minus"
            mapping = self._get_mapping(mapping_type)

        if not mapping:
            mapping = self._get_mapping("stock_adjustment")

        if not mapping:
            logger.warning(f"No account mapping for cycle count adjustment")
            return None

        quantity = abs(float(ledger_entry.quantity))
        unit_cost = float(ledger_entry.unit_cost or 0)
        total_cost = float(ledger_entry.total_cost or (quantity * unit_cost))

        if total_cost == 0:
            logger.info(f"Skipping journal entry for zero-cost cycle count {ledger_entry.transaction_number}")
            return None

        # Get business_unit_id from ledger entry's warehouse
        warehouse_id = ledger_entry.to_warehouse_id or ledger_entry.from_warehouse_id
        business_unit_id = self._get_business_unit_from_warehouse(warehouse_id)
        if not business_unit_id:
            business_unit_id = self._get_default_business_unit("balance_sheet")

        # Create journal entry
        entry_date = ledger_entry.transaction_date.date() if ledger_entry.transaction_date else date.today()
        fiscal_period = self._get_fiscal_period(entry_date)

        entry = JournalEntry(
            company_id=self.company_id,
            entry_number=self._generate_entry_number(),
            entry_date=entry_date,
            description=f"Cycle Count Adjustment - {cycle_count_number} - {item.item_number}",
            reference=ledger_entry.transaction_number,
            source_type="cycle_count",
            source_id=ledger_entry.id,
            source_number=cycle_count_number,
            fiscal_period_id=fiscal_period.id if fiscal_period else None,
            status="draft",
            is_auto_generated=True,
            created_by=self.user_id
        )
        self.db.add(entry)
        self.db.flush()

        lines = []
        line_number = 1

        if adjustment_type == "plus":
            # Inventory gain
            if mapping.debit_account_id:
                inv_line = JournalEntryLine(
                    journal_entry_id=entry.id,
                    account_id=mapping.debit_account_id,
                    debit=total_cost,
                    credit=0,
                    description=f"Inventory gain - {item.item_number} x {quantity}",
                    line_number=line_number,
                    business_unit_id=business_unit_id
                )
                self.db.add(inv_line)
                lines.append(inv_line)
                line_number += 1

            if mapping.credit_account_id:
                adj_line = JournalEntryLine(
                    journal_entry_id=entry.id,
                    account_id=mapping.credit_account_id,
                    debit=0,
                    credit=total_cost,
                    description=f"Cycle count variance gain - {cycle_count_number}",
                    line_number=line_number,
                    business_unit_id=business_unit_id
                )
                self.db.add(adj_line)
                lines.append(adj_line)
        else:
            # Inventory loss
            if mapping.debit_account_id:
                adj_line = JournalEntryLine(
                    journal_entry_id=entry.id,
                    account_id=mapping.debit_account_id,
                    debit=total_cost,
                    credit=0,
                    description=f"Cycle count variance loss - {cycle_count_number}",
                    line_number=line_number,
                    business_unit_id=business_unit_id
                )
                self.db.add(adj_line)
                lines.append(adj_line)
                line_number += 1

            if mapping.credit_account_id:
                inv_line = JournalEntryLine(
                    journal_entry_id=entry.id,
                    account_id=mapping.credit_account_id,
                    debit=0,
                    credit=total_cost,
                    description=f"Inventory loss - {item.item_number} x {quantity}",
                    line_number=line_number,
                    business_unit_id=business_unit_id
                )
                self.db.add(inv_line)
                lines.append(inv_line)

        # Update totals
        entry.total_debit = sum(float(l.debit) for l in lines)
        entry.total_credit = sum(float(l.credit) for l in lines)

        if post_immediately:
            entry.status = "posted"
            entry.posted_at = datetime.utcnow()
            entry.posted_by = self.user_id
            self._update_account_balance(entry)

        self.db.commit()
        logger.info(f"Created journal entry {entry.entry_number} for cycle count {cycle_count_number}")

        return entry

    def post_goods_receipt(
        self,
        grn,  # GoodsReceipt object
        post_immediately: bool = True
    ) -> Optional[JournalEntry]:
        """
        Create journal entry for Goods Receipt Note (GRN).

        Standard receiving entry:
        - DR: Inventory (asset increases) - uses landed cost if available
        - DR: VAT Input (if applicable)
        - CR: Goods Received Not Invoiced (GRNI) or Accounts Payable - for invoice amount
        - CR: Accounts Payable (or specific accounts) - for each extra cost

        For imports with extra costs (landed cost):
        - Inventory is debited with landed cost (invoice + allocated extra costs)
        - GRNI credited for invoice amount
        - Separate credit entries for each extra cost (freight, duty, etc.)

        This is similar to post_po_receiving but for the new GRN system.
        """
        # Import here to avoid circular imports
        from app.models import GoodsReceipt, GoodsReceiptLine

        # Get mappings
        mapping = self._get_mapping("po_receive_inventory")
        if not mapping:
            mapping = self._get_mapping("inventory_increase")

        if not mapping:
            logger.warning("No account mapping for goods receipt")
            return None

        vat_mapping = self._get_mapping("po_receive_vat")

        # Calculate totals - use landed cost if available
        total_invoice_value = float(grn.subtotal or 0)
        total_extra_costs = float(grn.total_extra_costs or 0)
        tax_amount = float(grn.tax_amount or 0)

        # Total inventory value = invoice + extra costs (landed cost)
        total_inventory_value = total_invoice_value + total_extra_costs
        total_invoice_with_tax = total_invoice_value + tax_amount

        if total_invoice_value == 0:
            logger.info(f"Skipping journal entry for zero-value GRN {grn.grn_number}")
            return None

        # Handle exchange rate for multi-currency
        exchange_rate = float(grn.exchange_rate or 1.0)
        if grn.currency != 'USD':  # Assuming USD is base currency
            rate = self._get_exchange_rate(grn.currency, 'USD')
            if rate:
                exchange_rate = rate

        total_invoice_value_base = total_invoice_value * exchange_rate
        total_extra_costs_base = total_extra_costs * exchange_rate
        tax_amount_base = tax_amount * exchange_rate
        total_invoice_with_tax_base = total_invoice_with_tax * exchange_rate

        # Create journal entry
        po = grn.purchase_order
        vendor_name = po.address_book.alpha_name if po and po.address_book else "Unknown Vendor"

        # Get business_unit_id from warehouse (inventory is balance sheet)
        business_unit_id = self._get_business_unit_from_warehouse(grn.warehouse_id)
        if not business_unit_id:
            # Fall back to default balance sheet BU for inventory
            business_unit_id = self._get_default_business_unit("balance_sheet")

        # Get site_id and contract_id from linked PO/work order
        site_id = None
        contract_id = po.contract_id if po else None
        work_order_id = po.work_order_id if po else None

        # If PO is linked to a work order, get site_id from the work order
        if work_order_id:
            from app.models import WorkOrder
            work_order = self.db.query(WorkOrder).filter(WorkOrder.id == work_order_id).first()
            if work_order:
                site_id = work_order.site_id
                if not contract_id:
                    contract_id = work_order.contract_id

        entry_date = grn.receipt_date or date.today()
        fiscal_period = self._get_fiscal_period(entry_date)

        # Build description
        description = f"Goods Receipt - {grn.grn_number} from {vendor_name}"
        if grn.is_import and total_extra_costs > 0:
            description += f" (Import with landed costs)"

        entry = JournalEntry(
            company_id=self.company_id,
            entry_number=self._generate_entry_number(),
            entry_date=entry_date,
            description=description,
            reference=grn.grn_number,
            source_type="goods_receipt",
            source_id=grn.id,
            source_number=grn.grn_number,
            fiscal_period_id=fiscal_period.id if fiscal_period else None,
            status="draft",
            is_auto_generated=True,
            created_by=self.user_id
        )
        self.db.add(entry)
        self.db.flush()

        lines = []
        line_number = 1

        # Create line for each GRN line item - use landed cost if available
        for grn_line in grn.lines:
            # Use landed total cost if available, otherwise use invoice total
            if grn_line.landed_total_cost and float(grn_line.landed_total_cost) > 0:
                line_value = float(grn_line.landed_total_cost)
            else:
                line_value = float(grn_line.total_price or 0)

            if line_value == 0:
                continue

            line_value_base = line_value * exchange_rate

            # DR: Inventory (at landed cost)
            if mapping.debit_account_id:
                qty = float(grn_line.quantity_accepted or grn_line.quantity_received or 0)
                allocated_extra = float(grn_line.allocated_extra_cost or 0)
                desc = f"{grn_line.item_code or 'Item'}: {grn_line.item_description or ''} x {qty}"
                if allocated_extra > 0:
                    desc += f" (incl. landed costs: {allocated_extra:.2f})"

                inv_line = JournalEntryLine(
                    journal_entry_id=entry.id,
                    account_id=mapping.debit_account_id,
                    debit=Decimal(str(round(line_value_base, 2))),
                    credit=Decimal('0'),
                    description=desc,
                    line_number=line_number,
                    address_book_id=po.address_book_id if po else None,
                    business_unit_id=business_unit_id,
                    site_id=site_id,
                    contract_id=contract_id,
                    work_order_id=work_order_id
                )
                self.db.add(inv_line)
                lines.append(inv_line)
                line_number += 1

        # DR: VAT Input (if applicable) - on invoice amount only
        if tax_amount_base > 0 and vat_mapping and vat_mapping.debit_account_id:
            vat_line = JournalEntryLine(
                journal_entry_id=entry.id,
                account_id=vat_mapping.debit_account_id,
                debit=Decimal(str(round(tax_amount_base, 2))),
                credit=Decimal('0'),
                description=f"VAT on GRN {grn.grn_number}",
                line_number=line_number,
                address_book_id=po.address_book_id if po else None,
                business_unit_id=business_unit_id,
                site_id=site_id,
                contract_id=contract_id,
                work_order_id=work_order_id
            )
            self.db.add(vat_line)
            lines.append(vat_line)
            line_number += 1

        # CR: GRNI or Accounts Payable - for invoice amount only
        grni_mapping = self._get_mapping("grni") or self._get_mapping("accounts_payable")
        credit_account_id = grni_mapping.credit_account_id if grni_mapping else mapping.credit_account_id

        if credit_account_id:
            ap_line = JournalEntryLine(
                journal_entry_id=entry.id,
                account_id=credit_account_id,
                debit=Decimal('0'),
                credit=Decimal(str(round(total_invoice_with_tax_base, 2))),
                description=f"GRNI for {grn.grn_number} - PO {po.po_number if po else 'N/A'}",
                line_number=line_number,
                address_book_id=po.address_book_id if po else None,
                business_unit_id=business_unit_id,
                site_id=site_id,
                contract_id=contract_id,
                work_order_id=work_order_id
            )
            self.db.add(ap_line)
            lines.append(ap_line)
            line_number += 1

        # CR: Extra costs - separate entry for each extra cost
        if hasattr(grn, 'extra_costs') and grn.extra_costs:
            for extra_cost in grn.extra_costs:
                cost_amount = float(extra_cost.amount or 0)
                if cost_amount == 0:
                    continue

                cost_amount_base = cost_amount * exchange_rate

                # Map cost type to transaction type for account lookup
                cost_type_mapping = {
                    'freight': 'landed_cost_freight',
                    'duty': 'landed_cost_duty',
                    'port_handling': 'landed_cost_port_handling',
                    'customs': 'landed_cost_customs',
                    'insurance': 'landed_cost_insurance',
                    'other': 'landed_cost_other'
                }

                mapping_key = cost_type_mapping.get(extra_cost.cost_type, 'landed_cost_other')
                extra_cost_mapping = self._get_mapping(mapping_key)

                # Fall back to accounts payable if no specific mapping
                if not extra_cost_mapping:
                    extra_cost_mapping = self._get_mapping("accounts_payable")

                if extra_cost_mapping:
                    extra_credit_account = extra_cost_mapping.credit_account_id
                else:
                    extra_credit_account = credit_account_id  # Use same as GRNI

                if extra_credit_account:
                    cost_type_label = extra_cost.cost_description or extra_cost.cost_type.replace('_', ' ').title()
                    extra_cost_line = JournalEntryLine(
                        journal_entry_id=entry.id,
                        account_id=extra_credit_account,
                        debit=Decimal('0'),
                        credit=Decimal(str(round(cost_amount_base, 2))),
                        description=f"{cost_type_label}: {extra_cost.reference_number or grn.grn_number}",
                        line_number=line_number,
                        address_book_id=getattr(extra_cost, 'address_book_id', None) or (po.address_book_id if po else None),
                        business_unit_id=business_unit_id,
                        site_id=site_id,
                        contract_id=contract_id,
                        work_order_id=work_order_id
                    )
                    self.db.add(extra_cost_line)
                    lines.append(extra_cost_line)
                    line_number += 1

        # Handle exchange difference if applicable
        if grn.currency != 'USD' and exchange_rate != 1.0:
            exchange_mapping = self._get_mapping("exchange_gain_loss")
            if exchange_mapping:
                # Calculate any rounding difference
                total_debits = sum(float(l.debit) for l in lines)
                total_credits = sum(float(l.credit) for l in lines)
                diff = abs(total_debits - total_credits)

                if diff > 0.01:
                    fx_account_id = exchange_mapping.debit_account_id if total_credits > total_debits else exchange_mapping.credit_account_id
                    if fx_account_id:
                        fx_line = JournalEntryLine(
                            journal_entry_id=entry.id,
                            account_id=fx_account_id,
                            debit=Decimal(str(diff)) if total_credits > total_debits else Decimal('0'),
                            credit=Decimal('0') if total_credits > total_debits else Decimal(str(diff)),
                            description=f"Exchange difference on GRN {grn.grn_number}",
                            line_number=line_number,
                            business_unit_id=business_unit_id
                        )
                        self.db.add(fx_line)
                        lines.append(fx_line)

        # Update totals
        entry.total_debit = sum(float(l.debit) for l in lines)
        entry.total_credit = sum(float(l.credit) for l in lines)

        if post_immediately:
            entry.status = "posted"
            entry.posted_at = datetime.utcnow()
            entry.posted_by = self.user_id
            self._update_account_balance(entry)

        self.db.commit()
        logger.info(f"Created journal entry {entry.entry_number} for GRN {grn.grn_number}")

        return entry
