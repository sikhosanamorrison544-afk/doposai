"""
Notification Service for low-stock alerts and other system notifications.
"""

import logging
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict
from sqlalchemy.orm import Session
from sqlalchemy import and_

from .models import Product, Notification, StoreSettings, User
from . import tenant_scope
from .email_service import email_service

logger = logging.getLogger(__name__)


class NotificationService:
    """Service for managing system notifications."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_threshold(self, product: Product) -> float:
        """
        Get the low-stock threshold for a product.
        Uses product-specific threshold if set, otherwise tenant store settings.
        """
        if product.low_stock_threshold is not None:
            return product.low_stock_threshold

        settings = tenant_scope.first_store_settings_for_tenant(
            self.db, getattr(product, "tenant_id", None)
        )
        if settings and settings.default_low_stock_threshold:
            return settings.default_low_stock_threshold

        return 10.0
    
    def check_low_stock(self, product: Product) -> Optional[Notification]:
        """
        Check if a product is low on stock and create a notification if needed.
        Prevents duplicate notifications unless stock goes back above threshold.
        
        Args:
            product: Product to check
        
        Returns:
            Notification if created, None otherwise
        """
        if not product.is_active:
            return None
        
        threshold = self.get_threshold(product)
        
        # Check if stock is below threshold
        if product.stock_qty > threshold:
            return None
        
        # Check if there's already an unread notification for this product
        existing_notification = self.db.query(Notification).filter(
            and_(
                Notification.product_id == product.id,
                Notification.type == "LOW_STOCK",
                Notification.is_read == False
            )
        ).first()
        
        if existing_notification:
            # Already have an unread notification, don't create duplicate
            return None
        
        # Check if stock was previously above threshold (to allow re-notification)
        # Look for the most recent notification for this product
        last_notification = self.db.query(Notification).filter(
            and_(
                Notification.product_id == product.id,
                Notification.type == "LOW_STOCK"
            )
        ).order_by(Notification.created_at.desc()).first()
        
        if last_notification and not last_notification.is_read:
            # There's an unread notification, don't create duplicate
            return None
        
        # Create notification with clear quantity information
        if product.stock_qty == 0:
            message = f"OUT OF STOCK: {product.name} (Qty: 0)"
        else:
            message = f"Low Stock: {product.name} (Qty: {product.stock_qty}, Threshold: {threshold})"
        
        notification = Notification(
            type="LOW_STOCK",
            message=message,
            product_id=product.id,
            is_read=False,
            tenant_id=getattr(product, "tenant_id", None),
        )
        self.db.add(notification)
        self.db.flush()
        
        logger.info(f"Created low-stock notification for product {product.id} ({product.name})")
        
        # Don't send individual emails - batch email will be sent separately
        # Email will be sent when check_all_products_low_stock() is called
        
        return notification
    
    def check_all_products_and_create_notifications(self, user: Optional[User] = None) -> int:
        """
        Check all active products and create notifications for:
        - Out of stock items (qty = 0)
        - Items with qty <= 5

        Returns:
            Number of notifications created
        """
        # Get all active products
        if user is not None:
            products = (
                tenant_scope.filter_products(self.db, user)
                .filter(Product.is_active == True)  # noqa: E712
                .all()
            )
        else:
            products = self.db.query(Product).filter(Product.is_active == True).all()  # noqa: E712
        
        notifications_created = 0
        
        for product in products:
            # Check for out of stock (qty = 0)
            if product.stock_qty == 0:
                # Check if there's already an unread notification for this product
                existing_notification = self.db.query(Notification).filter(
                    and_(
                        Notification.product_id == product.id,
                        Notification.type == "LOW_STOCK",
                        Notification.is_read == False
                    )
                ).first()
                
                if not existing_notification:
                    message = f"OUT OF STOCK: {product.name} (Qty: 0)"
                    notification = Notification(
                        type="LOW_STOCK",
                        message=message,
                        product_id=product.id,
                        is_read=False,
                        tenant_id=getattr(product, "tenant_id", None),
                    )
                    self.db.add(notification)
                    notifications_created += 1
                    logger.info(f"Created out-of-stock notification for product {product.id} ({product.name})")
            
            # Check for qty <= 5 (but not 0, as that's already handled above)
            elif product.stock_qty <= 5:
                # Check if there's already an unread notification for this product
                existing_notification = self.db.query(Notification).filter(
                    and_(
                        Notification.product_id == product.id,
                        Notification.type == "LOW_STOCK",
                        Notification.is_read == False
                    )
                ).first()
                
                if not existing_notification:
                    message = f"Low Stock: {product.name} (Qty: {product.stock_qty})"
                    notification = Notification(
                        type="LOW_STOCK",
                        message=message,
                        product_id=product.id,
                        is_read=False,
                        tenant_id=getattr(product, "tenant_id", None),
                    )
                    self.db.add(notification)
                    notifications_created += 1
                    logger.info(f"Created low-stock notification for product {product.id} ({product.name}) - Qty: {product.stock_qty}")
        
        if notifications_created > 0:
            self.db.commit()
            logger.info(f"Created {notifications_created} new notifications for low-stock/out-of-stock products")
        
        return notifications_created
    
    def check_all_products_low_stock(self) -> None:
        """
        Check active products for low stock and send tenant-scoped batch emails.

        Scheduler path: iterates StoreSettings per tenant (no cross-tenant branding).
        When a product has no matching StoreSettings, it is skipped for email (logged).
        """
        settings_rows = self.db.query(StoreSettings).all()
        if not settings_rows:
            logger.warning(
                "check_all_products_low_stock: no StoreSettings rows; skipping email batch"
            )
            return

        by_tenant: Dict[Optional[int], StoreSettings] = {}
        for s in settings_rows:
            tid = getattr(s, "tenant_id", None)
            # Prefer first row per tenant
            if tid not in by_tenant:
                by_tenant[tid] = s

        products = self.db.query(Product).filter(Product.is_active == True).all()
        # Group products by tenant_id
        products_by_tid: Dict[Optional[int], List[Product]] = {}
        for product in products:
            tid = getattr(product, "tenant_id", None)
            products_by_tid.setdefault(tid, []).append(product)

        for tid, tenant_products in products_by_tid.items():
            settings = by_tenant.get(tid)
            if not settings:
                logger.warning(
                    "check_all_products_low_stock: no StoreSettings for tenant_id=%s; skip email",
                    tid,
                )
                continue
            if not settings.low_stock_email_enabled or not settings.notification_email:
                continue

            low_stock_products = []
            for product in tenant_products:
                threshold = self.get_threshold(product)
                if product.stock_qty <= threshold:
                    low_stock_products.append(
                        {
                            "name": product.name,
                            "current_stock": product.stock_qty,
                            "threshold": threshold,
                        }
                    )

            if not low_stock_products:
                continue
            try:
                store_name = settings.store_name or "Store"
                success = email_service.send_low_stock_batch_alert(
                    to_email=settings.notification_email,
                    products=low_stock_products,
                    store_name=store_name,
                )
                if success:
                    logger.info(
                        "Sent batch low-stock email for tenant_id=%s (%s products)",
                        tid,
                        len(low_stock_products),
                    )
                else:
                    logger.warning(
                        "Failed to send batch low-stock email for tenant_id=%s", tid
                    )
            except Exception as e:
                logger.error(
                    "Error sending batch low-stock email for tenant_id=%s: %s",
                    tid,
                    e,
                    exc_info=True,
                )
    
    def mark_notification_read(self, notification_id: int, user: User) -> bool:
        """
        Mark a notification as read.

        Args:
            notification_id: ID of notification to mark as read
            user: Current user (tenant scope)

        Returns:
            True if successful, False if notification not found
        """
        notification = (
            tenant_scope.filter_notifications(self.db, user)
            .filter(Notification.id == notification_id)
            .first()
        )

        if not notification:
            return False

        notification.is_read = True
        self.db.commit()
        return True

    def mark_all_read(self, user: User) -> int:
        """
        Mark all notifications as read for this tenant.

        Returns:
            Number of notifications marked as read
        """
        q = tenant_scope.filter_notifications(self.db, user).filter(Notification.is_read == False)  # noqa: E712
        count = q.update({"is_read": True}, synchronize_session=False)
        self.db.commit()
        return count

    def get_unread_count(self, user: User) -> int:
        """Get count of unread notifications for this tenant."""
        return (
            tenant_scope.filter_notifications(self.db, user)
            .filter(Notification.is_read == False)  # noqa: E712
            .count()
        )
    
    def check_expiring_products(self, days_ahead: int = 7) -> List[Dict]:
        """
        Check for products expiring within the specified number of days.
        
        Args:
            days_ahead: Number of days ahead to check (default: 7)
        
        Returns:
            List of products expiring within the specified days
        """
        if days_ahead <= 0:
            return []
        
        today = date.today()
        expiry_threshold = today + timedelta(days=days_ahead)
        
        # Get all active products with expiry dates
        products = self.db.query(Product).filter(
            and_(
                Product.is_active == True,
                Product.expiry_date.isnot(None),
                Product.expiry_date >= today,
                Product.expiry_date <= expiry_threshold
            )
        ).all()
        
        expiring_products = []
        for product in products:
            days_until_expiry = (product.expiry_date - today).days
            expiring_products.append({
                'id': product.id,
                'name': product.name,
                'expiry_date': product.expiry_date,
                'days_until_expiry': days_until_expiry,
                'stock_qty': product.stock_qty
            })
        
        return expiring_products
    
    def check_expiring_products_and_create_notifications(self, days_ahead: int = 7) -> int:
        """
        Check for products expiring within the specified days and create notifications.
        Prevents duplicate notifications for the same product.
        
        Args:
            days_ahead: Number of days ahead to check (default: 7)
        
        Returns:
            Number of notifications created
        """
        if days_ahead <= 0:
            return 0
        
        today = date.today()
        expiry_threshold = today + timedelta(days=days_ahead)
        
        # Get all active products with expiry dates
        products = self.db.query(Product).filter(
            and_(
                Product.is_active == True,
                Product.expiry_date.isnot(None),
                Product.expiry_date >= today,
                Product.expiry_date <= expiry_threshold
            )
        ).all()
        
        notifications_created = 0
        
        for product in products:
            # Check if there's already an unread notification for this product
            existing_notification = self.db.query(Notification).filter(
                and_(
                    Notification.product_id == product.id,
                    Notification.type == "EXPIRY_WARNING",
                    Notification.is_read == False
                )
            ).first()
            
            if existing_notification:
                # Already have an unread notification, don't create duplicate
                continue
            
            days_until_expiry = (product.expiry_date - today).days
            expiry_date_str = product.expiry_date.strftime('%Y-%m-%d')
            
            if days_until_expiry == 0:
                message = f"{product.name} is expiring today ({expiry_date_str})"
            elif days_until_expiry == 1:
                message = f"{product.name} is expiring tomorrow ({expiry_date_str})"
            else:
                message = f"{product.name} is expiring in {days_until_expiry} days ({expiry_date_str})"
            
            notification = Notification(
                type="EXPIRY_WARNING",
                message=message,
                product_id=product.id,
                is_read=False,
                tenant_id=getattr(product, "tenant_id", None),
            )
            self.db.add(notification)
            notifications_created += 1
            logger.info(f"Created expiry notification for product {product.id} ({product.name}) - Expires: {expiry_date_str}")
        
        if notifications_created > 0:
            self.db.commit()
            logger.info(f"Created {notifications_created} expiry notifications")
        
        return notifications_created
    
    def check_expiring_products_and_send_email(self, days_ahead: int = 7) -> None:
        """
        Check for products expiring within the specified days and send tenant-scoped emails.
        """
        settings_rows = self.db.query(StoreSettings).all()
        if not settings_rows:
            logger.warning(
                "check_expiring_products_and_send_email: no StoreSettings; skipping"
            )
            return

        by_tenant: Dict[Optional[int], StoreSettings] = {}
        for s in settings_rows:
            tid = getattr(s, "tenant_id", None)
            if tid not in by_tenant:
                by_tenant[tid] = s

        # check_expiring_products returns product dicts — prefer per-tenant filtering
        all_expiring = self.check_expiring_products(days_ahead)
        if not all_expiring:
            return

        # Group by product tenant via DB lookup
        by_tid_products: Dict[Optional[int], List[dict]] = {}
        for item in all_expiring:
            pid = item.get("product_id") or item.get("id")
            product = None
            if pid:
                product = self.db.query(Product).filter(Product.id == pid).first()
            tid = getattr(product, "tenant_id", None) if product else None
            by_tid_products.setdefault(tid, []).append(item)

        for tid, products in by_tid_products.items():
            settings = by_tenant.get(tid)
            if not settings:
                logger.warning(
                    "expiry email: no StoreSettings for tenant_id=%s; skip", tid
                )
                continue
            if not settings.low_stock_email_enabled or not settings.notification_email:
                continue
            try:
                store_name = settings.store_name or "Store"
                success = email_service.send_expiry_batch_alert(
                    to_email=settings.notification_email,
                    products=products,
                    store_name=store_name,
                    days_ahead=days_ahead,
                )
                if success:
                    logger.info(
                        "Sent expiry email for tenant_id=%s (%s products)",
                        tid,
                        len(products),
                    )
                else:
                    logger.warning("Failed expiry email for tenant_id=%s", tid)
            except Exception as e:
                logger.error(
                    "Error sending expiry email for tenant_id=%s: %s", tid, e, exc_info=True
                )

