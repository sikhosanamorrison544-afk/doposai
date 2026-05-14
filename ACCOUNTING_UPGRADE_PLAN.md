# Accounting Upgrade Plan - POS System
## Analysis & Implementation Strategy

### CURRENT SYSTEM ANALYSIS

#### What Exists:
1. **Sales Transactions**: 
   - `Sale` model with items, payments, discounts
   - Stock is decremented on sale
   - Payments tracked by method (cash, mobile_money, card, credit)
   - No accounting entries generated

2. **Expenses/Withdrawals**:
   - `Withdrawal` model tracks cash outflows
   - Has reason field (e.g., "Daily expenses", "Buying company assets")
   - No expense account linkage
   - No journal entries

3. **Inventory**:
   - `Product` model with cost_price and selling_price
   - `InventoryMovement` tracks stock changes
   - No COGS calculation or posting
   - No inventory asset account

4. **Payments**:
   - Multiple payment methods supported
   - No clearing accounts (Cash, Bank, Mobile Money)
   - No accounting reconciliation

5. **No Accounting Infrastructure**:
   - No Chart of Accounts
   - No Journal Entries
   - No General Ledger
   - No Trial Balance
   - No Financial Reports

#### What's Missing:
1. Chart of Accounts (COA) suitable for Zimbabwe
2. Journal Entry system (header + lines)
3. Accounting engine to auto-post transactions
4. Expense account linkage
5. VAT handling (Input/Output VAT)
6. Fixed Assets register and depreciation
7. Period locking mechanism
8. Audit trail for accounting changes
9. Financial reports (Trial Balance, P&L, Balance Sheet, VAT Report)

---

### PROPOSED ARCHITECTURE

#### 1. Database Schema Additions (New Tables)

**Chart of Accounts (chart_of_accounts)**
- id, code (e.g., "1000", "4000"), name, account_type, parent_id, is_active
- Account types: ASSET, LIABILITY, EQUITY, INCOME, EXPENSE
- Hierarchical structure (parent-child for sub-accounts)

**Journal Entries (journal_entries)**
- id, entry_number, entry_date, description, reference_type, reference_id
- created_by, created_at, is_posted, posted_at, period_id
- Database constraint: Must be balanced (debits = credits)

**Journal Entry Lines (journal_entry_lines)**
- id, journal_entry_id, account_id, debit_amount, credit_amount
- description, reference_type, reference_id
- Database constraint: debit_amount XOR credit_amount (one must be zero)

**Accounting Periods (accounting_periods)**
- id, period_name, start_date, end_date, is_locked, locked_at, locked_by

**Expense Accounts (expense_accounts)**
- Links withdrawal reasons to COA accounts
- id, reason, account_id

**Fixed Assets (fixed_assets)**
- id, asset_code, name, purchase_date, purchase_cost, depreciation_method
- useful_life_months, accumulated_depreciation, current_value

**Asset Depreciation Schedule (asset_depreciation_schedule)**
- id, asset_id, period, depreciation_amount, journal_entry_id

---

#### 2. Implementation Strategy

**Phase 1: Foundation (Non-Breaking)**
1. Create accounting models (new tables only)
2. Create default Chart of Accounts for Zimbabwe
3. Create accounting service module
4. Add database migrations

**Phase 2: Auto-Posting Engine**
1. Hook into `create_sale()` to auto-post journal entries
2. Hook into withdrawal creation to post expenses
3. Ensure atomicity with database transactions
4. Add rollback capability if posting fails

**Phase 3: Inventory Accounting**
1. Implement COGS calculation (Weighted Average method)
2. Post inventory movements to Inventory account
3. Post COGS on sales

**Phase 4: Fixed Assets**
1. Asset register
2. Purchase posting
3. Depreciation scheduler (offline-safe)

**Phase 5: Controls & Reporting**
1. Period locking
2. Audit trail
3. Financial reports (Trial Balance, P&L, Balance Sheet, VAT)

---

### DESIGN DECISIONS

#### 1. Backward Compatibility
- All existing POS functionality remains unchanged
- Accounting is a **backend layer** - no UI changes to cashier workflows
- Existing sales/withdrawals continue to work
- Optional: Backfill journal entries for historical data (separate migration script)

#### 2. Double-Entry Enforcement
- Database CHECK constraints ensure debits = credits
- Application-level validation before commit
- Transaction rollback if unbalanced

#### 3. Zimbabwe-Specific Accounts
- Mobile Money clearing accounts (EcoCash, OneMoney, etc.)
- VAT Control Accounts (15% standard rate)
- ZWL currency handling
- ZIMRA-compliant reporting

#### 4. Offline-First
- All accounting logic runs locally
- No cloud dependencies
- SQLite database (already in use)
- Depreciation scheduler uses local cron/equivalent

#### 5. COGS Method
- **Weighted Average Cost** (simpler than FIFO for offline system)
- Calculated on each sale: `COGS = (Total Cost of Inventory / Total Quantity) * Quantity Sold`
- Alternative: FIFO can be added later if needed

---

### SAMPLE JOURNAL ENTRIES

#### Sale Transaction (Cash Payment):
```
Dr. Cash (1000)                    $100.00
    Cr. Sales Revenue (4000)                  $86.96
    Cr. Output VAT (2200)                      $13.04

Dr. COGS (5000)                    $60.00
    Cr. Inventory (1200)                       $60.00
```

#### Sale Transaction (Mobile Money - EcoCash):
```
Dr. EcoCash Clearing (1010)         $100.00
    Cr. Sales Revenue (4000)                  $86.96
    Cr. Output VAT (2200)                      $13.04

Dr. COGS (5000)                    $60.00
    Cr. Inventory (1200)                       $60.00
```

#### Expense (Daily Expenses):
```
Dr. Operating Expenses (6000)      $50.00
    Cr. Cash (1000)                             $50.00
```

#### Fixed Asset Purchase:
```
Dr. Fixed Assets (1300)            $1,000.00
    Cr. Cash (1000)                             $1,000.00
```

#### Monthly Depreciation:
```
Dr. Depreciation Expense (6100)   $83.33
    Cr. Accumulated Depreciation (1301)         $83.33
```

---

### IMPLEMENTATION ORDER

1. **Models & Schema** (app/accounting_models.py)
2. **Chart of Accounts Setup** (app/accounting_setup.py)
3. **Accounting Engine** (app/accounting_engine.py)
4. **Integration Hooks** (modify app/main.py minimally)
5. **Reports** (app/accounting_reports.py)
6. **Migrations** (Alembic or manual SQL)

---

### RISK MITIGATION

1. **Database Transactions**: All accounting posts wrapped in same transaction as business logic
2. **Validation**: Pre-commit checks ensure balanced entries
3. **Rollback**: If accounting post fails, entire transaction rolls back
4. **Testing**: Test with sample data before production
5. **Backup**: Recommend database backup before migration

---

### QUESTIONS FOR CLARIFICATION

1. **VAT Rate**: What is the standard VAT rate? (Assuming 15% for Zimbabwe)
2. **Currency**: All amounts in ZWL? Any multi-currency needs?
3. **Historical Data**: Should we backfill journal entries for existing sales/withdrawals?
4. **Depreciation Frequency**: Monthly? Quarterly?
5. **Period Structure**: Monthly periods? Fiscal year start month?
6. **Access Control**: Should accountants have different UI or just backend access?

---

### NEXT STEPS

1. Review and approve this plan
2. Answer clarification questions
3. Begin Phase 1 implementation (Models & Schema)
4. Test incrementally
5. Deploy with backward compatibility guarantee

