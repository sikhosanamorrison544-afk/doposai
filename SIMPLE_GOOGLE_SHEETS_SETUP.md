# Simple Google Sheets Sync Setup Guide

## ✅ No Google Cloud Platform Required!

Your POS system now syncs with Google Sheets using Google Apps Script - completely free and no complex setup needed!

## Quick Setup (3 Steps)

### Step 1: Add Script to Google Sheets

1. Create/open your Google Spreadsheet
2. Go to **Extensions > Apps Script**
3. Copy the entire contents of `GOOGLE_SHEETS_SYNC_SCRIPT.js` from your POS system
4. Paste into the Apps Script editor
5. Click **Save** (Ctrl+S)

### Step 2: Deploy as Web App

1. In Apps Script, click **Deploy > New deployment**
2. Click gear icon ⚙️ → Select **Web app**
3. Set:
   - **Execute as**: Me
   - **Who has access**: Anyone
4. Click **Deploy**
5. **Copy the Web App URL** (looks like: `https://script.google.com/macros/s/.../exec`)

### Step 3: Configure in POS

1. Login to POS Admin Panel
2. Click Settings icon (⚙️)
3. Go to "Google Sheets Backup" section
4. Enter:
   - ✅ Enable backup: Checked
   - Web App URL: Paste the URL from Step 2
   - API Key: (optional - leave empty)
5. Click **Save Configuration**
6. Click **Sync All Products Now**

**Done!** Your inventory is now syncing to Google Sheets automatically! 🎉

## What Happens Now?

- ✅ Products automatically sync when created/updated/deleted
- ✅ Offline changes queue and sync when internet returns
- ✅ All sync happens in the background
- ✅ No Google Cloud Platform needed
- ✅ Completely free

## Troubleshooting

**Not syncing?**
- Check Web App URL is correct (ends with `/exec`)
- Verify deployment has "Who has access: Anyone"
- Check internet connection
- Click "Sync All Products Now" to test

**Need more help?**
See `GOOGLE_SHEETS_SYNC_SETUP.md` for detailed instructions.
