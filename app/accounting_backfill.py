"""
Accounting Backfill - Create journal entries for historical transactions
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func

from .accounting_models import JournalEntry
from .accounting_engine import AccountingEngine
from .models import Sale, SaleItem, Payment, LaybyPayment, LaybyTransaction, Product

logger = logging.getLogger(__name__)


def backfill_historical_transactions(db: Session, created_by: int = 1) -> Dict:
    """
    Backfill journal entries for all historical sales and layby payments.
    
    Returns:
        {
            "sales_processed": int,
            "sales_skipped": int,
            "layby_payments_processed": int,
            "layby_payments_skipped": int,
            "errors": List[str]
        }
    """
    if not db:
        raise ValueError("Database session required")
    
    engine = AccountingEngine(db)
    stats = {
        "sales_processed": 0,
        "sales_skipped": 0,
        "layby_payments_processed": 0,
        "layby_payments_skipped": 0,
        "errors": []
    }
    
    # Get all sales that don't have journal entries yet
    sales_with_entries = db.query(JournalEntry.reference_id).filter(
        JournalEntry.reference_type == "SALE"
    ).all()
    sales_with_entry_ids = {row[0] for row in sales_with_entries}
    
    sales_to_process = db.query(Sale).order_by(Sale.created_at).all()
    sales_to_process = [s for s in sales_to_process if s.id not in sales_with_entry_ids]
    
    logger.info(f"Found {len(sales_to_process)} sales to backfill")
    
    # Process each sale in batches to avoid long transactions
    batch_size = 50
    for i in range(0, len(sales_to_process), batch_size):
        batch = sales_to_process[i:i+batch_size]
        logger.info(f"Processing sales batch {i//batch_size + 1} of {(len(sales_to_process) + batch_size - 1)//batch_size}")
        
        for sale in batch:
            try:
                # Check if journal entry already exists
                existing = db.query(JournalEntry).filter(
                    JournalEntry.reference_type == "SALE",
                    JournalEntry.reference_id == sale.id
                ).first()
                
                if existing:
                    stats["sales_skipped"] += 1
                    continue
                
                # Post sale to accounting
                engine.post_sale(sale)
                db.commit()
                stats["sales_processed"] += 1
                logger.info(f"Backfilled sale {sale.id} from {sale.created_at}")
                
            except Exception as e:
                db.rollback()
                error_msg = f"Error backfilling sale {sale.id}: {str(e)}"
                stats["errors"].append(error_msg)
                logger.error(error_msg, exc_info=True)
                stats["sales_skipped"] += 1
    
    # Get all layby payments that don't have journal entries yet
    layby_payments_with_entries = db.query(JournalEntry.reference_id).filter(
        JournalEntry.reference_type == "LAYBY_PAYMENT"
    ).all()
    layby_payment_ids_with_entries = {row[0] for row in layby_payments_with_entries}
    
    layby_payments_to_process = db.query(LaybyPayment).order_by(LaybyPayment.created_at).all()
    layby_payments_to_process = [p for p in layby_payments_to_process if p.id not in layby_payment_ids_with_entries]
    
    logger.info(f"Found {len(layby_payments_to_process)} layby payments to backfill")
    
    # Process each layby payment in batches
    batch_size = 50
    for i in range(0, len(layby_payments_to_process), batch_size):
        batch = layby_payments_to_process[i:i+batch_size]
        logger.info(f"Processing layby payments batch {i//batch_size + 1} of {(len(layby_payments_to_process) + batch_size - 1)//batch_size}")
        
        for payment in batch:
            try:
                # Check if journal entry already exists
                existing = db.query(JournalEntry).filter(
                    JournalEntry.reference_type == "LAYBY_PAYMENT",
                    JournalEntry.reference_id == payment.id
                ).first()
                
                if existing:
                    stats["layby_payments_skipped"] += 1
                    continue
                
                # Post layby payment to accounting
                transaction = db.get(LaybyTransaction, payment.transaction_id)
                if not transaction:
                    stats["layby_payments_skipped"] += 1
                    continue
                
                # Determine payment account based on method
                payment_account_code = "1000"  # Default to Cash
                if payment.payment_method == "mobile_money":
                    payment_account_code = "1010"  # EcoCash
                elif payment.payment_method == "card":
                    payment_account_code = "1020"  # Bank
                
                # Create journal entry for layby payment
                # When customer makes a layby payment:
                # Dr. Cash/Bank/Mobile Money (receiving money)
                # Cr. Accounts Receivable - Layby (reducing what customer owes)
                # Note: Accounts Receivable is a debit balance account, so crediting it reduces the balance
                lines = [
                    {
                        "account_code": payment_account_code,
                        "debit": payment.amount,
                        "credit": 0,
                        "description": f"Layby Payment #{payment.id} - {payment.payment_method}"
                    },
                    {
                        "account_code": "1100",  # Accounts Receivable (for layby)
                        "debit": 0,
                        "credit": payment.amount,
                        "description": f"Layby Payment #{payment.id} - Transaction #{transaction.id}"
                    }
                ]
                
                journal_entry = engine.create_journal_entry(
                    entry_date=payment.created_at,
                    description=f"Layby Payment #{payment.id} - Transaction #{transaction.id}",
                    lines=lines,
                    reference_type="LAYBY_PAYMENT",
                    reference_id=payment.id,
                    created_by=created_by
                )
                
                db.commit()
                stats["layby_payments_processed"] += 1
                logger.info(f"Backfilled layby payment {payment.id} from {payment.created_at}")
                
                # If this payment completes the layby transaction, also post the sale
                if transaction.status == "completed" and transaction.balance <= Decimal("0.01"):
                    # Check if sale journal entry already exists for this completed layby
                    existing_sale_entry = db.query(JournalEntry).filter(
                        JournalEntry.reference_type == "LAYBY_COMPLETION",
                        JournalEntry.reference_id == transaction.id
                    ).first()
                    
                    if not existing_sale_entry:
                        try:
                            # Post the completed layby as a sale
                            # This is similar to a regular sale but the payment was received over time
                            product = db.get(Product, transaction.product_id)
                            if product:
                                # Calculate amounts
                                vat_rate = Decimal("0.15")  # 15% VAT
                                vat_exclusive_total = transaction.total_amount / (Decimal("1") + vat_rate)
                                vat_amount = transaction.total_amount - vat_exclusive_total
                                
                                # Calculate COGS
                                cogs_per_unit = product.cost_price
                                cogs_total = cogs_per_unit * Decimal(str(transaction.quantity))
                                
                                # Create journal entry for completed layby sale
                                # When layby is completed, recognize revenue and COGS
                                # The cash was already received via payments, so we just post:
                                # - Revenue recognition (Cr. Sales, Cr. VAT)
                                # - COGS and inventory reduction
                                lines = [
                                    # Dr. Accounts Receivable (to clear any remaining balance)
                                    {
                                        "account_code": "1100",
                                        "debit": transaction.total_amount,
                                        "credit": 0,
                                        "description": f"Layby Completion - Transaction #{transaction.id}"
                                    },
                                    # Cr. Sales Revenue
                                    {
                                        "account_code": "4000",
                                        "debit": 0,
                                        "credit": vat_exclusive_total,
                                        "description": f"Layby Sale - Transaction #{transaction.id}"
                                    },
                                    # Cr. Output VAT
                                    {
                                        "account_code": "2200",
                                        "debit": 0,
                                        "credit": vat_amount,
                                        "description": f"VAT on Layby Sale #{transaction.id}"
                                    },
                                    # Dr. COGS
                                    {
                                        "account_code": "5000",
                                        "debit": cogs_total,
                                        "credit": 0,
                                        "description": f"COGS for Layby Sale #{transaction.id}"
                                    },
                                    # Cr. Inventory
                                    {
                                        "account_code": "1200",
                                        "debit": 0,
                                        "credit": cogs_total,
                                        "description": f"Inventory reduction for Layby Sale #{transaction.id}"
                                    }
                                ]
                                
                                completion_entry = engine.create_journal_entry(
                                    entry_date=transaction.completed_at or transaction.created_at,
                                    description=f"Layby Completion - Transaction #{transaction.id}",
                                    lines=lines,
                                    reference_type="LAYBY_COMPLETION",
                                    reference_id=transaction.id,
                                    created_by=created_by
                                )
                                
                                db.commit()
                                logger.info(f"Backfilled layby completion {transaction.id}")
                        except Exception as e:
                            db.rollback()
                            logger.warning(f"Could not post layby completion for transaction {transaction.id}: {e}")
            
            except Exception as e:
                db.rollback()
                error_msg = f"Error backfilling layby payment {payment.id}: {str(e)}"
                stats["errors"].append(error_msg)
                logger.error(error_msg, exc_info=True)
                stats["layby_payments_skipped"] += 1
    
    return stats

