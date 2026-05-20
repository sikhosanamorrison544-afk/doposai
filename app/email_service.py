"""
Email Service for sending notifications.
Supports SMTP email sending for low-stock alerts.
"""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import Optional, List
from datetime import datetime
import os
import io

# Try to load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv is optional

logger = logging.getLogger(__name__)


class EmailService:
    """Service for sending emails via SMTP."""
    
    def __init__(self):
        # SMTP configuration from environment variables (optional)
        self.smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER", "")
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        self.smtp_use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
        self.from_email = os.getenv("SMTP_FROM_EMAIL", self.smtp_user)
    
    def is_configured(self) -> bool:
        """Check if email service is configured."""
        return bool(self.smtp_user and self.smtp_password)
    
    def _generate_pdf(self, products: List[dict], store_name: str) -> bytes:
        """
        Generate a PDF document with low-stock products list.
        
        Args:
            products: List of dicts with keys: name, current_stock, threshold
            store_name: Store name for header
        
        Returns:
            PDF content as bytes
        """
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import letter, A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import inch
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
            from reportlab.lib.enums import TA_CENTER, TA_LEFT
            
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
            
            # Container for PDF elements
            elements = []
            
            # Styles
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=18,
                textColor=colors.HexColor('#f44336'),
                spaceAfter=30,
                alignment=TA_CENTER
            )
            
            # Title
            title = Paragraph(f"Low Stock Alert - {store_name}", title_style)
            elements.append(title)
            elements.append(Spacer(1, 0.2*inch))
            
            # Date
            date_text = f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            date_para = Paragraph(date_text, styles['Normal'])
            elements.append(date_para)
            elements.append(Spacer(1, 0.1*inch))
            
            # Summary
            summary_text = f"Total Products with Low Stock: <b>{len(products)}</b>"
            summary_para = Paragraph(summary_text, styles['Normal'])
            elements.append(summary_para)
            elements.append(Spacer(1, 0.2*inch))
            
            # Prepare table data
            table_data = [['#', 'Product Name', 'Current Stock', 'Threshold', 'Status']]
            
            for i, product in enumerate(products, 1):
                is_out_of_stock = product['current_stock'] == 0
                stock_text = "OUT OF STOCK" if is_out_of_stock else str(product['current_stock'])
                status = "🔴 Out of Stock" if is_out_of_stock else "⚠️ Low Stock"
                
                table_data.append([
                    str(i),
                    product['name'],
                    stock_text,
                    str(product['threshold']),
                    status
                ])
            
            # Create table
            table = Table(table_data, colWidths=[0.4*inch, 3.5*inch, 1.2*inch, 1*inch, 1.5*inch])
            
            # Table style
            table_style = TableStyle([
                # Header row
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e40af')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (2, 1), (3, -1), 'CENTER'),  # Center stock and threshold columns
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('TOPPADDING', (0, 0), (-1, 0), 12),
                # Data rows
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 9),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
                # Highlight out-of-stock rows
            ])
            
            # Highlight out-of-stock rows with red background
            for i, product in enumerate(products, 1):
                if product['current_stock'] == 0:
                    table_style.add('BACKGROUND', (0, i), (-1, i), colors.HexColor('#fee2e2'))
                    table_style.add('TEXTCOLOR', (2, i), (2, i), colors.HexColor('#991b1b'))
                    table_style.add('FONTNAME', (2, i), (2, i), 'Helvetica-Bold')
            
            table.setStyle(table_style)
            elements.append(table)
            elements.append(Spacer(1, 0.3*inch))
            
            # Footer note
            note_text = "Please review these products and consider restocking soon to avoid stockouts."
            note_para = Paragraph(note_text, styles['Normal'])
            elements.append(note_para)
            
            # Build PDF
            doc.build(elements)
            buffer.seek(0)
            return buffer.getvalue()
            
        except ImportError:
            logger.warning("reportlab not installed. PDF generation skipped. Install with: pip install reportlab")
            return None
        except Exception as e:
            logger.error(f"Error generating PDF: {e}", exc_info=True)
            return None
    
    def send_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        pdf_attachment: Optional[bytes] = None,
        pdf_filename: Optional[str] = None
    ) -> bool:
        """
        Send an email.
        
        Args:
            to_email: Recipient email address
            subject: Email subject
            body: Plain text email body
            html_body: Optional HTML email body
        
        Returns:
            True if sent successfully, False otherwise
        """
        if not self.is_configured():
            logger.warning("Email service not configured. Skipping email send.")
            return False
        
        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['From'] = self.from_email
            msg['To'] = to_email
            msg['Subject'] = subject
            
            # Add plain text part
            part1 = MIMEText(body, 'plain')
            msg.attach(part1)
            
            # Add HTML part if provided
            if html_body:
                part2 = MIMEText(html_body, 'html')
                msg.attach(part2)
            
            # Add PDF attachment if provided
            if pdf_attachment and pdf_filename:
                part3 = MIMEBase('application', 'pdf')
                part3.set_payload(pdf_attachment)
                encoders.encode_base64(part3)
                part3.add_header(
                    'Content-Disposition',
                    f'attachment; filename= {pdf_filename}'
                )
                msg.attach(part3)
            
            # Send email
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                if self.smtp_use_tls:
                    server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)
            
            logger.info(f"Email sent successfully to {to_email}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending email to {to_email}: {e}", exc_info=True)
            return False
    
    def send_low_stock_alert(
        self,
        to_email: str,
        product_name: str,
        current_stock: float,
        threshold: float,
        store_name: str = "Store"
    ) -> bool:
        """
        Send a low-stock alert email.
        
        Args:
            to_email: Recipient email address
            product_name: Name of the product
            current_stock: Current stock quantity
            threshold: Low stock threshold
            store_name: Store name for email header
        
        Returns:
            True if sent successfully, False otherwise
        """
        subject = f"Low Stock Alert: {product_name}"
        
        body = f"""
Low Stock Alert

Store: {store_name}
Product: {product_name}
Current Stock: {current_stock}
Threshold: {threshold}

This product is running low on stock. Please consider restocking soon.

---
This is an automated notification from your POS system.
"""
        
        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background-color: #f44336; color: white; padding: 20px; text-align: center; }}
        .content {{ background-color: #f9f9f9; padding: 20px; }}
        .alert {{ background-color: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 20px 0; }}
        .info {{ margin: 10px 0; }}
        .label {{ font-weight: bold; }}
        .footer {{ text-align: center; color: #666; font-size: 12px; margin-top: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>⚠️ Low Stock Alert</h2>
        </div>
        <div class="content">
            <div class="alert">
                <strong>{product_name}</strong> is running low on stock!
            </div>
            <div class="info">
                <span class="label">Store:</span> {store_name}
            </div>
            <div class="info">
                <span class="label">Product:</span> {product_name}
            </div>
            <div class="info">
                <span class="label">Current Stock:</span> {current_stock}
            </div>
            <div class="info">
                <span class="label">Threshold:</span> {threshold}
            </div>
            <p style="margin-top: 20px;">
                Please consider restocking this product soon to avoid stockouts.
            </p>
        </div>
        <div class="footer">
            This is an automated notification from your POS system.
        </div>
    </div>
</body>
</html>
"""
        
        return self.send_email(to_email, subject, body, html_body)
    
    def send_low_stock_batch_alert(
        self,
        to_email: str,
        products: List[dict],
        store_name: str = "Store"
    ) -> bool:
        """
        Send a batch low-stock alert email with a list of all low-stock products.
        
        Args:
            to_email: Recipient email address
            products: List of dicts with keys: name, current_stock, threshold
            store_name: Store name for email header
        
        Returns:
            True if sent successfully, False otherwise
        """
        if not products:
            return False
        
        product_count = len(products)
        subject = f"Low Stock Alert: {product_count} Product{'s' if product_count > 1 else ''} Running Low"
        
        # Plain text body
        body = f"""
Low Stock Alert - Multiple Products

Store: {store_name}
Total Products with Low Stock: {product_count}

Products Running Low:
"""
        for i, product in enumerate(products, 1):
            stock_text = "OUT OF STOCK" if product['current_stock'] == 0 else f"{product['current_stock']}"
            body += f"\n{i}. {product['name']}\n"
            body += f"   Current Stock: {stock_text}\n"
            body += f"   Threshold: {product['threshold']}\n"
        
        body += f"""

Please consider restocking these products soon to avoid stockouts.

A detailed PDF report is attached to this email.

---
This is an automated notification from your POS system.
"""
        
        # Generate PDF attachment
        pdf_content = self._generate_pdf(products, store_name)
        pdf_filename = f"low_stock_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        
        # HTML body
        products_html = ""
        for i, product in enumerate(products, 1):
            # Highlight out-of-stock items (stock = 0) differently
            is_out_of_stock = product['current_stock'] == 0
            stock_color = "#991b1b" if is_out_of_stock else "#dc2626"  # Darker red for out of stock
            stock_bg = "rgba(220, 38, 38, 0.1)" if is_out_of_stock else "transparent"
            stock_text = "OUT OF STOCK" if is_out_of_stock else f"{product['current_stock']}"
            row_style = f"background-color: {stock_bg};" if is_out_of_stock else ""
            
            products_html += f"""
            <tr style="border-bottom: 1px solid #ddd; {row_style}">
                <td style="padding: 12px; font-weight: bold;">{i}</td>
                <td style="padding: 12px; font-weight: 500; color: #1e40af;">{product['name']}</td>
                <td style="padding: 12px; text-align: center; color: {stock_color}; font-weight: bold;">{stock_text}</td>
                <td style="padding: 12px; text-align: center;">{product['threshold']}</td>
            </tr>
            """
        
        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 700px; margin: 0 auto; padding: 20px; }}
        .header {{ background-color: #f44336; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
        .content {{ background-color: #f9f9f9; padding: 20px; border-radius: 0 0 8px 8px; }}
        .alert {{ background-color: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 20px 0; border-radius: 4px; }}
        .info {{ margin: 10px 0; }}
        .label {{ font-weight: bold; color: #1e40af; }}
        .footer {{ text-align: center; color: #666; font-size: 12px; margin-top: 20px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        th {{ background-color: #1e40af; color: white; padding: 12px; text-align: left; font-weight: bold; }}
        td {{ padding: 12px; }}
        tr:nth-child(even) {{ background-color: #f8f9fa; }}
        .stock-low {{ color: #dc2626; font-weight: bold; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>⚠️ Low Stock Alert</h2>
            <p style="margin: 10px 0 0 0; font-size: 16px;">{product_count} Product{'s' if product_count > 1 else ''} Running Low</p>
        </div>
        <div class="content">
            <div class="alert">
                <strong>Action Required:</strong> The following products are running low on stock and may need restocking soon.
            </div>
            <div class="info">
                <span class="label">Store:</span> {store_name}
            </div>
            <div class="info">
                <span class="label">Total Products with Low Stock:</span> {product_count}
            </div>
            
            <table>
                <thead>
                    <tr>
                        <th style="width: 50px;">#</th>
                        <th>Product Name</th>
                        <th style="text-align: center; width: 120px;">Current Stock</th>
                        <th style="text-align: center; width: 100px;">Threshold</th>
                    </tr>
                </thead>
                <tbody>
                    {products_html}
                </tbody>
            </table>
            
            <p style="margin-top: 20px; padding: 15px; background-color: #e0f2fe; border-left: 4px solid #0284c7; border-radius: 4px;">
                <strong>💡 Recommendation:</strong> Please review these products and consider restocking them soon to avoid stockouts and maintain smooth operations.
            </p>
        </div>
        <div class="footer">
            This is an automated notification from your POS system.<br>
            Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        </div>
    </div>
</body>
</html>
"""
        
        # Generate PDF attachment
        pdf_content = self._generate_pdf(products, store_name)
        pdf_filename = f"low_stock_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        
        return self.send_email(to_email, subject, body, html_body, pdf_attachment=pdf_content, pdf_filename=pdf_filename)
    
    def send_expiry_batch_alert(
        self,
        to_email: str,
        products: List[dict],
        store_name: str = "Store",
        days_ahead: int = 7
    ) -> bool:
        """
        Send a batch expiry alert email with a list of all products expiring within the specified days.
        
        Args:
            to_email: Recipient email address
            products: List of dicts with keys: id, name, expiry_date, days_until_expiry, stock_qty
            store_name: Store name for email header
            days_ahead: Number of days ahead checked (for email context)
        
        Returns:
            True if sent successfully, False otherwise
        """
        if not products:
            return False
        
        product_count = len(products)
        subject = f"Product Expiry Alert: {product_count} Product{'s' if product_count > 1 else ''} Expiring Within {days_ahead} Days"
        
        # Plain text body
        body = f"""
Product Expiry Alert - Multiple Products

Store: {store_name}
Total Products Expiring Within {days_ahead} Days: {product_count}

Products Expiring Soon:
"""
        for i, product in enumerate(products, 1):
            expiry_date = product['expiry_date']
            if hasattr(expiry_date, 'strftime'):
                expiry_date_str = expiry_date.strftime('%Y-%m-%d')
            else:
                expiry_date_str = str(expiry_date)
            if product['days_until_expiry'] == 0:
                days_text = "TODAY"
            elif product['days_until_expiry'] == 1:
                days_text = "TOMORROW"
            else:
                days_text = f"in {product['days_until_expiry']} days"
            body += f"\n{i}. {product['name']}\n"
            body += f"   Expiry Date: {expiry_date_str}\n"
            body += f"   Expires: {days_text}\n"
            body += f"   Current Stock: {product['stock_qty']}\n"
        
        body += f"""

Please review these products and take appropriate action (sell, discount, or remove) before they expire.

---
This is an automated notification from your POS system.
"""
        
        # HTML body
        products_html = ""
        for i, product in enumerate(products, 1):
            expiry_date = product['expiry_date']
            if hasattr(expiry_date, 'strftime'):
                expiry_date_str = expiry_date.strftime('%Y-%m-%d')
            else:
                expiry_date_str = str(expiry_date)
            days_until = product['days_until_expiry']
            
            # Color coding based on urgency
            if days_until == 0:
                urgency_color = "#991b1b"  # Dark red for today
                urgency_bg = "rgba(220, 38, 38, 0.15)"
                days_text = "<strong>TODAY</strong>"
            elif days_until == 1:
                urgency_color = "#dc2626"  # Red for tomorrow
                urgency_bg = "rgba(239, 68, 68, 0.1)"
                days_text = "<strong>TOMORROW</strong>"
            elif days_until <= 2:
                urgency_color = "#dc2626"  # Red for 2 days
                urgency_bg = "rgba(239, 68, 68, 0.1)"
                days_text = f"<strong>in {days_until} days</strong>"
            else:
                urgency_color = "#f59e0b"  # Orange for 3-7 days
                urgency_bg = "transparent"
                days_text = f"in {days_until} days"
            
            row_style = f"background-color: {urgency_bg};" if urgency_bg != "transparent" else ""
            
            products_html += f"""
            <tr style="border-bottom: 1px solid #ddd; {row_style}">
                <td style="padding: 12px; font-weight: bold;">{i}</td>
                <td style="padding: 12px; font-weight: 500; color: #1e40af;">{product['name']}</td>
                <td style="padding: 12px; text-align: center; color: {urgency_color}; font-weight: bold;">{days_text}</td>
                <td style="padding: 12px; text-align: center;">{expiry_date_str}</td>
                <td style="padding: 12px; text-align: center;">{product['stock_qty']}</td>
            </tr>
            """
        
        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 700px; margin: 0 auto; padding: 20px; }}
        .header {{ background-color: #f59e0b; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
        .content {{ background-color: #f9f9f9; padding: 20px; border-radius: 0 0 8px 8px; }}
        .alert {{ background-color: #fff3cd; border-left: 4px solid #f59e0b; padding: 15px; margin: 20px 0; border-radius: 4px; }}
        .info {{ margin: 10px 0; }}
        .label {{ font-weight: bold; color: #1e40af; }}
        .footer {{ text-align: center; color: #666; font-size: 12px; margin-top: 20px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        th {{ background-color: #f59e0b; color: white; padding: 12px; text-align: left; font-weight: bold; }}
        td {{ padding: 12px; }}
        tr:nth-child(even) {{ background-color: #f8f9fa; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>⏰ Product Expiry Alert</h2>
            <p style="margin: 10px 0 0 0; font-size: 16px;">{product_count} Product{'s' if product_count > 1 else ''} Expiring Within {days_ahead} Days</p>
        </div>
        <div class="content">
            <div class="alert">
                <strong>Action Required:</strong> The following products are expiring soon and may need immediate attention.
            </div>
            <div class="info">
                <span class="label">Store:</span> {store_name}
            </div>
            <div class="info">
                <span class="label">Total Products Expiring:</span> {product_count}
            </div>
            
            <table>
                <thead>
                    <tr>
                        <th style="width: 50px;">#</th>
                        <th>Product Name</th>
                        <th style="text-align: center; width: 120px;">Time Until Expiry</th>
                        <th style="text-align: center; width: 120px;">Expiry Date</th>
                        <th style="text-align: center; width: 100px;">Stock Qty</th>
                    </tr>
                </thead>
                <tbody>
                    {products_html}
                </tbody>
            </table>
            
            <p style="margin-top: 20px; padding: 15px; background-color: #fef3c7; border-left: 4px solid #f59e0b; border-radius: 4px;">
                <strong>💡 Recommendation:</strong> Please review these products and consider selling them at a discount, removing them from inventory, or taking other appropriate action before they expire.
            </p>
        </div>
        <div class="footer">
            This is an automated notification from your POS system.<br>
            Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        </div>
    </div>
</body>
</html>
"""
        
        return self.send_email(to_email, subject, body, html_body)

    def send_customer_statement(
        self,
        to_email: str,
        customer_name: str,
        statement_lines: List[dict],
        balance: float,
        store_name: str = "Store",
        pdf_bytes: Optional[bytes] = None,
    ) -> bool:
        """Email customer account statement with optional PDF attachment."""
        subject = f"Account Statement — {customer_name} — {store_name}"
        rows_text = "\n".join(
            f"  {line.get('date', '')}  {line.get('type', '')}  {line.get('amount', '')}  {line.get('detail') or ''}"
            for line in statement_lines[:40]
        )
        body = f"""Hello {customer_name},

Please find your account statement from {store_name}.

Outstanding balance: {balance:.2f}

Recent activity:
{rows_text}

Thank you for your business.
"""
        rows_html = "".join(
            f"<tr><td>{line.get('date','')}</td><td>{line.get('type','')}</td>"
            f"<td>{line.get('amount','')}</td><td>{line.get('detail') or ''}</td></tr>"
            for line in statement_lines[:40]
        )
        html_body = f"""
        <html><body style="font-family:sans-serif;">
        <h2>Account Statement — {store_name}</h2>
        <p>Hello <strong>{customer_name}</strong>,</p>
        <p>Outstanding balance: <strong>{balance:.2f}</strong></p>
        <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;">
        <tr style="background:#1e40af;color:#fff;"><th>Date</th><th>Type</th><th>Amount</th><th>Detail</th></tr>
        {rows_html}
        </table>
        </body></html>
        """
        filename = f"statement_{customer_name.replace(' ', '_')[:30]}.pdf" if pdf_bytes else None
        return self.send_email(
            to_email,
            subject,
            body,
            html_body,
            pdf_attachment=pdf_bytes,
            pdf_filename=filename,
        )


# Global email service instance
email_service = EmailService()

