"""
Accounting Engine - Double-Entry Bookkeeping Service
Handles automatic journal entry posting for all financial transactions.
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from .accounting_models import (
    ChartOfAccount, JournalEntry, JournalEntryLine, AccountingPeriod,
    ExpenseAccountMapping, FixedAsset, AssetDepreciationSchedule
)
from .models import Sale, SaleItem, Payment, Product, Withdrawal

logger = logging.getLogger(__name__)


class AccountingEngine:
    """Core accounting engine for double-entry bookkeeping."""

    def __init__(self, db: Session):
        self.db = db

    def get_account_by_code(self, code: str) -> Optional[ChartOfAccount]:
        """Get account by code."""
        return self.db.query(ChartOfAccount).filter(
            ChartOfAccount.code == code,
            ChartOfAccount.is_active == True
        ).first()

    def get_or_create_period(self, date: datetime) -> AccountingPeriod:
        """Get or create accounting period for a given date."""
        period_name = date.strftime("%Y-%m")
        period = self.db.query(AccountingPeriod).filter(
            AccountingPeriod.period_name == period_name
        ).first()

        if not period:
            # Create period
            start_date = date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if date.month == 12:
                end_date = date.replace(year=date.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                end_date = date.replace(month=date.month + 1, day=1) - timedelta(days=1)
            end_date = end_date.replace(hour=23, minute=59, second=59)

            period = AccountingPeriod(
                period_name=period_name,
                start_date=start_date,
                end_date=end_date,
                is_locked=False
            )
            self.db.add(period)
            self.db.flush()
            logger.info(f"Created new accounting period: {period_name}")

        return period

    def generate_entry_number(self, date: datetime) -> str:
        """Generate unique journal entry number."""
        year = date.year
        # Get last entry number for this year
        last_entry = self.db.query(JournalEntry).filter(
            func.strftime("%Y", JournalEntry.entry_date) == str(year)
        ).order_by(JournalEntry.id.desc()).first()

        if last_entry and last_entry.entry_number:
            try:
                last_num = int(last_entry.entry_number.split("-")[-1])
                next_num = last_num + 1
            except (ValueError, IndexError):
                next_num = 1
        else:
            next_num = 1

        return f"JE-{year}-{next_num:04d}"

    def create_journal_entry(
        self,
        entry_date: datetime,
        description: str,
        lines: List[Dict],
        reference_type: Optional[str] = None,
        reference_id: Optional[int] = None,
        created_by: int = 1
    ) -> JournalEntry:
        """
        Create a balanced journal entry.
        
        Args:
            entry_date: Transaction date
            description: Entry description
            lines: List of dicts with keys: account_code, debit, credit, description
            reference_type: Type of source transaction (e.g., "SALE", "WITHDRAWAL")
            reference_id: ID of source transaction
            created_by: User ID creating the entry
        
        Returns:
            JournalEntry object
        
        Raises:
            ValueError: If entry is unbalanced
        """
        # Validate lines
        total_debits = sum(Decimal(str(line.get("debit", 0))) for line in lines)
        total_credits = sum(Decimal(str(line.get("credit", 0))) for line in lines)

        if total_debits != total_credits:
            raise ValueError(
                f"Unbalanced journal entry: Debits {total_debits} != Credits {total_credits}"
            )

        if total_debits == 0:
            raise ValueError("Journal entry must have non-zero amounts")

        # Check period is not locked
        period = self.get_or_create_period(entry_date)
        if period.is_locked:
            raise ValueError(f"Accounting period {period.period_name} is locked")

        # Create journal entry
        entry_number = self.generate_entry_number(entry_date)
        journal_entry = JournalEntry(
            entry_number=entry_number,
            entry_date=entry_date,
            description=description,
            reference_type=reference_type,
            reference_id=reference_id,
            period_id=period.id,
            created_by=created_by,
            is_posted=True,
            posted_at=datetime.utcnow(),
            total_debit=total_debits,
            total_credit=total_credits
        )
        self.db.add(journal_entry)
        self.db.flush()

        # Create lines
        for idx, line in enumerate(lines, start=1):
            account = self.get_account_by_code(line["account_code"])
            if not account:
                raise ValueError(f"Account not found: {line['account_code']}")

            entry_line = JournalEntryLine(
                journal_entry_id=journal_entry.id,
                account_id=account.id,
                debit_amount=Decimal(str(line.get("debit", 0))),
                credit_amount=Decimal(str(line.get("credit", 0))),
                description=line.get("description"),
                reference_type=reference_type,
                reference_id=reference_id,
                line_number=idx
            )
            self.db.add(entry_line)

        logger.info(f"Created journal entry {entry_number}: {description}")
        return journal_entry

    def post_sale(self, sale: Sale) -> JournalEntry:
        """
        Post a sale transaction to accounting.
        
        Journal Entries:
        - Dr. Cash/Bank/Mobile Money (based on payment method)
        - Cr. Sales Revenue
        - Cr. Output VAT (if applicable)
        - Dr. COGS
        - Cr. Inventory
        """
        try:
            # Get payment methods and amounts
            # Use relationship if available, otherwise query
            if hasattr(sale, 'payments') and sale.payments:
                payments = sale.payments
            else:
                payments = self.db.query(Payment).filter(Payment.sale_id == sale.id).all()
            
            if not payments:
                raise ValueError(f"No payments found for sale {sale.id}. Cannot create journal entry without payment information.")
            
            # Calculate VAT (15% for Zimbabwe)
            VAT_RATE = Decimal("0.15")
            vat_exclusive_total = sale.total / (1 + VAT_RATE)
            vat_amount = sale.total - vat_exclusive_total

            lines = []
            total_payment_amount = Decimal("0")
            
            # Calculate total payment amount
            for payment in payments:
                total_payment_amount += Decimal(str(payment.amount))
            
            # In accounting, we only record the net amount received (sale total)
            # If customer pays more than sale total, change is given back (reduces cash)
            # So we debit only the sale total amount, not the full payment
            net_amount_received = sale.total
            
            # Allocate the net amount across payment methods proportionally
            if total_payment_amount > 0:
                for payment in payments:
                    payment_amount = Decimal(str(payment.amount))
                    # Calculate proportional share of the net amount
                    payment_share = (payment_amount / total_payment_amount) * net_amount_received
                    account_code = self._get_payment_account_code(payment.method)
                    lines.append({
                        "account_code": account_code,
                        "debit": payment_share,
                        "credit": 0,
                        "description": f"Payment via {payment.method} (net: {payment_share:.2f})"
                    })
            else:
                raise ValueError(f"Total payment amount is zero for sale {sale.id}")
            
            # Validate that total debits match sale total (allow small rounding differences)
            total_debits = sum(Decimal(str(line["debit"])) for line in lines)
            if abs(total_debits - sale.total) > Decimal("0.01"):
                logger.warning(f"Payment debits ({total_debits}) do not match sale total ({sale.total}) for sale {sale.id}. Adjusting...")
                # Adjust the last payment to balance
                if lines:
                    adjustment = sale.total - total_debits
                    lines[-1]["debit"] = Decimal(str(lines[-1]["debit"])) + adjustment

            # 2. Credit Sales Revenue
            lines.append({
                "account_code": "4000",  # Sales Revenue
                "debit": 0,
                "credit": vat_exclusive_total,
                "description": f"Sale #{sale.id}"
            })

            # 3. Credit Output VAT (if applicable)
            if vat_amount > 0:
                lines.append({
                    "account_code": "2200",  # Output VAT
                    "debit": 0,
                    "credit": vat_amount,
                    "description": f"VAT on Sale #{sale.id}"
                })

            # 4. Calculate and post COGS
            # Use relationship if available, otherwise query
            if hasattr(sale, 'items') and sale.items:
                sale_items = sale.items
            else:
                sale_items = self.db.query(SaleItem).filter(SaleItem.sale_id == sale.id).all()
            total_cogs = Decimal("0")

            for item in sale_items:
                product = self.db.get(Product, item.product_id)
                if product:
                    # Weighted Average Cost method
                    cogs_per_unit = product.cost_price
                    cogs_for_item = cogs_per_unit * Decimal(str(item.quantity))
                    total_cogs += cogs_for_item

            # 5. Debit COGS
            if total_cogs > 0:
                lines.append({
                    "account_code": "5000",  # COGS
                    "debit": total_cogs,
                    "credit": 0,
                    "description": f"COGS for Sale #{sale.id}"
                })

                # 6. Credit Inventory
                lines.append({
                    "account_code": "1200",  # Inventory
                    "debit": 0,
                    "credit": total_cogs,
                    "description": f"Inventory reduction for Sale #{sale.id}"
                })

            # Create journal entry
            description = f"Sale #{sale.id} - {len(sale_items)} items"
            journal_entry = self.create_journal_entry(
                entry_date=sale.created_at,
                description=description,
                lines=lines,
                reference_type="SALE",
                reference_id=sale.id,
                created_by=sale.cashier_id
            )

            return journal_entry

        except Exception as e:
            logger.error(f"Error posting sale {sale.id} to accounting: {e}", exc_info=True)
            raise

    def post_withdrawal(self, withdrawal: Withdrawal) -> JournalEntry:
        """
        Post a withdrawal/expense transaction to accounting.
        
        Journal Entries:
        - Dr. Expense Account (based on reason mapping)
        - Cr. Cash
        """
        try:
            # Get expense account for this withdrawal reason
            mapping = self.db.query(ExpenseAccountMapping).filter(
                ExpenseAccountMapping.reason == withdrawal.reason
            ).first()

            if not mapping:
                # Default to "Operating Expenses" if no mapping found
                expense_account = self.get_account_by_code("6000")
                if not expense_account:
                    raise ValueError("Default expense account (6000) not found. Please initialize Chart of Accounts.")
            else:
                expense_account = mapping.account

            lines = [
                {
                    "account_code": expense_account.code,
                    "debit": withdrawal.amount,
                    "credit": 0,
                    "description": f"{withdrawal.reason} - {withdrawal.notes or ''}"
                },
                {
                    "account_code": "1000",  # Cash
                    "debit": 0,
                    "credit": withdrawal.amount,
                    "description": f"Cash withdrawal for {withdrawal.reason}"
                }
            ]

            description = f"Withdrawal #{withdrawal.id} - {withdrawal.reason}"
            journal_entry = self.create_journal_entry(
                entry_date=withdrawal.created_at,
                description=description,
                lines=lines,
                reference_type="WITHDRAWAL",
                reference_id=withdrawal.id,
                created_by=withdrawal.cashier_id
            )

            return journal_entry

        except Exception as e:
            logger.error(f"Error posting withdrawal {withdrawal.id} to accounting: {e}", exc_info=True)
            raise

    def _get_payment_account_code(self, payment_method: str) -> str:
        """Map payment method to account code."""
        mapping = {
            "cash": "1000",  # Cash
            "mobile_money": "1010",  # EcoCash Clearing (default, can be customized)
            "card": "1020",  # Bank Account
            "credit": "1100",  # Accounts Receivable
        }
        return mapping.get(payment_method.lower(), "1000")  # Default to Cash

    def get_account_balance(
        self,
        account_code: str,
        as_of_date: Optional[datetime] = None
    ) -> Decimal:
        """Get account balance (debits - credits) as of a specific date."""
        account = self.get_account_by_code(account_code)
        if not account:
            return Decimal("0")

        query = self.db.query(
            func.sum(JournalEntryLine.debit_amount - JournalEntryLine.credit_amount)
        ).join(JournalEntry).join(ChartOfAccount).filter(
            ChartOfAccount.id == account.id,
            JournalEntry.is_posted == True
        )

        if as_of_date:
            query = query.filter(JournalEntry.entry_date <= as_of_date)

        result = query.scalar()
        return Decimal(str(result or 0))

    def create_fixed_asset(
        self,
        asset_code: str,
        name: str,
        purchase_date: datetime,
        purchase_cost: Decimal,
        useful_life_months: int,
        created_by: int,
        payment_account_code: str = "1000"  # Default to Cash
    ) -> Tuple[FixedAsset, JournalEntry]:
        """
        Create a fixed asset and post the purchase transaction.
        
        Journal Entry:
        - Dr. Fixed Assets (1300)
        - Cr. Cash/Bank (payment account)
        """
        # Check if asset code already exists
        existing = self.db.query(FixedAsset).filter(
            FixedAsset.asset_code == asset_code
        ).first()
        if existing:
            raise ValueError(f"Asset with code {asset_code} already exists")

        # Create asset
        asset = FixedAsset(
            asset_code=asset_code,
            name=name,
            purchase_date=purchase_date,
            purchase_cost=purchase_cost,
            useful_life_months=useful_life_months,
            current_value=purchase_cost,
            created_by=created_by
        )
        self.db.add(asset)
        self.db.flush()

        # Post journal entry
        lines = [
            {
                "account_code": "1300",  # Fixed Assets
                "debit": purchase_cost,
                "credit": 0,
                "description": f"Purchase of {name} (Asset {asset_code})"
            },
            {
                "account_code": payment_account_code,
                "debit": 0,
                "credit": purchase_cost,
                "description": f"Payment for {name} (Asset {asset_code})"
            }
        ]

        journal_entry = self.create_journal_entry(
            entry_date=purchase_date,
            description=f"Fixed Asset Purchase - {name} ({asset_code})",
            lines=lines,
            reference_type="ASSET",
            reference_id=asset.id,
            created_by=created_by
        )

        return asset, journal_entry

    def calculate_depreciation(
        self,
        asset: FixedAsset,
        period: str
    ) -> Decimal:
        """Calculate monthly depreciation using straight-line method."""
        if asset.is_disposed:
            return Decimal("0")

        monthly_depreciation = asset.purchase_cost / Decimal(str(asset.useful_life_months))
        return monthly_depreciation.quantize(Decimal("0.01"))

    def post_depreciation(
        self,
        asset_id: int,
        period: str,
        created_by: int = 1
    ) -> Tuple[AssetDepreciationSchedule, JournalEntry]:
        """
        Post monthly depreciation for a fixed asset.
        
        Journal Entry:
        - Dr. Depreciation Expense (6400)
        - Cr. Accumulated Depreciation (1301)
        """
        asset = self.db.get(FixedAsset, asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found")

        if asset.is_disposed:
            raise ValueError(f"Asset {asset.asset_code} is already disposed")

        # Check if depreciation already posted for this period
        existing = self.db.query(AssetDepreciationSchedule).filter(
            AssetDepreciationSchedule.asset_id == asset_id,
            AssetDepreciationSchedule.period == period
        ).first()
        if existing:
            raise ValueError(f"Depreciation for period {period} already posted for asset {asset.asset_code}")

        # Calculate depreciation
        depreciation_amount = self.calculate_depreciation(asset, period)

        if depreciation_amount <= 0:
            raise ValueError("Depreciation amount must be positive")

        # Check if asset is fully depreciated
        if asset.accumulated_depreciation + depreciation_amount >= asset.purchase_cost:
            # Adjust to exact amount
            depreciation_amount = asset.purchase_cost - asset.accumulated_depreciation
            if depreciation_amount <= 0:
                raise ValueError("Asset is already fully depreciated")

        # Create depreciation schedule entry
        schedule = AssetDepreciationSchedule(
            asset_id=asset_id,
            period=period,
            depreciation_amount=depreciation_amount
        )
        self.db.add(schedule)
        self.db.flush()

        # Post journal entry
        period_date = datetime.strptime(period + "-01", "%Y-%m-%d")
        lines = [
            {
                "account_code": "6400",  # Depreciation Expense
                "debit": depreciation_amount,
                "credit": 0,
                "description": f"Depreciation - {asset.name} ({asset.asset_code})"
            },
            {
                "account_code": "1301",  # Accumulated Depreciation
                "debit": 0,
                "credit": depreciation_amount,
                "description": f"Accumulated Depreciation - {asset.name} ({asset.asset_code})"
            }
        ]

        journal_entry = self.create_journal_entry(
            entry_date=period_date,
            description=f"Depreciation - {asset.name} ({asset.asset_code}) - Period {period}",
            lines=lines,
            reference_type="DEPRECIATION",
            reference_id=schedule.id,
            created_by=created_by
        )

        # Update asset
        schedule.journal_entry_id = journal_entry.id
        schedule.posted_at = datetime.utcnow()
        asset.accumulated_depreciation += depreciation_amount
        asset.current_value = asset.purchase_cost - asset.accumulated_depreciation

        return schedule, journal_entry

    def dispose_asset(
        self,
        asset_id: int,
        disposal_date: datetime,
        disposal_proceeds: Decimal,
        created_by: int = 1
    ) -> JournalEntry:
        """
        Dispose of a fixed asset and post disposal transaction.
        
        Journal Entry:
        - Dr. Cash (proceeds)
        - Dr. Accumulated Depreciation (remove accumulated)
        - Cr. Fixed Assets (remove cost)
        - Dr/Cr. Gain/Loss on Disposal (difference)
        """
        asset = self.db.get(FixedAsset, asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found")

        if asset.is_disposed:
            raise ValueError(f"Asset {asset.asset_code} is already disposed")

        # Calculate gain/loss
        book_value = asset.purchase_cost - asset.accumulated_depreciation
        gain_loss = disposal_proceeds - book_value

        # Post journal entry
        lines = [
            {
                "account_code": "1000",  # Cash
                "debit": disposal_proceeds,
                "credit": 0,
                "description": f"Proceeds from disposal of {asset.name}"
            },
            {
                "account_code": "1301",  # Accumulated Depreciation
                "debit": asset.accumulated_depreciation,
                "credit": 0,
                "description": f"Remove accumulated depreciation for {asset.name}"
            },
            {
                "account_code": "1300",  # Fixed Assets
                "debit": 0,
                "credit": asset.purchase_cost,
                "description": f"Remove asset {asset.name} from books"
            }
        ]

        # Gain/Loss
        if gain_loss > 0:
            # Gain
            lines.append({
                "account_code": "4100",  # Other Income
                "debit": 0,
                "credit": gain_loss,
                "description": f"Gain on disposal of {asset.name}"
            })
        elif gain_loss < 0:
            # Loss
            lines.append({
                "account_code": "6700",  # Other Operating Expenses
                "debit": abs(gain_loss),
                "credit": 0,
                "description": f"Loss on disposal of {asset.name}"
            })

        journal_entry = self.create_journal_entry(
            entry_date=disposal_date,
            description=f"Asset Disposal - {asset.name} ({asset.asset_code})",
            lines=lines,
            reference_type="ASSET_DISPOSAL",
            reference_id=asset.id,
            created_by=created_by
        )

        # Update asset
        asset.is_disposed = True
        asset.disposed_date = disposal_date
        asset.disposal_proceeds = disposal_proceeds
        asset.current_value = Decimal("0")

        return journal_entry



