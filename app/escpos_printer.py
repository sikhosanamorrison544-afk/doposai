"""
Optimized ESC/POS printing helper for thermal receipt printers.

This module writes raw bytes directly to the printer device
(e.g. `/dev/usb/lp0` or `/dev/ttyUSB0`).
Supports 48mm and 80mm thermal printers.
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Optional

from .config import PRINTER_DEVICE
from .receipt_store import normalize_store_receipt_fields

logger = logging.getLogger(__name__)

# Receipt width (40mm = 32 chars, 48mm = 32 chars, 80mm = 48 chars)
RECEIPT_WIDTH = 48  # 80mm receipt width


def _write_store_header_block(
    write,
    store_name: str,
    store_location: Optional[str],
    store_phone: Optional[str],
) -> None:
    """Print store name, address, and phone on every receipt (centered)."""
    name, address, phone = normalize_store_receipt_fields(
        store_name, store_phone, store_location
    )
    write(b"\x1b\x61\x01")  # center
    write(b"\x1b\x21\x08")  # bold
    write(name.upper().encode("ascii", errors="ignore") + b"\n")
    write(b"\x1b\x21\x00")
    write(address[:RECEIPT_WIDTH].encode("ascii", errors="ignore") + b"\n")
    write(f"Tel: {phone}"[:RECEIPT_WIDTH].encode("ascii", errors="ignore") + b"\n")
    write(b"\x1b\x61\x00")  # left


def _safe_open_printer() -> Optional[object]:
    """Safely open printer device, return None if unavailable."""
    try:
        return open(PRINTER_DEVICE, "wb", buffering=0)
    except FileNotFoundError:
        logger.error(f"Printer device not found: {PRINTER_DEVICE}")
        return None
    except PermissionError:
        logger.error(f"Permission denied accessing printer device: {PRINTER_DEVICE}")
        return None
    except OSError as e:
        logger.error(f"OS error opening printer device {PRINTER_DEVICE}: {e}")
        return None


def print_receipt(
    sale_id: int,
    store_name: str,
    items: Iterable[dict],
    subtotal: Decimal,
    discount_total: Decimal,
    total: Decimal,
    payments: Iterable[dict],
    customer_name: Optional[str] = None,
    cashier_name: Optional[str] = None,
    cashier_role: Optional[str] = None,
    store_phone: Optional[str] = None,
    store_location: Optional[str] = None,
    footer: str = "Thank you for shopping with us!",
    collection_status: Optional[str] = None,
) -> bool:
    """
    Print an optimized receipt.

    `items` is an iterable of dicts: {name, qty, unit_price, line_total}
    `payments` is an iterable of dicts: {method, amount}
    Returns True if print succeeded, False otherwise.
    """
    printer = _safe_open_printer()
    if printer is None:
        logger.warning(f"Could not open printer device: {PRINTER_DEVICE}")
        return False

    errors = []

    def write(cmd: bytes) -> None:
        try:
            printer.write(cmd)
        except OSError as e:
            errors.append(str(e))

    try:
        # Initialize printer and set character size for 80mm receipt
        write(b"\x1b\x40")  # ESC @ (initialize)
        write(b"\x1b\x21\x00")  # ESC ! 0 (normal size - 1x1)

        _write_store_header_block(write, store_name, store_location, store_phone)

        # Separator line
        write(b"=" * RECEIPT_WIDTH + b"\n")

        # Sale info
        now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        write(f"Sale #: {sale_id}\n".encode("ascii", errors="ignore"))
        write(f"Date:   {now_str}\n".encode("ascii", errors="ignore"))
        
        # Cashier/Admin information
        if cashier_name:
            cashier_display = str(cashier_name)[:RECEIPT_WIDTH - 15]
            role_display = ""
            if cashier_role:
                role_display = f" ({cashier_role.upper()})"
            write(f"Cashier:{role_display} {cashier_display}\n".encode("ascii", errors="ignore"))
        
        # Customer name if provided
        if customer_name:
            cust_name = str(customer_name)[:RECEIPT_WIDTH - 10]
            write(f"Customer: {cust_name}\n".encode("ascii", errors="ignore"))
        
        # Collection status
        if collection_status:
            write(b"\x1b\x45\x01")  # bold on
            if collection_status == "to_collect":
                write(b"STATUS: COLLECTION PENDING\n")
            elif collection_status == "collected":
                write(b"STATUS: COLLECTED\n")
            write(b"\x1b\x45\x00")  # bold off
        
        write(b"-" * RECEIPT_WIDTH + b"\n")

        # Items section
        write(b"ITEMS:\n")
        for item in items:
            name = str(item.get("name", ""))[:30]  # Longer for 80mm
            qty = item.get("qty", 1)
            unit_price = Decimal(item.get("unit_price", 0))
            line_total = Decimal(item.get("line_total", 0))
            
            # Item name (may wrap)
            write(name.encode("ascii", errors="ignore") + b"\n")
            
            # Quantity, unit price, and line total
            try:
                qty_int = int(qty)
                qty_str = str(qty_int)
            except (ValueError, TypeError):
                qty_str = str(int(float(qty))) if qty else "0"
            line = f"  {qty_str} x {unit_price:.2f} = {line_total:.2f}\n"
            write(line.encode("ascii", errors="ignore"))

        write(b"-" * RECEIPT_WIDTH + b"\n")

        # Totals section
        write(f"Subtotal:     {subtotal:>10.2f}\n".encode("ascii", errors="ignore"))
        if discount_total and discount_total > 0:
            write(f"Discount:     {discount_total:>10.2f}\n".encode("ascii", errors="ignore"))
        write(b"\x1b\x45\x01")  # bold on
        write(f"TOTAL:        {total:>10.2f}\n".encode("ascii", errors="ignore"))
        write(b"\x1b\x45\x00")  # bold off
        write(b"=" * RECEIPT_WIDTH + b"\n")

        # Payments section
        write(b"PAYMENT:\n")
        payment_total = Decimal(0)
        for p in payments:
            method = str(p.get("method", "")).upper()
            amount = Decimal(p.get("amount", 0))
            payment_total += amount
            # Format method name nicely
            method_display = method.replace("_", " ").title()[:15]
            write(f"{method_display:<15} {amount:>10.2f}\n".encode("ascii", errors="ignore"))
        
        # Calculate and show change
        change = payment_total - total
        if change > 0:
            write(b"\x1b\x45\x01")  # bold on
            write(f"CHANGE:       {change:>10.2f}\n".encode("ascii", errors="ignore"))
            write(b"\x1b\x45\x00")  # bold off

        write(b"=" * RECEIPT_WIDTH + b"\n")

        # Footer - ensure it fits on receipt width
        write(b"\n")
        write(b"\x1b\x61\x01")  # center align
        # Wrap footer text if too long for 40mm
        footer_lines = footer.split('\n')
        for line in footer_lines:
            if len(line) > RECEIPT_WIDTH:
                # Split long lines
                words = line.split()
                current_line = ""
                for word in words:
                    if len(current_line) + len(word) + 1 <= RECEIPT_WIDTH:
                        current_line += (word + " ") if current_line else word
                    else:
                        if current_line:
                            write(current_line.encode("ascii", errors="ignore") + b"\n")
                        current_line = word
                if current_line:
                    write(current_line.encode("ascii", errors="ignore") + b"\n")
            else:
                write(line.encode("ascii", errors="ignore") + b"\n")
        write(b"\x1b\x61\x00")  # left align
        
        # Add minimal spacing before cut (optimized for speed)
        write(b"\n" * 2)  # Reduced from 5 to 2 blank lines

        # Feed paper minimal lines before cutting (optimized for speed)
        write(b"\x1b\x64\x03")  # ESC d 3 (feed 3 lines - reduced from 10)
        
        # Cut paper (partial cut with minimal feed)
        write(b"\x1d\x56\x42\x03")  # GS V B 3 (feed 3 more lines then cut - reduced from 10)

        # Flush all data to ensure it's sent to printer
        try:
            printer.flush()
            logger.info(f"Receipt printed successfully for sale #{sale_id}")
        except OSError as e:
            logger.error(f"Error flushing printer data: {e}")
            errors.append(f"Flush error: {e}")

        if errors:
            logger.error(f"Printer write errors occurred: {errors}")
        return len(errors) == 0

    except Exception as e:
        logger.error(f"Exception during receipt printing: {e}", exc_info=True)
        errors.append(str(e))
        return False
    finally:
        try:
            printer.flush()  # Try to flush before closing
            printer.close()
        except OSError:
            pass


def print_withdrawal_receipt(
    withdrawal_id: int,
    receipt_number: str,
    store_name: str,
    amount: Decimal,
    reason: str,
    cashier_name: str,
    notes: Optional[str] = None,
    store_phone: Optional[str] = None,
    store_location: Optional[str] = None,
    salary_details: Optional[dict] = None,
) -> bool:
    """
    Print a withdrawal receipt.
    Returns True if print succeeded, False otherwise.
    """
    printer = _safe_open_printer()
    if printer is None:
        logger.warning(f"Could not open printer device: {PRINTER_DEVICE}")
        return False

    errors = []

    def write(cmd: bytes) -> None:
        try:
            printer.write(cmd)
        except OSError as e:
            errors.append(str(e))

    try:
        # Initialize printer and set character size for 80mm receipt
        write(b"\x1b\x40")  # ESC @ (initialize)
        write(b"\x1b\x21\x00")  # ESC ! 0 (normal size - 1x1)

        _write_store_header_block(write, store_name, store_location, store_phone)

        # Separator line
        write(b"=" * RECEIPT_WIDTH + b"\n")
        write(b"\n")

        # Withdrawal header - large and bold
        write(b"\x1b\x61\x01")  # center align
        write(b"\x1b\x21\x18")  # ESC ! 24 (double height and width, bold)
        write(b"WITHDRAWAL RECEIPT\n")
        write(b"\x1b\x21\x00")  # normal size, bold off
        write(b"\n")
        write(b"\x1b\x61\x00")  # left align

        # Separator line
        write(b"-" * RECEIPT_WIDTH + b"\n")
        write(b"\n")

        # Receipt number section
        write(b"\x1b\x21\x08")  # bold on
        write(f"Receipt Number: {receipt_number}\n".encode("ascii", errors="ignore"))
        write(b"\x1b\x21\x00")  # bold off
        
        # Date and time
        now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        write(f"Date & Time: {now_str}\n".encode("ascii", errors="ignore"))
        write(b"\n")

        # Separator line
        write(b"-" * RECEIPT_WIDTH + b"\n")
        write(b"\n")

        # Transaction details header
        write(b"\x1b\x21\x08")  # bold on
        write(b"TRANSACTION DETAILS\n")
        write(b"\x1b\x21\x00")  # bold off
        write(b"\n")

        # Amount - large and prominent
        write(b"\x1b\x61\x01")  # center align
        write(b"\x1b\x21\x18")  # double height and width, bold
        write(f"AMOUNT: ${float(amount):.2f}\n".encode("ascii", errors="ignore"))
        write(b"\x1b\x21\x00")  # normal size, bold off
        write(b"\n")
        write(b"\x1b\x61\x00")  # left align

        # Employee Name - prominent display for salary withdrawals
        if reason == "Salary" and salary_details:
            employee_name = salary_details.get("employee_name", "").strip()
            if employee_name:
                write(b"\n")
                write(b"\x1b\x61\x01")  # center align
                write(b"\x1b\x21\x10")  # double height, bold
                write(b"EMPLOYEE:\n")
                write(b"\x1b\x21\x18")  # double height and width, bold
                write(f"{employee_name}\n".encode("ascii", errors="ignore"))
                write(b"\x1b\x21\x00")  # normal size, bold off
                write(b"\n")
                write(b"\x1b\x61\x00")  # left align

        # Separator line
        write(b"-" * RECEIPT_WIDTH + b"\n")
        write(b"\n")

        # Reason section
        write(b"\x1b\x21\x08")  # bold on
        write(b"Reason for Withdrawal:\n")
        write(b"\x1b\x21\x00")  # bold off
        # Wrap reason if too long
        reason_lines = []
        words = reason.split()
        current_line = ""
        for word in words:
            if len(current_line) + len(word) + 1 <= RECEIPT_WIDTH - 2:
                current_line += (word + " ") if current_line else word
            else:
                if current_line:
                    reason_lines.append(current_line)
                current_line = word
        if current_line:
            reason_lines.append(current_line)
        
        for line in reason_lines:
            write(f"  {line}\n".encode("ascii", errors="ignore"))
        write(b"\n")

        # Employee details section (for salary withdrawals)
        if reason == "Salary" and salary_details:
            write(b"\x1b\x61\x00")  # left align
            write(b"\x1b\x21\x08")  # bold on
            write(b"EMPLOYEE DETAILS\n")
            write(b"\x1b\x21\x00")  # bold off
            write(b"\n")
            
            employee_name = salary_details.get("employee_name", "").strip()
            employee_id = salary_details.get("employee_id", "").strip()
            position = salary_details.get("position", "").strip()
            period = salary_details.get("period", "").strip()
            additional_notes = salary_details.get("additional_notes", "").strip()
            
            if employee_name:
                write(b"\x1b\x21\x08")  # bold on
                write(b"Employee Name:\n")
                write(b"\x1b\x21\x00")  # bold off
                write(f"  {employee_name}\n".encode("ascii", errors="ignore"))
                write(b"\n")
            
            if employee_id:
                write(b"Employee ID:\n".encode("ascii", errors="ignore"))
                write(f"  {employee_id}\n".encode("ascii", errors="ignore"))
                write(b"\n")
            
            if position:
                write(b"Position:\n".encode("ascii", errors="ignore"))
                write(f"  {position}\n".encode("ascii", errors="ignore"))
                write(b"\n")
            
            if period:
                write(b"\x1b\x21\x08")  # bold on
                write(b"Salary Period:\n")
                write(b"\x1b\x21\x00")  # bold off
                write(f"  {period}\n".encode("ascii", errors="ignore"))
                write(b"\n")
            
            if additional_notes:
                write(b"Additional Notes:\n".encode("ascii", errors="ignore"))
                # Wrap additional notes if too long
                notes_lines = []
                words = additional_notes.split()
                current_line = ""
                for word in words:
                    if len(current_line) + len(word) + 1 <= RECEIPT_WIDTH - 2:
                        current_line += (word + " ") if current_line else word
                    else:
                        if current_line:
                            notes_lines.append(current_line)
                        current_line = word
                if current_line:
                    notes_lines.append(current_line)
                
                for line in notes_lines:
                    write(f"  {line}\n".encode("ascii", errors="ignore"))
                write(b"\n")
            
            # Separator line
            write(b"-" * RECEIPT_WIDTH + b"\n")
            write(b"\n")

        # Cashier information
        write(b"\x1b\x21\x08")  # bold on
        write(b"Processed By:\n")
        write(b"\x1b\x21\x00")  # bold off
        write(f"  Cashier: {cashier_name}\n".encode("ascii", errors="ignore"))
        write(b"\n")
        
        # Notes section (if provided)
        if notes and notes.strip():
            write(b"\x1b\x21\x08")  # bold on
            write(b"Additional Notes:\n")
            write(b"\x1b\x21\x00")  # bold off
            # Wrap notes if too long
            notes_lines = []
            words = notes.split()
            current_line = ""
            for word in words:
                if len(current_line) + len(word) + 1 <= RECEIPT_WIDTH - 2:
                    current_line += (word + " ") if current_line else word
                else:
                    if current_line:
                        notes_lines.append(current_line)
                    current_line = word
            if current_line:
                notes_lines.append(current_line)
            
            for line in notes_lines:
                write(f"  {line}\n".encode("ascii", errors="ignore"))
            write(b"\n")

        # Separator line
        write(b"=" * RECEIPT_WIDTH + b"\n")
        write(b"\n")

        # Important notice
        write(b"\x1b\x61\x01")  # center align
        write(b"\x1b\x21\x08")  # bold on
        write(b"IMPORTANT NOTICE\n")
        write(b"\x1b\x21\x00")  # bold off
        write(b"\n")
        write(b"This is an official record\n")
        write(b"of money withdrawal from\n")
        write(b"the business account.\n")
        write(b"\n")
        write(b"Please keep this receipt\n")
        write(b"for your records.\n")
        write(b"\n")
        write(b"\x1b\x61\x00")  # left align

        # Separator line
        write(b"=" * RECEIPT_WIDTH + b"\n")
        write(b"\n")

        # Footer
        write(b"\x1b\x61\x01")  # center align
        write(b"Thank you for your business!\n")
        write(b"\n")
        write(b"\x1b\x61\x00")  # left align

        # Add minimal spacing before cut (optimized for speed)
        write(b"\n" * 2)  # Reduced from 3 to 2 blank lines

        # Feed paper minimal lines before cutting (optimized for speed)
        write(b"\x1b\x64\x03")  # ESC d 3 (feed 3 lines - reduced from 10)

        # Cut paper (partial cut with minimal feed)
        write(b"\x1d\x56\x42\x03")  # GS V B 3 (feed 3 more lines then cut - reduced from 10)

        # Flush all data to ensure it's sent to printer
        try:
            printer.flush()
            logger.info(f"Withdrawal receipt printed successfully for withdrawal #{withdrawal_id}")
        except OSError as e:
            logger.error(f"Error flushing printer data: {e}")
            errors.append(f"Flush error: {e}")

        printer.close()
    except Exception as e:
        logger.error(f"Error printing withdrawal receipt: {e}")
        if printer:
            try:
                printer.close()
            except:
                pass
        return False

    return len(errors) == 0


