# Email Setup Guide for Low-Stock Notifications

This guide will help you configure SMTP email settings to enable low-stock email notifications.

## Quick Setup

### Option 1: Using Environment Variables (Recommended)

Set these environment variables before starting the server:

```bash
export SMTP_HOST=smtp.gmail.com
export SMTP_PORT=587
export SMTP_USER=your-email@gmail.com
export SMTP_PASSWORD=your-app-password
export SMTP_USE_TLS=true
export SMTP_FROM_EMAIL=your-email@gmail.com
```

### Option 2: Create a `.env` File

Create a `.env` file in the project root:

```bash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_USE_TLS=true
SMTP_FROM_EMAIL=your-email@gmail.com
```

Then load it before starting the server (you may need to install python-dotenv):
```bash
pip install python-dotenv
```

And modify `start_server.sh` to load the .env file.

## Email Provider Configurations

### Gmail Setup

1. **Enable 2-Factor Authentication** on your Google account
2. **Generate an App Password**:
   - Go to https://myaccount.google.com/apppasswords
   - Select "Mail" and "Other (Custom name)"
   - Enter "POS System" as the name
   - Copy the 16-character password

3. **Configuration**:
   ```
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=your-email@gmail.com
   SMTP_PASSWORD=xxxx xxxx xxxx xxxx  (the 16-char app password)
   SMTP_USE_TLS=true
   ```

### Outlook/Office 365 Setup

```
SMTP_HOST=smtp.office365.com
SMTP_PORT=587
SMTP_USER=your-email@outlook.com
SMTP_PASSWORD=your-password
SMTP_USE_TLS=true
```

### Yahoo Mail Setup

```
SMTP_HOST=smtp.mail.yahoo.com
SMTP_PORT=587
SMTP_USER=your-email@yahoo.com
SMTP_PASSWORD=your-app-password
SMTP_USE_TLS=true
```

### Custom SMTP Server

```
SMTP_HOST=mail.yourdomain.com
SMTP_PORT=587 (or 465 for SSL)
SMTP_USER=notifications@yourdomain.com
SMTP_PASSWORD=your-password
SMTP_USE_TLS=true (or false if using port 465 with SSL)
```

## Testing Email Configuration

### Method 1: Test via Admin Settings

1. Start the server
2. Go to Admin → Store Settings
3. Enter your notification email address
4. Enable "Low-stock email alerts"
5. Create a test sale that triggers low stock
6. Check your email inbox

### Method 2: Test via Python Script

Create a test file `test_email.py`:

```python
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from app.email_service import email_service

# Test email sending
success = email_service.send_low_stock_alert(
    to_email="your-test-email@example.com",
    product_name="Test Product",
    current_stock=5.0,
    threshold=10.0,
    store_name="Test Store"
)

if success:
    print("✅ Email sent successfully!")
else:
    print("❌ Email failed. Check your SMTP configuration.")
```

Run it:
```bash
python3 test_email.py
```

## Troubleshooting

### "Email service not configured"
- Make sure all SMTP environment variables are set
- Check that SMTP_USER and SMTP_PASSWORD are not empty

### "Authentication failed"
- For Gmail: Make sure you're using an App Password, not your regular password
- Check that 2FA is enabled (required for App Passwords)
- Verify username and password are correct

### "Connection timeout"
- Check your firewall settings
- Verify SMTP_HOST and SMTP_PORT are correct
- Try using port 465 with SSL instead of 587 with TLS

### "Email not received"
- Check spam/junk folder
- Verify the notification email address in Admin Settings
- Check server logs for error messages
- Make sure "Low-stock email alerts" is enabled in settings

## Security Notes

- **Never commit `.env` files to git** - add `.env` to `.gitignore`
- Use App Passwords instead of your main account password
- Consider using a dedicated email account for notifications
- For production, use environment variables or a secure secrets manager

## Updating the Server Script

If you want to use a `.env` file, update `start_server.sh`:

```bash
#!/bin/bash
cd "$(dirname "$0")"

# Load environment variables from .env file if it exists
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Rest of your start script...
```

## Verification Checklist

- [ ] Environment variables set or `.env` file created
- [ ] SMTP credentials are correct
- [ ] Notification email configured in Admin Settings
- [ ] "Low-stock email alerts" enabled in Admin Settings
- [ ] Test email sent successfully
- [ ] Low-stock notification triggered and email received

