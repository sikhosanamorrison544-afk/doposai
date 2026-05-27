"""
Google Sheets backup service for inventory.
Automatically syncs products to Google Sheets when online.
Handles offline changes queue and syncs when connection is restored.
"""

import json
import logging
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    logging.warning("requests library not available. Install with: pip install requests")

from sqlalchemy.orm import Session

from app.config import BASE_DIR
from app.models import Product, Customer, LaybyCustomer, LaybyTransaction, Withdrawal, User

# Queue file to store offline changes
OFFLINE_QUEUE_FILE = BASE_DIR / "offline_changes.json"

# Configuration file for Google Sheets
BACKUP_CONFIG_FILE = BASE_DIR / "backup_config.json"

logger = logging.getLogger(__name__)


class BackupService:
    """Service for backing up inventory to Google Sheets via Apps Script Web App."""
    
    def __init__(self):
        self.web_app_url = None
        self.api_key = None
        self.config = self._load_config()
        self._initialize_client()
    
    def _load_config(self) -> Dict:
        """Load backup configuration from file."""
        if BACKUP_CONFIG_FILE.exists():
            try:
                with open(BACKUP_CONFIG_FILE, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading backup config: {e}")
        return {
            "enabled": False,
            "web_app_url": "",  # Google Apps Script Web App URL
            "api_key": ""  # Optional API key for security
        }
    
    def _save_config(self):
        """Save backup configuration to file."""
        try:
            with open(BACKUP_CONFIG_FILE, 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving backup config: {e}")
    
    def _initialize_client(self):
        """Initialize web app URL."""
        if not self.config.get("enabled", False):
            return
        
        self.web_app_url = self.config.get("web_app_url", "").strip()
        self.api_key = self.config.get("api_key", "").strip()
        
        if not self.web_app_url:
            logger.warning("Google Sheets Web App URL not configured")
            return
        
        if not REQUESTS_AVAILABLE:
            logger.warning("requests library not available. Install with: pip install requests")
            return
    
    def is_enabled(self) -> bool:
        """Check if backup is enabled and configured."""
        return (
            REQUESTS_AVAILABLE and
            self.config.get("enabled", False) and
            bool(self.web_app_url)
        )
    
    def _send_request(self, action: str, data: Dict) -> Dict:
        """Send HTTP request to Google Apps Script web app."""
        if not REQUESTS_AVAILABLE:
            return {"success": False, "error": "requests library not available"}
        
        if not self.web_app_url:
            return {"success": False, "error": "Web app URL not configured"}
        
        try:
            payload = {
                "action": action,
                "data": data
            }
            
            if self.api_key:
                payload["api_key"] = self.api_key
            
            logger.info(f"Sending request to {self.web_app_url} with action: {action}")
            logger.info(f"Payload keys: {list(payload.keys())}")
            if action == "sync_all_withdrawals":
                logger.info(f"Withdrawals count in payload: {len(payload.get('data', {}).get('withdrawals', []))}")
            
            response = requests.post(
                self.web_app_url,
                json=payload,
                timeout=30,
                allow_redirects=True
            )
            
            logger.info(f"Response status: {response.status_code}")
            logger.info(f"Response text: {response.text[:500]}")  # Log first 500 chars
            
            # Handle 401 Unauthorized - web app needs authorization
            if response.status_code == 401:
                return {
                    "success": False,
                    "error": "Web app not authorized. Please visit the Web App URL in your browser to authorize it, then try again."
                }
            
            if response.status_code == 200:
                try:
                    result = response.json()
                    if not result.get("success"):
                        return {"success": False, "error": result.get("error", "Unknown error from Apps Script")}
                    return result
                except ValueError:
                    # Response is not JSON
                    return {"success": False, "error": f"Invalid JSON response: {response.text[:200]}"}
            else:
                return {"success": False, "error": f"HTTP {response.status_code}: {response.text[:200]}"}
        except requests.exceptions.Timeout:
            logger.error(f"Request to web app timed out")
            return {"success": False, "error": "Request timed out. Please check your internet connection and try again."}
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error: {e}")
            return {"success": False, "error": f"Connection error: {str(e)}"}
        except requests.exceptions.RequestException as e:
            logger.error(f"Error sending request to web app: {e}")
            return {"success": False, "error": str(e)}
    
    def check_internet(self, timeout: float = 0.5) -> bool:
        """Quick connectivity probe for status UI (short timeout by default)."""
        try:
            import socket

            socket.create_connection(("8.8.8.8", 53), timeout=timeout)
            return True
        except OSError:
            return False

    def _check_internet(self) -> bool:
        return self.check_internet(timeout=3)
    
    def _load_offline_queue(self) -> List[Dict]:
        """Load offline changes queue from file."""
        if not OFFLINE_QUEUE_FILE.exists():
            return []
        try:
            with open(OFFLINE_QUEUE_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading offline queue: {e}")
            return []
    
    def _save_offline_queue(self, queue: List[Dict]):
        """Save offline changes queue to file."""
        try:
            with open(OFFLINE_QUEUE_FILE, 'w') as f:
                json.dump(queue, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving offline queue: {e}")
    
    def _add_to_offline_queue(self, action: str, product_id: int, data: Optional[Dict] = None):
        """Add a change to the offline queue."""
        queue = self._load_offline_queue()
        queue.append({
            "action": action,  # "create", "update", "delete"
            "product_id": product_id,
            "data": data,
            "timestamp": datetime.utcnow().isoformat()
        })
        self._save_offline_queue(queue)
    
    def sync_all_products(self, db: Session) -> Dict:
        """Sync all products to Google Sheets via Apps Script web app."""
        if not REQUESTS_AVAILABLE:
            return {"success": False, "message": "requests library not available. Install with: pip install requests"}
        
        if not self.config.get("enabled", False):
            return {"success": False, "message": "Backup is not enabled. Please check 'Enable Google Sheets Backup' and save configuration."}
        
        if not self.web_app_url:
            web_url = self.config.get("web_app_url", "").strip()
            if not web_url:
                return {"success": False, "message": "Web App URL is not configured. Please enter your Google Apps Script Web App URL and save configuration."}
            # Try to initialize if URL exists in config but not set
            self._initialize_client()
        
        if not self.web_app_url:
            return {"success": False, "message": "Web App URL is not configured. Please enter your Google Apps Script Web App URL and save configuration."}
        
        if not self._check_internet():
            return {"success": False, "message": "No internet connection"}
        
        try:
            # Get all products
            products = db.query(Product).all()
            
            # Prepare product data
            products_data = []
            for product in products:
                category_name = product.category.name if product.category else ""
                products_data.append({
                    "id": product.id,
                    "name": product.name,
                    "barcode": product.barcode or "",
                    "category": category_name,
                    "stock_qty": float(product.stock_qty),
                    "cost_price": float(product.cost_price),
                    "selling_price": float(product.selling_price),
                    "is_active": product.is_active
                })
            
            # Send to web app
            result = self._send_request("sync_all", {"products": products_data})
            
            if result.get("success"):
                return {
                    "success": True,
                    "message": f"Synced {len(products)} products to Google Sheets",
                    "count": len(products)
                }
            else:
                error_msg = result.get("error", result.get("message", "Unknown error occurred"))
                return {
                    "success": False,
                    "message": f"Sync failed: {error_msg}"
                }
        except Exception as e:
            logger.error(f"Error syncing all products: {e}")
            return {"success": False, "message": str(e)}
    
    def sync_all_debtors(self, db: Session) -> Dict:
        """Sync all debtors (customers with outstanding debts) to Google Sheets via Apps Script web app."""
        if not REQUESTS_AVAILABLE:
            return {"success": False, "message": "requests library not available"}
        
        if not self.config.get("enabled", False):
            return {"success": False, "message": "Backup is not enabled"}
        
        if not self.web_app_url:
            self._initialize_client()
            if not self.web_app_url:
                return {"success": False, "message": "Web App URL is not configured"}
        
        if not self._check_internet():
            return {"success": False, "message": "No internet connection"}
        
        try:
            # Get all debtors (same logic as the API endpoint)
            debts = []
            
            # Get regular customers with credit_balance > 0
            regular_customers = db.query(Customer).filter(Customer.credit_balance > 0).all()
            for customer in regular_customers:
                debts.append({
                    "customer_id": customer.id,
                    "customer_name": customer.name,
                    "phone": customer.phone or "",
                    "address": customer.address or "",
                    "debt_type": "credit_sale",
                    "debt_amount": float(customer.credit_balance),
                })
            
            # Get layby customers with outstanding balances
            layby_customers = db.query(LaybyCustomer).all()
            for layby_customer in layby_customers:
                # Get all active transactions for this customer
                active_transactions = db.query(LaybyTransaction).filter(
                    LaybyTransaction.customer_id == layby_customer.id,
                    LaybyTransaction.status == "active"
                ).all()
                
                customer_total_balance = Decimal("0.00")
                for txn in active_transactions:
                    customer_total_balance += Decimal(str(txn.balance))
                
                if customer_total_balance > 0:
                    debts.append({
                        "customer_id": layby_customer.id,
                        "customer_name": layby_customer.name,
                        "phone": layby_customer.phone or "",
                        "address": layby_customer.address or "",
                        "debt_type": "layby",
                        "debt_amount": float(customer_total_balance),
                    })
            
            # Sort by debt amount (highest first)
            debts.sort(key=lambda x: x["debt_amount"], reverse=True)
            
            # Calculate grand total
            grand_total = sum(Decimal(str(debt["debt_amount"])) for debt in debts)
            
            # Send to Apps Script
            result = self._send_request("sync_all_debtors", {
                "debts": debts,
                "grand_total": float(grand_total),
                "count": len(debts),
                "sync_timestamp": datetime.utcnow().isoformat()
            })
            
            if result.get("success"):
                return {
                    "success": True,
                    "message": f"Synced {len(debts)} debtors to Google Sheets",
                    "count": len(debts),
                    "grand_total": float(grand_total)
                }
            else:
                error_msg = result.get("error", result.get("message", "Unknown error occurred"))
                return {
                    "success": False,
                    "message": f"Sync failed: {error_msg}"
                }
        except Exception as e:
            logger.error(f"Error syncing debtors: {e}")
            return {"success": False, "message": str(e)}
    
    def sync_product_create(self, db: Session, product: Product) -> bool:
        """Sync a newly created product to Google Sheets."""
        if not self.is_enabled():
            if self._check_internet():
                self._add_to_offline_queue("create", product.id, None)
            return False
        
        if not self._check_internet():
            self._add_to_offline_queue("create", product.id, None)
            return False
        
        try:
            category_name = product.category.name if product.category else ""
            product_data = {
                "id": product.id,
                "name": product.name,
                "barcode": product.barcode or "",
                "category": category_name,
                "stock_qty": float(product.stock_qty),
                "cost_price": float(product.cost_price),
                "selling_price": float(product.selling_price),
                "is_active": product.is_active
            }
            
            result = self._send_request("create", {"product": product_data})
            return result.get("success", False)
        except Exception as e:
            logger.error(f"Error syncing product create: {e}")
            self._add_to_offline_queue("create", product.id, None)
            return False
    
    def sync_product_update(self, db: Session, product: Product) -> bool:
        """Sync an updated product to Google Sheets."""
        if not self.is_enabled():
            if self._check_internet():
                self._add_to_offline_queue("update", product.id, None)
            return False
        
        if not self._check_internet():
            self._add_to_offline_queue("update", product.id, None)
            return False
        
        try:
            category_name = product.category.name if product.category else ""
            product_data = {
                "id": product.id,
                "name": product.name,
                "barcode": product.barcode or "",
                "category": category_name,
                "stock_qty": float(product.stock_qty),
                "cost_price": float(product.cost_price),
                "selling_price": float(product.selling_price),
                "is_active": product.is_active
            }
            
            result = self._send_request("update", {"product": product_data})
            return result.get("success", False)
        except Exception as e:
            logger.error(f"Error syncing product update: {e}")
            self._add_to_offline_queue("update", product.id, None)
            return False
    
    def sync_product_delete(self, db: Session, product_id: int) -> bool:
        """Sync a deleted product removal from Google Sheets."""
        if not self.is_enabled():
            if self._check_internet():
                self._add_to_offline_queue("delete", product_id, None)
            return False
        
        if not self._check_internet():
            self._add_to_offline_queue("delete", product_id, None)
            return False
        
        try:
            result = self._send_request("delete", {"product_id": product_id})
            return result.get("success", False)
        except Exception as e:
            logger.error(f"Error syncing product delete: {e}")
            self._add_to_offline_queue("delete", product_id, None)
            return False
    
    def process_offline_queue(self, db: Session) -> Dict:
        """Process all pending offline changes when internet is available."""
        if not self.is_enabled():
            return {"success": False, "message": "Backup not enabled"}
        
        if not self._check_internet():
            return {"success": False, "message": "No internet connection"}
        
        queue = self._load_offline_queue()
        if not queue:
            return {"success": True, "message": "No pending changes", "processed": 0}
        
        processed = 0
        errors = []
        
        for change in queue:
            try:
                action = change["action"]
                product_id = change["product_id"]
                
                if action == "create":
                    product = db.query(Product).get(product_id)
                    if product:
                        if self.sync_product_create(db, product):
                            processed += 1
                elif action == "update":
                    product = db.query(Product).get(product_id)
                    if product:
                        if self.sync_product_update(db, product):
                            processed += 1
                    else:
                        # Product was deleted, skip update
                        processed += 1
                elif action == "delete":
                    if self.sync_product_delete(db, product_id):
                        processed += 1
            except Exception as e:
                errors.append(f"Error processing {change}: {e}")
                logger.error(f"Error processing offline change: {e}")
        
        # Clear processed items from queue
        if processed > 0:
            remaining = queue[processed:]
            self._save_offline_queue(remaining)
        
        return {
            "success": True,
            "message": f"Processed {processed} changes",
            "processed": processed,
            "errors": errors
        }
    
    def sync_withdrawal_create(self, db: Session, withdrawal: Withdrawal) -> bool:
        """Sync a newly created withdrawal to Google Sheets."""
        if not self.is_enabled():
            return False
        
        if not self._check_internet():
            return False
        
        try:
            cashier = db.query(User).get(withdrawal.cashier_id)
            cashier_name = cashier.full_name or cashier.username if cashier else "Unknown"
            
            withdrawal_data = {
                "id": withdrawal.id,
                "cashier_id": withdrawal.cashier_id,
                "cashier_name": cashier_name,
                "amount": float(withdrawal.amount),
                "reason": withdrawal.reason,
                "receipt_number": withdrawal.receipt_number or "",
                "created_at": withdrawal.created_at.isoformat() if withdrawal.created_at else "",
                "notes": withdrawal.notes or ""
            }
            
            result = self._send_request("create_withdrawal", {"withdrawal": withdrawal_data})
            return result.get("success", False)
        except Exception as e:
            logger.error(f"Error syncing withdrawal create: {e}")
            return False
    
    def sync_all_withdrawals(self, db: Session) -> Dict:
        """Sync all withdrawals to Google Sheets via Apps Script web app."""
        if not REQUESTS_AVAILABLE:
            return {"success": False, "message": "requests library not available"}
        
        if not self.config.get("enabled", False):
            return {"success": False, "message": "Backup is not enabled"}
        
        if not self.web_app_url:
            self._initialize_client()
            if not self.web_app_url:
                return {"success": False, "message": "Web App URL is not configured"}
        
        if not self._check_internet():
            return {"success": False, "message": "No internet connection"}
        
        try:
            withdrawals = db.query(Withdrawal).order_by(Withdrawal.created_at.desc()).all()
            
            withdrawals_data = []
            for withdrawal in withdrawals:
                cashier = db.query(User).get(withdrawal.cashier_id)
                cashier_name = cashier.full_name or cashier.username if cashier else "Unknown"
                
                withdrawals_data.append({
                    "id": withdrawal.id,
                    "cashier_id": withdrawal.cashier_id,
                    "cashier_name": cashier_name,
                    "amount": float(withdrawal.amount),
                    "reason": withdrawal.reason,
                    "receipt_number": withdrawal.receipt_number or "",
                    "created_at": withdrawal.created_at.isoformat() if withdrawal.created_at else "",
                    "notes": withdrawal.notes or ""
                })
            
            result = self._send_request("sync_all_withdrawals", {
                "withdrawals": withdrawals_data,
                "count": len(withdrawals_data),
                "sync_timestamp": datetime.utcnow().isoformat()
            })
            
            if result.get("success"):
                return {
                    "success": True,
                    "message": f"Synced {len(withdrawals)} withdrawals to Google Sheets",
                    "count": len(withdrawals)
                }
            else:
                error_msg = result.get("error", result.get("message", "Unknown error occurred"))
                return {
                    "success": False,
                    "message": f"Sync failed: {error_msg}"
                }
        except Exception as e:
            logger.error(f"Error syncing withdrawals: {e}")
            return {"success": False, "message": str(e)}


# Global backup service instance
_backup_service = None


def get_backup_service() -> BackupService:
    """Get or create backup service instance."""
    global _backup_service
    if _backup_service is None:
        _backup_service = BackupService()
    return _backup_service

