# Google Sheets Backup Setup Guide

This guide will help you set up automatic inventory backup to Google Sheets.

## Features

- ✅ Automatic backup of inventory to Google Sheets when online
- ✅ Offline change tracking - changes made offline are queued and synced when internet is available
- ✅ Deletion sync - products deleted offline are removed from backup when online
- ✅ Manual sync and restore options
- ✅ Background processing of pending changes

## Setup Instructions

### Step 1: Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the Google Sheets API:
   - Go to "APIs & Services" > "Library"
   - Search for "Google Sheets API"
   - Click "Enable"

### Step 2: Create a Service Account

1. Go to "APIs & Services" > "Credentials"
2. Click "Create Credentials" > "Service Account"
3. Fill in the service account details:
   - Name: `pos-backup-service` (or any name you prefer)
   - Click "Create and Continue"
   - Skip role assignment (click "Continue")
   - Click "Done"

### Step 3: Create and Download Service Account Key

1. Click on the service account you just created
2. Go to the "Keys" tab
3. Click "Add Key" > "Create new key"
4. Select "JSON" format
5. Click "Create" - this will download a JSON file
6. Save this file to your POS system (e.g., `/home/morrison/Desktop/pos/credentials.json`)

### Step 4: Create a Google Spreadsheet

1. Go to [Google Sheets](https://sheets.google.com/)
2. Create a new spreadsheet
3. Name it (e.g., "POS Inventory Backup")
4. Copy the Spreadsheet ID from the URL:
   - URL format: `https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit`
   - Copy the `SPREADSHEET_ID` part

### Step 5: Share Spreadsheet with Service Account

1. Open your Google Spreadsheet
2. Click the "Share" button (top right)
3. Add the service account email (found in the JSON file, looks like `xxxxx@xxxxx.iam.gserviceaccount.com`)
4. Give it "Editor" permissions
5. Click "Send" (you can uncheck "Notify people")

### Step 6: Configure Backup in POS System

1. Log in to the admin panel
2. Click the settings icon (⚙️) in the floating icons
3. Scroll down to "Google Sheets Backup" section
4. Fill in the configuration:
   - **Enable Google Sheets Backup**: Check this box
   - **Google Spreadsheet ID**: Paste the Spreadsheet ID from Step 4
   - **Service Account JSON File Path**: Enter the full path to your credentials.json file (e.g., `/home/morrison/Desktop/pos/credentials.json`)
   - **Sheet Name**: Leave as "Inventory" (or change if you prefer)
5. Click "Save Configuration"

### Step 7: Initial Sync

1. After saving configuration, click "Sync All Products Now"
2. Wait for the sync to complete
3. Check your Google Spreadsheet - you should see all your products

## Usage

### Automatic Backup

Once configured, the system will:
- Automatically backup products when they are created, updated, or deleted (when online)
- Queue changes when offline and sync them when internet is available
- Process pending changes every minute in the background

### Manual Operations

- **Sync All Products Now**: Manually sync all products to Google Sheets
- **Process Pending Changes**: Process any queued offline changes immediately
- **Import from Backup**: Restore products from Google Sheets (useful after factory reset)

### After Factory Reset

1. After factory reset, log in with default credentials (admin/admin)
2. Go to Settings > Google Sheets Backup
3. Configure the backup settings again (if needed)
4. Click "Import from Backup" to restore all products from Google Sheets

## Troubleshooting

### "Backup not enabled or configured"
- Make sure you've checked "Enable Google Sheets Backup"
- Verify the Spreadsheet ID is correct
- Verify the credentials file path is correct and the file exists

### "No internet connection"
- Check your internet connection
- The system will queue changes and sync when connection is restored

### "Error initializing Google Sheets client"
- Verify the credentials JSON file is valid
- Check that the service account email has been shared with the spreadsheet
- Make sure the Google Sheets API is enabled in your Google Cloud project

### Pending changes not syncing
- Click "Process Pending Changes" manually
- Check the backup status to see if internet is connected
- Check server logs for error messages

## File Locations

- **Backup Configuration**: `backup_config.json` (in project root)
- **Offline Queue**: `offline_changes.json` (in project root)
- **Credentials File**: Wherever you saved the JSON file from Google Cloud

## Security Notes

- Keep your credentials.json file secure and don't share it
- The service account only has access to the specific spreadsheet you share with it
- Consider restricting file permissions on the credentials file: `chmod 600 credentials.json`

