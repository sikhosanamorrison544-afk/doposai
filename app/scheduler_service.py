"""
Scheduler Service for running periodic tasks like stock checks.
"""

import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .database import SessionLocal
from .notification_service import NotificationService

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler: Optional[AsyncIOScheduler] = None


def get_scheduler() -> Optional[AsyncIOScheduler]:
    """Get the global scheduler instance."""
    return scheduler


async def check_stock_and_send_email():
    """
    Check all products for low stock, create notifications, and send email if enabled.
    This function is called by the scheduler.
    """
    db = SessionLocal()
    try:
        logger.info("Running scheduled stock check...")
        notification_service = NotificationService(db)
        
        # First, create notifications for out-of-stock and qty <= 5 items
        notifications_created = notification_service.check_all_products_and_create_notifications()
        if notifications_created > 0:
            logger.info(f"Created {notifications_created} notifications during scheduled check")
        
        # Then, send email if enabled
        notification_service.check_all_products_low_stock()
        logger.info("Scheduled stock check completed")
    except Exception as e:
        logger.error(f"Error in scheduled stock check: {e}", exc_info=True)
    finally:
        db.close()


async def check_expiring_products_and_send_email():
    """
    Check for products expiring within 7 days, create notifications, and send email if enabled.
    This function is called by the scheduler daily.
    """
    db = SessionLocal()
    try:
        logger.info("Running scheduled expiry check...")
        notification_service = NotificationService(db)
        
        # Create notifications for products expiring within 7 days
        notifications_created = notification_service.check_expiring_products_and_create_notifications(days_ahead=7)
        if notifications_created > 0:
            logger.info(f"Created {notifications_created} expiry notifications during scheduled check")
        
        # Send email if enabled
        notification_service.check_expiring_products_and_send_email(days_ahead=7)
        logger.info("Scheduled expiry check completed")
    except Exception as e:
        logger.error(f"Error in scheduled expiry check: {e}", exc_info=True)
    finally:
        db.close()


def start_scheduler():
    """
    Start the scheduler with stock check jobs.
    Jobs run at 5pm on Sundays and Fridays.
    """
    global scheduler
    
    if scheduler is not None:
        logger.warning("Scheduler is already running")
        return
    
    scheduler = AsyncIOScheduler()
    
    # Schedule stock check for Sundays at 5:00 PM
    scheduler.add_job(
        check_stock_and_send_email,
        trigger=CronTrigger(day_of_week='sun', hour=17, minute=0),
        id='stock_check_sunday',
        name='Low Stock Check - Sunday 5pm',
        replace_existing=True
    )
    
    # Schedule stock check for Fridays at 5:00 PM
    scheduler.add_job(
        check_stock_and_send_email,
        trigger=CronTrigger(day_of_week='fri', hour=17, minute=0),
        id='stock_check_friday',
        name='Low Stock Check - Friday 5pm',
        replace_existing=True
    )
    
    # Schedule expiry check daily at 9:00 AM
    scheduler.add_job(
        check_expiring_products_and_send_email,
        trigger=CronTrigger(hour=9, minute=0),
        id='expiry_check_daily',
        name='Product Expiry Check - Daily 9am',
        replace_existing=True
    )
    
    scheduler.start()
    logger.info("Stock check scheduler started")
    logger.info("Scheduled jobs:")
    for job in scheduler.get_jobs():
        logger.info(f"  - {job.name} (ID: {job.id}) - Next run: {job.next_run_time}")


def stop_scheduler():
    """Stop the scheduler."""
    global scheduler
    
    if scheduler is None:
        return
    
    scheduler.shutdown(wait=True)
    scheduler = None
    logger.info("Stock check scheduler stopped")

