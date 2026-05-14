# Google Sheets Sync Setup (No Google Cloud Platform Required!)

This guide shows you how to set up automatic inventory sync to Google Sheets **without** using Google Cloud Platform or Service Accounts.

## How It Works

Your POS system sends data to a Google Apps Script Web App, which writes directly to your Google Spreadsheet. Simple and free!

## Setup Steps

### Step 1: Create a Google Spreadsheet

1. Go to [Google Sheets](https://sheets.google.com/)
2. Create a new spreadsheet
3. Name it (e.g., "POS Inventory Backup")
4. Leave it open - we'll add the script next

### Step 2: Add the Apps Script

1. In your Google Spreadsheet, go to **Extensions > Apps Script**
2. Delete any existing code in the editor
3. Open the file `GOOGLE_SHEETS_SYNC_SCRIPT.js` from your POS system
4. Copy the entire contents
5. Paste it into the Apps Script editor
6. Click **Save** (Ctrl+S or Cmd+S)
7. Name your project (e.g., "POS Inventory Sync")

### Step 3: Deploy as Web App

1. In the Apps Script editor, click **Deploy > New deployment**
2. Click the gear icon ⚙️ next to "Type"
3. Select **Web app**
4. Configure the deployment:
   - **Description**: "POS Inventory Sync" (optional)
   - **Execute as**: Select **Me** (your email)
   - **Who has access**: Select **Anyone** (this allows your POS system to send data)
5. Click **Deploy**
6. **IMPORTANT**: Copy the **Web app URL** - it looks like:
   ```
   https://script.google.com/macros/s/AKfycbw.../exec
   ```
7. Click "Done"

### Step 4: (Optional) Set API Key for Security

1. In the Apps Script editor, select the function `setApiKey` from the dropdown
2. Click **Run** ▶️
3. Enter an API key (e.g., "my-secret-key-123") or leave blank to disable
4. Copy this API key - you'll need it in Step 5

### Step 5: Configure in POS System

1. Log in to your POS Admin Panel
2. Click the Settings icon (⚙️)
3. Scroll to **Google Sheets Backup** section
4. Fill in:
   - **Enable Google Sheets Backup**: Check this box ✅
   - **Google Apps Script Web App URL**: Paste the URL from Step 3
   - **API Key**: Paste the API key from Step 4 (or leave empty if you didn't set one)
5. Click **Save Configuration**

### Step 6: Test the Sync

1. Click **Sync All Products Now**
2. Wait for success message
3. Go back to your Google Spreadsheet
4. You should see all your products!

## That's It!

Now your inventory will automatically sync to Google Sheets whenever:
- You create a new product
- You update a product
- You delete a product
- You click "Sync All Products Now"

## Troubleshooting

### "Backup not enabled or configured"
- Make sure you checked "Enable Google Sheets Backup"
- Verify the Web App URL is correct (ends with `/exec`)

### "Error sending request to web app"
- Check that your Web App deployment has "Who has access" set to "Anyone"
- Verify the URL is correct
- Check internet connection

### "Invalid API key"
- Make sure the API key in your POS config matches the one you set in Apps Script
- Or remove the API key from both places if you want to disable it

### Data not appearing in Google Sheets
- Make sure you deployed the Apps Script as a Web App (not just saved it)
- Try clicking "Sync All Products Now" again
- Check the Apps Script execution log: **View > Execution log** in Apps Script editor

## Security Note

⚠️ **Keep your Web App URL secret!** Anyone with the URL can write to your spreadsheet. Consider setting an API key for extra security (Step 4).

## No Internet? No Problem!

Changes made offline are queued and will sync automatically when internet is restored. The system processes pending changes every minute.

