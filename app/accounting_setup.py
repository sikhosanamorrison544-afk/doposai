"""
Chart of Accounts Setup for Zimbabwe POS System
Initializes default accounts suitable for Zimbabwe retail business.
"""

import logging
from sqlalchemy.orm import Session

from .accounting_models import ChartOfAccount, ExpenseAccountMapping

logger = logging.getLogger(__name__)


# Zimbabwe Chart of Accounts Structure
ZIMBABWE_COA = [
    # ASSETS (1000-1999)
    {"code": "1000", "name": "Cash", "type": "ASSET", "parent": None},
    {"code": "1010", "name": "EcoCash Clearing Account", "type": "ASSET", "parent": None},
    {"code": "1011", "name": "OneMoney Clearing Account", "type": "ASSET", "parent": None},
    {"code": "1020", "name": "Bank Account", "type": "ASSET", "parent": None},
    {"code": "1100", "name": "Accounts Receivable", "type": "ASSET", "parent": None},
    {"code": "1200", "name": "Inventory", "type": "ASSET", "parent": None},
    {"code": "1300", "name": "Fixed Assets", "type": "ASSET", "parent": None},
    {"code": "1301", "name": "Accumulated Depreciation", "type": "ASSET", "parent": "1300"},
    {"code": "1400", "name": "Prepaid Expenses", "type": "ASSET", "parent": None},
    
    # LIABILITIES (2000-2999)
    {"code": "2000", "name": "Accounts Payable", "type": "LIABILITY", "parent": None},
    {"code": "2100", "name": "Accrued Expenses", "type": "LIABILITY", "parent": None},
    {"code": "2200", "name": "Output VAT", "type": "LIABILITY", "parent": None},
    {"code": "2201", "name": "Input VAT", "type": "LIABILITY", "parent": None},
    {"code": "2300", "name": "VAT Payable to ZIMRA", "type": "LIABILITY", "parent": None},
    
    # EQUITY (3000-3999)
    {"code": "3000", "name": "Owner's Equity", "type": "EQUITY", "parent": None},
    {"code": "3100", "name": "Retained Earnings", "type": "EQUITY", "parent": None},
    {"code": "3200", "name": "Current Year Earnings", "type": "EQUITY", "parent": None},
    
    # INCOME (4000-4999)
    {"code": "4000", "name": "Sales Revenue", "type": "INCOME", "parent": None},
    {"code": "4100", "name": "Other Income", "type": "INCOME", "parent": None},
    
    # EXPENSES (5000-6999)
    {"code": "5000", "name": "Cost of Goods Sold (COGS)", "type": "EXPENSE", "parent": None},
    {"code": "6000", "name": "Operating Expenses", "type": "EXPENSE", "parent": None},
    {"code": "6100", "name": "Salaries and Wages", "type": "EXPENSE", "parent": "6000"},
    {"code": "6200", "name": "Rent Expense", "type": "EXPENSE", "parent": "6000"},
    {"code": "6300", "name": "Utilities Expense", "type": "EXPENSE", "parent": "6000"},
    {"code": "6400", "name": "Depreciation Expense", "type": "EXPENSE", "parent": "6000"},
    {"code": "6500", "name": "Daily Expenses", "type": "EXPENSE", "parent": "6000"},
    {"code": "6600", "name": "Company Assets Purchase", "type": "EXPENSE", "parent": "6000"},
    {"code": "6700", "name": "Other Operating Expenses", "type": "EXPENSE", "parent": "6000"},
]


# Default expense account mappings for withdrawal reasons
DEFAULT_EXPENSE_MAPPINGS = [
    {"reason": "Daily expenses", "account_code": "6500"},
    {"reason": "Salary", "account_code": "6100"},
    {"reason": "Buying company assets", "account_code": "6600"},
    {"reason": "Rent", "account_code": "6200"},
    {"reason": "Utilities", "account_code": "6300"},
]


def initialize_chart_of_accounts(db: Session) -> bool:
    """
    Initialize Chart of Accounts with Zimbabwe-specific accounts.
    Returns True if successful, False if accounts already exist.
    """
    # Check if COA already exists
    existing = db.query(ChartOfAccount).first()
    if existing:
        logger.info("Chart of Accounts already initialized. Skipping.")
        return False

    logger.info("Initializing Chart of Accounts for Zimbabwe POS system...")

    # Create accounts
    account_map = {}  # Store created accounts for parent relationships
    for account_data in ZIMBABWE_COA:
        parent_id = None
        if account_data["parent"]:
            parent_account = account_map.get(account_data["parent"])
            if parent_account:
                parent_id = parent_account.id

        account = ChartOfAccount(
            code=account_data["code"],
            name=account_data["name"],
            account_type=account_data["type"],
            parent_id=parent_id,
            is_active=True,
            description=f"Default account for {account_data['name']}"
        )
        db.add(account)
        db.flush()
        account_map[account_data["code"]] = account
        logger.debug(f"Created account: {account.code} - {account.name}")

    # Create expense account mappings
    for mapping_data in DEFAULT_EXPENSE_MAPPINGS:
        account = account_map.get(mapping_data["account_code"])
        if account:
            expense_mapping = ExpenseAccountMapping(
                reason=mapping_data["reason"],
                account_id=account.id
            )
            db.add(expense_mapping)
            logger.debug(f"Mapped '{mapping_data['reason']}' to account {account.code}")

    db.commit()
    logger.info(f"Successfully initialized {len(ZIMBABWE_COA)} accounts and {len(DEFAULT_EXPENSE_MAPPINGS)} expense mappings.")
    return True


def verify_chart_of_accounts(db: Session) -> bool:
    """Verify that essential accounts exist."""
    essential_accounts = ["1000", "4000", "5000", "6000", "1200", "2200"]
    missing = []

    for code in essential_accounts:
        account = db.query(ChartOfAccount).filter(
            ChartOfAccount.code == code,
            ChartOfAccount.is_active == True
        ).first()
        if not account:
            missing.append(code)

    if missing:
        logger.warning(f"Missing essential accounts: {missing}")
        return False

    return True

