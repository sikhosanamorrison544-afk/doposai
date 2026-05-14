"""
Accounting Reports - Financial Statements and Reports
Trial Balance, Profit & Loss, Balance Sheet, VAT Report
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, case

from .accounting_models import (
    ChartOfAccount, JournalEntry, JournalEntryLine, AccountingPeriod
)

logger = logging.getLogger(__name__)


class AccountingReports:
    """Generate financial reports from journal entries."""

    def __init__(self, db: Session):
        self.db = db

    def get_trial_balance(
        self,
        as_of_date: Optional[datetime] = None,
        period_name: Optional[str] = None
    ) -> List[Dict]:
        """
        Generate Trial Balance report.
        
        Returns list of accounts with:
        - account_code, account_name, account_type
        - debit_balance, credit_balance
        - net_balance (debit - credit, positive = debit, negative = credit)
        """
        # Get all active accounts first
        all_accounts = self.db.query(ChartOfAccount).filter(
            ChartOfAccount.is_active == True
        ).order_by(ChartOfAccount.code).all()
        
        # Build date filter for transactions
        date_filter = None
        if period_name:
            period = self.db.query(AccountingPeriod).filter(
                AccountingPeriod.period_name == period_name
            ).first()
            if period:
                date_filter = and_(
                    JournalEntry.entry_date >= period.start_date,
                    JournalEntry.entry_date <= period.end_date
                )
        elif as_of_date:
            date_filter = JournalEntry.entry_date <= as_of_date
        
        # Get transaction balances for ALL accounts in a single optimized query (avoid N+1 problem)
        account_ids = [acc.id for acc in all_accounts]
        account_balances = {acc.id: {
            "code": acc.code,
            "name": acc.name,
            "account_type": acc.account_type,
            "debits": Decimal("0"),
            "credits": Decimal("0")
        } for acc in all_accounts}
        
        # Single bulk query for all accounts
        balance_query = self.db.query(
            JournalEntryLine.account_id,
            func.sum(JournalEntryLine.debit_amount).label('total_debits'),
            func.sum(JournalEntryLine.credit_amount).label('total_credits')
        ).join(
            JournalEntry, JournalEntryLine.journal_entry_id == JournalEntry.id
        ).filter(
            JournalEntryLine.account_id.in_(account_ids),
            JournalEntry.is_posted == True
        )
        
        # Apply date filter if provided
        if date_filter is not None:
            balance_query = balance_query.filter(date_filter)
        
        # Group by account to get totals per account
        balance_query = balance_query.group_by(JournalEntryLine.account_id)
        
        # Process results in one go
        for row in balance_query.all():
            account_balances[row.account_id] = {
                "code": account_balances[row.account_id]["code"],
                "name": account_balances[row.account_id]["name"],
                "account_type": account_balances[row.account_id]["account_type"],
                "debits": Decimal(str(row.total_debits or 0)),
                "credits": Decimal(str(row.total_credits or 0))
            }
        
        # Convert to list format for processing
        results = []
        for account in all_accounts:
            balance = account_balances[account.id]
            # Create a simple object with the needed attributes
            class AccountRow:
                def __init__(self, code, name, account_type, total_debits, total_credits):
                    self.code = code
                    self.name = name
                    self.account_type = account_type
                    self.total_debits = total_debits
                    self.total_credits = total_credits
            results.append(AccountRow(
                balance['code'],
                balance['name'],
                balance['account_type'],
                balance['debits'],
                balance['credits']
            ))

        trial_balance = []
        total_debits = Decimal("0")
        total_credits = Decimal("0")

        for row in results:
            debits = Decimal(str(row.total_debits or 0))
            credits = Decimal(str(row.total_credits or 0))
            
            # Calculate net balance based on account type
            if row.account_type in ["ASSET", "EXPENSE"]:
                # Assets and Expenses: Debit balance is positive
                net_balance = debits - credits
            else:
                # Liabilities, Equity, Income: Credit balance is positive
                net_balance = credits - debits
                # For reporting, show as negative if it's a credit balance
                net_balance = -net_balance

            trial_balance.append({
                "account_code": row.code,
                "account_name": row.name,
                "account_type": row.account_type,
                "debit_balance": float(debits),
                "credit_balance": float(credits),
                "net_balance": float(net_balance)
            })

            total_debits += debits
            total_credits += credits

        # Add totals row
        trial_balance.append({
            "account_code": "TOTAL",
            "account_name": "TOTAL",
            "account_type": None,
            "debit_balance": float(total_debits),
            "credit_balance": float(total_credits),
            "net_balance": 0.0
        })

        return trial_balance

    def get_profit_and_loss(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> Dict:
        """
        Generate Profit & Loss Statement.
        
        Returns:
        {
            "period": "2024-01",
            "start_date": datetime,
            "end_date": datetime,
            "revenue": {...},
            "cogs": {...},
            "gross_profit": {...},
            "expenses": [...],
            "total_expenses": {...},
            "net_profit": {...}
        }
        """
        # Revenue (Income accounts)
        revenue_query = self.db.query(
            ChartOfAccount.code,
            ChartOfAccount.name,
            func.sum(JournalEntryLine.credit_amount - JournalEntryLine.debit_amount).label('amount')
        ).join(
            JournalEntryLine, ChartOfAccount.id == JournalEntryLine.account_id
        ).join(
            JournalEntry, JournalEntryLine.journal_entry_id == JournalEntry.id
        ).filter(
            ChartOfAccount.account_type == "INCOME",
            ChartOfAccount.is_active == True,
            JournalEntry.is_posted == True,
            JournalEntry.entry_date >= start_date,
            JournalEntry.entry_date <= end_date
        ).group_by(
            ChartOfAccount.id, ChartOfAccount.code, ChartOfAccount.name
        ).all()

        total_revenue = Decimal("0")
        revenue_items = []
        for row in revenue_query:
            amount = Decimal(str(row.amount or 0))
            total_revenue += amount
            revenue_items.append({
                "account_code": row.code,
                "account_name": row.name,
                "amount": float(amount)
            })

        # COGS (Cost of Goods Sold)
        cogs_query = self.db.query(
            func.sum(JournalEntryLine.debit_amount - JournalEntryLine.credit_amount).label('amount')
        ).join(
            ChartOfAccount, JournalEntryLine.account_id == ChartOfAccount.id
        ).join(
            JournalEntry, JournalEntryLine.journal_entry_id == JournalEntry.id
        ).filter(
            ChartOfAccount.code == "5000",  # COGS account
            JournalEntry.is_posted == True,
            JournalEntry.entry_date >= start_date,
            JournalEntry.entry_date <= end_date
        ).scalar()

        total_cogs = Decimal(str(cogs_query or 0))
        gross_profit = total_revenue - total_cogs

        # Expenses
        expenses_query = self.db.query(
            ChartOfAccount.code,
            ChartOfAccount.name,
            func.sum(JournalEntryLine.debit_amount - JournalEntryLine.credit_amount).label('amount')
        ).join(
            JournalEntryLine, ChartOfAccount.id == JournalEntryLine.account_id
        ).join(
            JournalEntry, JournalEntryLine.journal_entry_id == JournalEntry.id
        ).filter(
            ChartOfAccount.account_type == "EXPENSE",
            ChartOfAccount.is_active == True,
            JournalEntry.is_posted == True,
            JournalEntry.entry_date >= start_date,
            JournalEntry.entry_date <= end_date
        ).group_by(
            ChartOfAccount.id, ChartOfAccount.code, ChartOfAccount.name
        ).order_by(
            func.sum(JournalEntryLine.debit_amount - JournalEntryLine.credit_amount).desc()
        ).all()

        total_expenses = Decimal("0")
        expense_items = []
        for row in expenses_query:
            amount = Decimal(str(row.amount or 0))
            total_expenses += amount
            expense_items.append({
                "account_code": row.code,
                "account_name": row.name,
                "amount": float(amount)
            })

        net_profit = gross_profit - total_expenses

        return {
            "period": start_date.strftime("%Y-%m"),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "revenue": {
                "items": revenue_items,
                "total": float(total_revenue)
            },
            "cogs": {
                "total": float(total_cogs)
            },
            "gross_profit": {
                "total": float(gross_profit)
            },
            "expenses": {
                "items": expense_items,
                "total": float(total_expenses)
            },
            "net_profit": {
                "total": float(net_profit)
            }
        }

    def get_balance_sheet(
        self,
        as_of_date: datetime
    ) -> Dict:
        """
        Generate Balance Sheet.
        
        Returns:
        {
            "as_of_date": datetime,
            "assets": {...},
            "liabilities": {...},
            "equity": {...},
            "total_assets": decimal,
            "total_liabilities": decimal,
            "total_equity": decimal
        }
        """
        # Assets
        assets_query = self.db.query(
            ChartOfAccount.code,
            ChartOfAccount.name,
            func.sum(JournalEntryLine.debit_amount - JournalEntryLine.credit_amount).label('balance')
        ).join(
            JournalEntryLine, ChartOfAccount.id == JournalEntryLine.account_id
        ).join(
            JournalEntry, JournalEntryLine.journal_entry_id == JournalEntry.id
        ).filter(
            ChartOfAccount.account_type == "ASSET",
            ChartOfAccount.is_active == True,
            JournalEntry.is_posted == True,
            JournalEntry.entry_date <= as_of_date
        ).group_by(
            ChartOfAccount.id, ChartOfAccount.code, ChartOfAccount.name
        ).order_by(ChartOfAccount.code).all()

        total_assets = Decimal("0")
        asset_items = []
        for row in assets_query:
            balance = Decimal(str(row.balance or 0))
            total_assets += balance
            asset_items.append({
                "account_code": row.code,
                "account_name": row.name,
                "balance": float(balance)
            })

        # Liabilities
        liabilities_query = self.db.query(
            ChartOfAccount.code,
            ChartOfAccount.name,
            func.sum(JournalEntryLine.credit_amount - JournalEntryLine.debit_amount).label('balance')
        ).join(
            JournalEntryLine, ChartOfAccount.id == JournalEntryLine.account_id
        ).join(
            JournalEntry, JournalEntryLine.journal_entry_id == JournalEntry.id
        ).filter(
            ChartOfAccount.account_type == "LIABILITY",
            ChartOfAccount.is_active == True,
            JournalEntry.is_posted == True,
            JournalEntry.entry_date <= as_of_date
        ).group_by(
            ChartOfAccount.id, ChartOfAccount.code, ChartOfAccount.name
        ).order_by(ChartOfAccount.code).all()

        total_liabilities = Decimal("0")
        liability_items = []
        for row in liabilities_query:
            balance = Decimal(str(row.balance or 0))
            total_liabilities += balance
            liability_items.append({
                "account_code": row.code,
                "account_name": row.name,
                "balance": float(balance)
            })

        # Equity
        equity_query = self.db.query(
            ChartOfAccount.code,
            ChartOfAccount.name,
            func.sum(JournalEntryLine.credit_amount - JournalEntryLine.debit_amount).label('balance')
        ).join(
            JournalEntryLine, ChartOfAccount.id == JournalEntryLine.account_id
        ).join(
            JournalEntry, JournalEntryLine.journal_entry_id == JournalEntry.id
        ).filter(
            ChartOfAccount.account_type == "EQUITY",
            ChartOfAccount.is_active == True,
            JournalEntry.is_posted == True,
            JournalEntry.entry_date <= as_of_date
        ).group_by(
            ChartOfAccount.id, ChartOfAccount.code, ChartOfAccount.name
        ).order_by(ChartOfAccount.code).all()

        total_equity = Decimal("0")
        equity_items = []
        for row in equity_query:
            balance = Decimal(str(row.balance or 0))
            total_equity += balance
            equity_items.append({
                "account_code": row.code,
                "account_name": row.name,
                "balance": float(balance)
            })

        return {
            "as_of_date": as_of_date.isoformat(),
            "assets": {
                "items": asset_items,
                "total": float(total_assets)
            },
            "liabilities": {
                "items": liability_items,
                "total": float(total_liabilities)
            },
            "equity": {
                "items": equity_items,
                "total": float(total_equity)
            },
            "total_assets": float(total_assets),
            "total_liabilities": float(total_liabilities),
            "total_equity": float(total_equity),
            "balances": total_assets == (total_liabilities + total_equity)  # Accounting equation check
        }

    def get_vat_report(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> Dict:
        """
        Generate VAT Report for ZIMRA compliance.
        
        Returns:
        {
            "period": "2024-01",
            "start_date": datetime,
            "end_date": datetime,
            "output_vat": {...},
            "input_vat": {...},
            "vat_payable": decimal
        }
        """
        # Output VAT (VAT on sales)
        output_vat_query = self.db.query(
            func.sum(JournalEntryLine.credit_amount).label('total')
        ).join(
            ChartOfAccount, JournalEntryLine.account_id == ChartOfAccount.id
        ).join(
            JournalEntry, JournalEntryLine.journal_entry_id == JournalEntry.id
        ).filter(
            ChartOfAccount.code == "2200",  # Output VAT
            JournalEntry.is_posted == True,
            JournalEntry.entry_date >= start_date,
            JournalEntry.entry_date <= end_date
        ).scalar()

        output_vat = Decimal(str(output_vat_query or 0))

        # Input VAT (VAT on purchases - if implemented)
        input_vat_query = self.db.query(
            func.sum(JournalEntryLine.debit_amount).label('total')
        ).join(
            ChartOfAccount, JournalEntryLine.account_id == ChartOfAccount.id
        ).join(
            JournalEntry, JournalEntryLine.journal_entry_id == JournalEntry.id
        ).filter(
            ChartOfAccount.code == "2201",  # Input VAT
            JournalEntry.is_posted == True,
            JournalEntry.entry_date >= start_date,
            JournalEntry.entry_date <= end_date
        ).scalar()

        input_vat = Decimal(str(input_vat_query or 0))

        # VAT Payable to ZIMRA
        vat_payable = output_vat - input_vat

        # Get detailed breakdown by transaction
        output_vat_details = self.db.query(
            JournalEntry.entry_date,
            JournalEntry.entry_number,
            JournalEntry.description,
            JournalEntryLine.credit_amount,
            JournalEntry.reference_type,
            JournalEntry.reference_id
        ).join(
            JournalEntryLine, JournalEntry.id == JournalEntryLine.journal_entry_id
        ).join(
            ChartOfAccount, JournalEntryLine.account_id == ChartOfAccount.id
        ).filter(
            ChartOfAccount.code == "2200",  # Output VAT
            JournalEntry.is_posted == True,
            JournalEntry.entry_date >= start_date,
            JournalEntry.entry_date <= end_date
        ).order_by(JournalEntry.entry_date).all()

        vat_transactions = []
        for row in output_vat_details:
            vat_transactions.append({
                "date": row.entry_date.isoformat(),
                "entry_number": row.entry_number,
                "description": row.description,
                "vat_amount": float(row.credit_amount),
                "reference_type": row.reference_type,
                "reference_id": row.reference_id
            })

        return {
            "period": start_date.strftime("%Y-%m"),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "output_vat": {
                "total": float(output_vat),
                "transactions": vat_transactions
            },
            "input_vat": {
                "total": float(input_vat)
            },
            "vat_payable": float(vat_payable),
            "vat_rate": 15.0  # Zimbabwe standard rate
        }

    def get_general_ledger(
        self,
        account_code: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict:
        """
        Generate General Ledger for a specific account.
        
        Returns:
        {
            "account_code": "1000",
            "account_name": "Cash",
            "opening_balance": decimal,
            "transactions": [...],
            "closing_balance": decimal
        }
        """
        account = self.db.query(ChartOfAccount).filter(
            ChartOfAccount.code == account_code,
            ChartOfAccount.is_active == True
        ).first()

        if not account:
            raise ValueError(f"Account not found: {account_code}")

        # Opening balance (before start_date)
        # Determine if account is debit-balance (ASSET, EXPENSE) or credit-balance (LIABILITY, EQUITY, INCOME)
        is_debit_balance = account.account_type in ["ASSET", "EXPENSE"]
        
        # Build the balance calculation based on account type
        if is_debit_balance:
            balance_expr = JournalEntryLine.debit_amount - JournalEntryLine.credit_amount
        else:
            balance_expr = JournalEntryLine.credit_amount - JournalEntryLine.debit_amount
        
        opening_query = self.db.query(
            func.sum(balance_expr).label('balance')
        ).join(
            JournalEntry, JournalEntryLine.journal_entry_id == JournalEntry.id
        ).filter(
            JournalEntryLine.account_id == account.id,
            JournalEntry.is_posted == True
        )

        if start_date:
            opening_query = opening_query.filter(JournalEntry.entry_date < start_date)

        opening_balance = Decimal(str(opening_query.scalar() or 0))

        # Transactions in period
        transactions_query = self.db.query(
            JournalEntry.entry_date,
            JournalEntry.entry_number,
            JournalEntry.description,
            JournalEntryLine.debit_amount,
            JournalEntryLine.credit_amount,
            JournalEntryLine.description.label('line_description')
        ).join(
            JournalEntry, JournalEntryLine.journal_entry_id == JournalEntry.id
        ).filter(
            JournalEntryLine.account_id == account.id,
            JournalEntry.is_posted == True
        )

        if start_date:
            transactions_query = transactions_query.filter(JournalEntry.entry_date >= start_date)
        if end_date:
            transactions_query = transactions_query.filter(JournalEntry.entry_date <= end_date)

        transactions_query = transactions_query.order_by(JournalEntry.entry_date, JournalEntry.id)

        transactions = []
        running_balance = opening_balance

        for row in transactions_query:
            if account.account_type in ["ASSET", "EXPENSE"]:
                # Debit increases, Credit decreases
                change = Decimal(str(row.debit_amount)) - Decimal(str(row.credit_amount))
            else:
                # Credit increases, Debit decreases
                change = Decimal(str(row.credit_amount)) - Decimal(str(row.debit_amount))

            running_balance += change

            transactions.append({
                "date": row.entry_date.isoformat(),
                "entry_number": row.entry_number,
                "description": row.line_description or row.description,
                "debit": float(row.debit_amount),
                "credit": float(row.credit_amount),
                "balance": float(running_balance)
            })

        return {
            "account_code": account.code,
            "account_name": account.name,
            "account_type": account.account_type,
            "opening_balance": float(opening_balance),
            "transactions": transactions,
            "closing_balance": float(running_balance)
        }



