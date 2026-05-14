#!/bin/bash
# Interactive email setup script for POS system

echo "=========================================="
echo "POS Email Configuration Setup"
echo "=========================================="
echo ""

# Check if .env file exists
if [ -f .env ]; then
    echo "⚠️  .env file already exists."
    read -p "Do you want to overwrite it? (y/N): " overwrite
    if [[ ! $overwrite =~ ^[Yy]$ ]]; then
        echo "Keeping existing .env file."
        exit 0
    fi
fi

echo "Select your email provider:"
echo "1) Gmail"
echo "2) Outlook/Office 365"
echo "3) Yahoo Mail"
echo "4) Custom SMTP"
echo ""
read -p "Enter choice (1-4): " choice

case $choice in
    1)
        SMTP_HOST="smtp.gmail.com"
        SMTP_PORT="587"
        echo ""
        echo "For Gmail, you need to:"
        echo "1. Enable 2-Factor Authentication"
        echo "2. Generate an App Password at: https://myaccount.google.com/apppasswords"
        echo ""
        read -p "Enter your Gmail address: " SMTP_USER
        read -sp "Enter your App Password (16 characters): " SMTP_PASSWORD
        echo ""
        ;;
    2)
        SMTP_HOST="smtp.office365.com"
        SMTP_PORT="587"
        read -p "Enter your Outlook email: " SMTP_USER
        read -sp "Enter your password: " SMTP_PASSWORD
        echo ""
        ;;
    3)
        SMTP_HOST="smtp.mail.yahoo.com"
        SMTP_PORT="587"
        read -p "Enter your Yahoo email: " SMTP_USER
        read -sp "Enter your App Password: " SMTP_PASSWORD
        echo ""
        ;;
    4)
        read -p "Enter SMTP host: " SMTP_HOST
        read -p "Enter SMTP port (587 for TLS, 465 for SSL): " SMTP_PORT
        read -p "Enter SMTP username/email: " SMTP_USER
        read -sp "Enter SMTP password: " SMTP_PASSWORD
        echo ""
        ;;
    *)
        echo "Invalid choice. Exiting."
        exit 1
        ;;
esac

read -p "Enter 'from' email address (or press Enter to use $SMTP_USER): " SMTP_FROM_EMAIL
SMTP_FROM_EMAIL=${SMTP_FROM_EMAIL:-$SMTP_USER}

# Create .env file
cat > .env << EOF
# SMTP Email Configuration
SMTP_HOST=$SMTP_HOST
SMTP_PORT=$SMTP_PORT
SMTP_USER=$SMTP_USER
SMTP_PASSWORD=$SMTP_PASSWORD
SMTP_USE_TLS=true
SMTP_FROM_EMAIL=$SMTP_FROM_EMAIL
EOF

echo ""
echo "✅ .env file created!"
echo ""
echo "To test your configuration, run:"
echo "  python3 test_email.py"
echo ""
echo "Or start the server and configure notification email in Admin Settings."

