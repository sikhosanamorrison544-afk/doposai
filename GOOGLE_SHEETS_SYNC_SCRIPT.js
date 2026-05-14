/**
 * POS Inventory Sync - Google Apps Script Web App
 * 
 * This script receives inventory data from your POS system and syncs it to Google Sheets.
 * No Google Cloud Platform setup required!
 * 
 * Setup Instructions:
 * 1. Open your Google Spreadsheet
 * 2. Go to Extensions > Apps Script
 * 3. Paste this entire script
 * 4. Save (Ctrl+S)
 * 5. Click "Deploy" > "New deployment"
 * 6. Click the gear icon next to "Type" > Select "Web app"
 * 7. Set "Execute as" to "Me"
 * 8. Set "Who has access" to "Anyone"
 * 9. Click "Deploy"
 * 10. Copy the Web app URL and use it in your POS system
 * 
 * IMPORTANT: Keep the Web app URL secret - it gives write access to your spreadsheet!
 */

/**
 * Handle POST requests from POS system
 */
function doPost(e) {
  try {
    // Check if request data exists
    if (!e || !e.postData || !e.postData.contents) {
      return ContentService.createTextOutput(JSON.stringify({
        success: false,
        error: "Invalid request: No POST data received"
      })).setMimeType(ContentService.MimeType.JSON);
    }
    
    // Get the active spreadsheet
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
    
    // Parse the request data
    var postData = JSON.parse(e.postData.contents);
    var action = postData.action; // "sync_all", "create", "update", "delete"
    var data = postData.data;
    
    // Verify API key if provided (optional security)
    var apiKey = postData.api_key;
    var expectedApiKey = PropertiesService.getScriptProperties().getProperty('API_KEY');
    if (expectedApiKey && apiKey !== expectedApiKey) {
      return ContentService.createTextOutput(JSON.stringify({
        success: false,
        error: "Invalid API key"
      })).setMimeType(ContentService.MimeType.JSON);
    }
    
    // Ensure headers exist
    ensureHeaders(sheet);
    
    var result;
    
    switch(action) {
      case "sync_all":
        result = syncAllProducts(sheet, data.products);
        break;
      case "create":
        result = createProduct(sheet, data.product);
        break;
      case "update":
        result = updateProduct(sheet, data.product);
        break;
      case "delete":
        result = deleteProduct(sheet, data.product_id);
        break;
      case "sync_all_debtors":
        result = syncAllDebtors(data.debts, data.grand_total, data.count);
        break;
      case "create_withdrawal":
        result = createWithdrawal(data.withdrawal);
        break;
      case "sync_all_withdrawals":
        Logger.log("=== Received sync_all_withdrawals action ===");
        Logger.log("Data keys: " + Object.keys(data || {}));
        Logger.log("Withdrawals array length: " + (data && data.withdrawals ? data.withdrawals.length : 0));
        result = syncAllWithdrawals(data.withdrawals, data.count);
        break;
      default:
        result = {success: false, error: "Unknown action: " + action};
    }
    
    return ContentService.createTextOutput(JSON.stringify(result))
      .setMimeType(ContentService.MimeType.JSON);
      
  } catch (error) {
    Logger.log("Error: " + error.toString());
    return ContentService.createTextOutput(JSON.stringify({
      success: false,
      error: error.toString()
    })).setMimeType(ContentService.MimeType.JSON);
  }
}

/**
 * Handle GET requests (for testing)
 */
function doGet(e) {
  return ContentService.createTextOutput(JSON.stringify({
    success: true,
    message: "POS Inventory Sync Web App is running",
    timestamp: new Date().toISOString()
  })).setMimeType(ContentService.MimeType.JSON);
}

/**
 * Ensure headers are present in the sheet
 */
function ensureHeaders(sheet) {
  var headerRange = sheet.getRange(1, 1, 1, 9);
  var headers = headerRange.getValues()[0];
  
  // Check if headers are empty or incorrect
  if (!headers[0] || headers[0] !== "ID") {
    var newHeaders = [
      "ID", "Name", "Barcode", "Category", "Stock Qty",
      "Cost Price", "Selling Price", "Is Active", "Last Updated"
    ];
    headerRange.setValues([newHeaders]);
    
    // Format header row
    headerRange.setFontWeight("bold");
    headerRange.setBackground("#4285f4");
    headerRange.setFontColor("#ffffff");
    headerRange.setHorizontalAlignment("center");
  }
}

/**
 * Sync all products (replace all data)
 */
function syncAllProducts(sheet, products) {
  try {
    var lastRow = sheet.getLastRow();
    
    // Clear existing data (except header)
    if (lastRow > 1) {
      sheet.deleteRows(2, lastRow - 1);
    }
    
    // Prepare rows
    var rows = [];
    for (var i = 0; i < products.length; i++) {
      var p = products[i];
      rows.push([
        p.id,
        p.name,
        p.barcode || "",
        p.category || "",
        p.stock_qty,
        p.cost_price,
        p.selling_price,
        p.is_active ? "Yes" : "No",
        new Date().toISOString()
      ]);
    }
    
    // Write all rows at once
    if (rows.length > 0) {
      sheet.getRange(2, 1, rows.length, 9).setValues(rows);
    }
    
    return {
      success: true,
      message: "Synced " + products.length + " products",
      count: products.length
    };
  } catch (error) {
    return {success: false, error: error.toString()};
  }
}

/**
 * Create a new product
 */
function createProduct(sheet, product) {
  try {
    var row = [
      product.id,
      product.name,
      product.barcode || "",
      product.category || "",
      product.stock_qty,
      product.cost_price,
      product.selling_price,
      product.is_active ? "Yes" : "No",
      new Date().toISOString()
    ];
    
    sheet.appendRow(row);
    
    return {success: true, message: "Product created"};
  } catch (error) {
    return {success: false, error: error.toString()};
  }
}

/**
 * Update an existing product
 */
function updateProduct(sheet, product) {
  try {
    var lastRow = sheet.getLastRow();
    var idColumn = 1; // ID is in column A
    
    // Find the row with matching ID
    var data = sheet.getRange(2, idColumn, lastRow - 1, 1).getValues();
    var rowIndex = -1;
    
    for (var i = 0; i < data.length; i++) {
      if (data[i][0] == product.id) {
        rowIndex = i + 2; // +2 because data starts at row 2 (row 1 is header)
        break;
      }
    }
    
    if (rowIndex > 0) {
      // Update existing row
      var row = [
        product.id,
        product.name,
        product.barcode || "",
        product.category || "",
        product.stock_qty,
        product.cost_price,
        product.selling_price,
        product.is_active ? "Yes" : "No",
        new Date().toISOString()
      ];
      sheet.getRange(rowIndex, 1, 1, 9).setValues([row]);
      return {success: true, message: "Product updated"};
    } else {
      // Product not found, create it
      return createProduct(sheet, product);
    }
  } catch (error) {
    return {success: false, error: error.toString()};
  }
}

/**
 * Delete a product
 */
function deleteProduct(sheet, productId) {
  try {
    var lastRow = sheet.getLastRow();
    var idColumn = 1; // ID is in column A
    
    // Find the row with matching ID
    var data = sheet.getRange(2, idColumn, lastRow - 1, 1).getValues();
    
    for (var i = 0; i < data.length; i++) {
      if (data[i][0] == productId) {
        var rowIndex = i + 2; // +2 because data starts at row 2
        sheet.deleteRows(rowIndex, 1);
        return {success: true, message: "Product deleted"};
      }
    }
    
    return {success: false, error: "Product not found"};
  } catch (error) {
    return {success: false, error: error.toString()};
  }
}

/**
 * Sync all debtors to a separate "Debtors" sheet
 */
function syncAllDebtors(debts, grandTotal, count) {
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    
    // Get or create "Debtors" sheet
    var debtorsSheet = ss.getSheetByName("Debtors");
    if (!debtorsSheet) {
      debtorsSheet = ss.insertSheet("Debtors");
    }
    
    // Ensure headers exist
    var headers = ["Customer ID", "Customer Name", "Phone", "Address", "Debt Type", "Outstanding Amount"];
    var headerRange = debtorsSheet.getRange(1, 1, 1, headers.length);
    var existingHeaders = headerRange.getValues()[0];
    
    if (existingHeaders[0] !== headers[0]) {
      // Headers don't match, set them
      headerRange.setValues([headers]);
      headerRange.setFontWeight("bold");
      headerRange.setBackground("#4285f4");
      headerRange.setFontColor("#ffffff");
      
      // Freeze header row
      debtorsSheet.setFrozenRows(1);
      
      // Set column widths
      debtorsSheet.setColumnWidth(1, 100); // Customer ID
      debtorsSheet.setColumnWidth(2, 200); // Customer Name
      debtorsSheet.setColumnWidth(3, 150); // Phone
      debtorsSheet.setColumnWidth(4, 250); // Address
      debtorsSheet.setColumnWidth(5, 120); // Debt Type
      debtorsSheet.setColumnWidth(6, 150); // Outstanding Amount
    }
    
    // Clear existing data (except header)
    var lastRow = debtorsSheet.getLastRow();
    if (lastRow > 1) {
      debtorsSheet.deleteRows(2, lastRow - 1);
    }
    
    // Add grand total row at the top (after header)
    debtorsSheet.insertRowAfter(1);
    var totalRow = debtorsSheet.getRange(2, 1, 1, headers.length);
    totalRow.setValues([["GRAND TOTAL", "", "", "", "", grandTotal || 0]]);
    totalRow.setFontWeight("bold");
    totalRow.setBackground("#fbbc04");
    totalRow.setFontColor("#000000");
    var grandTotalCell = debtorsSheet.getRange(2, 6);
    grandTotalCell.setNumberFormat("$#,##0.00");
    
    // Write debtor data
    if (debts && debts.length > 0) {
      var data = [];
      for (var i = 0; i < debts.length; i++) {
        var debt = debts[i];
        data.push([
          debt.customer_id,
          debt.customer_name,
          debt.phone || "",
          debt.address || "",
          debt.debt_type === "layby" ? "Layby" : "Credit Sale",
          debt.debt_amount
        ]);
      }
      
      if (data.length > 0) {
        var dataRange = debtorsSheet.getRange(3, 1, data.length, headers.length);
        dataRange.setValues(data);
        
        // Format the debt amount column
        var amountRange = debtorsSheet.getRange(3, 6, data.length, 1);
        amountRange.setNumberFormat("$#,##0.00");
        
        // Format debt type column with colors
        var typeRange = debtorsSheet.getRange(3, 5, data.length, 1);
        for (var i = 0; i < data.length; i++) {
          var cell = typeRange.getCell(i + 1, 1);
          if (cell.getValue() === "Layby") {
            cell.setBackground("#e8f0fe");
            cell.setFontColor("#1967d2");
          } else {
            cell.setBackground("#fef7e0");
            cell.setFontColor("#ea8600");
          }
        }
      }
    }
    
    // Add summary row at the bottom
    var summaryRow = debtorsSheet.getLastRow() + 1;
    var summaryRange = debtorsSheet.getRange(summaryRow, 1, 1, headers.length);
    summaryRange.setValues([["TOTAL DEBTORS", (count || 0).toString(), "", "", "", grandTotal || 0]]);
    summaryRange.setFontWeight("bold");
    summaryRange.setBackground("#34a853");
    summaryRange.setFontColor("#ffffff");
    var summaryTotalCell = debtorsSheet.getRange(summaryRow, 6);
    summaryTotalCell.setNumberFormat("$#,##0.00");
    
    return {
      success: true,
      message: "Debtors synced successfully",
      count: count || 0,
      grand_total: grandTotal || 0
    };
  } catch (error) {
    Logger.log("Error syncing debtors: " + error.toString());
    return {
      success: false,
      error: error.toString()
    };
  }
}

/**
 * Create a new withdrawal record
 */
function createWithdrawal(withdrawal) {
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var withdrawalsSheet = ss.getSheetByName("Withdrawals");
    if (!withdrawalsSheet) {
      // Create the sheet if it doesn't exist
      withdrawalsSheet = ss.insertSheet("Withdrawals");
      Logger.log("Created new 'Withdrawals' sheet for single withdrawal");
      ensureWithdrawalHeaders(withdrawalsSheet);
    } else {
      // Ensure headers exist even if sheet exists
      ensureWithdrawalHeaders(withdrawalsSheet);
    }
    
    var row = [
      withdrawal.id,
      withdrawal.cashier_id,
      withdrawal.cashier_name,
      withdrawal.amount,
      withdrawal.reason,
      withdrawal.receipt_number || "",
      withdrawal.created_at || new Date().toISOString(),
      withdrawal.notes || ""
    ];
    
    withdrawalsSheet.appendRow(row);
    
    return {success: true, message: "Withdrawal created"};
  } catch (error) {
    Logger.log("Error creating withdrawal: " + error.toString());
    return {success: false, error: error.toString()};
  }
}

/**
 * Sync all withdrawals to a separate "Withdrawals" sheet
 */
function syncAllWithdrawals(withdrawals, count) {
  try {
    Logger.log("=== syncAllWithdrawals called ===");
    Logger.log("Withdrawals count: " + (count || 0));
    Logger.log("Withdrawals array length: " + (withdrawals ? withdrawals.length : 0));
    
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    Logger.log("Active spreadsheet: " + ss.getName());
    
    // Get or create "Withdrawals" sheet
    var withdrawalsSheet = ss.getSheetByName("Withdrawals");
    if (!withdrawalsSheet) {
      // Create the sheet if it doesn't exist
      Logger.log("Sheet 'Withdrawals' not found, creating new sheet...");
      withdrawalsSheet = ss.insertSheet("Withdrawals");
      Logger.log("Created new 'Withdrawals' sheet successfully");
    } else {
      Logger.log("Found existing 'Withdrawals' sheet");
    }
    
    // Ensure headers exist (this will set headers if they don't exist)
    Logger.log("Ensuring headers exist...");
    ensureWithdrawalHeaders(withdrawalsSheet);
    Logger.log("Headers ensured");
    
    // Verify sheet exists and is accessible
    var sheetName = withdrawalsSheet.getName();
    Logger.log("Sheet name verified: " + sheetName);
    
    // Clear existing data (except header)
    var lastRow = withdrawalsSheet.getLastRow();
    Logger.log("Last row before clearing: " + lastRow);
    if (lastRow > 1) {
      withdrawalsSheet.deleteRows(2, lastRow - 1);
      Logger.log("Cleared existing data rows");
    }
    
    // Write withdrawal data
    if (withdrawals && withdrawals.length > 0) {
      Logger.log("Writing " + withdrawals.length + " withdrawal records...");
      var data = [];
      for (var i = 0; i < withdrawals.length; i++) {
        var w = withdrawals[i];
        data.push([
          w.id,
          w.cashier_id,
          w.cashier_name,
          w.amount,
          w.reason,
          w.receipt_number || "",
          w.created_at || "",
          w.notes || ""
        ]);
      }
      
      if (data.length > 0) {
        var headers = ["ID", "Cashier ID", "Cashier Name", "Amount", "Reason", "Receipt Number", "Date", "Notes"];
        var dataRange = withdrawalsSheet.getRange(2, 1, data.length, headers.length);
        dataRange.setValues(data);
        
        // Format the amount column
        var amountRange = withdrawalsSheet.getRange(2, 4, data.length, 1);
        amountRange.setNumberFormat("$#,##0.00");
        
        // Format date column
        var dateRange = withdrawalsSheet.getRange(2, 7, data.length, 1);
        dateRange.setNumberFormat("yyyy-mm-dd hh:mm:ss");
      }
    }
    
    // Add summary row at the bottom
    var totalAmount = 0;
    if (withdrawals && withdrawals.length > 0) {
      totalAmount = withdrawals.reduce(function(sum, w) { return sum + (parseFloat(w.amount) || 0); }, 0);
    }
    
    var summaryRow = withdrawalsSheet.getLastRow() + 1;
    var headers = ["ID", "Cashier ID", "Cashier Name", "Amount", "Reason", "Receipt Number", "Date", "Notes"];
    var summaryRange = withdrawalsSheet.getRange(summaryRow, 1, 1, headers.length);
    summaryRange.setValues([["TOTAL WITHDRAWALS", (count || 0).toString(), "", totalAmount, "", "", "", ""]]);
    summaryRange.setFontWeight("bold");
    summaryRange.setBackground("#ef4444");
    summaryRange.setFontColor("#ffffff");
    var summaryAmountCell = withdrawalsSheet.getRange(summaryRow, 4);
    summaryAmountCell.setNumberFormat("$#,##0.00");
    
    // Verify the sheet is visible and accessible
    var allSheets = ss.getSheets();
    var sheetNames = allSheets.map(function(s) { return s.getName(); });
    Logger.log("All sheets in spreadsheet: " + sheetNames.join(", "));
    Logger.log("Withdrawals sheet exists in list: " + (sheetNames.indexOf("Withdrawals") >= 0));
    
    Logger.log("=== syncAllWithdrawals completed successfully ===");
    Logger.log("Total amount: " + totalAmount);
    Logger.log("Sheet 'Withdrawals' should now be visible in your spreadsheet");
    
    return {
      success: true,
      message: "Withdrawals synced successfully",
      count: count || 0,
      total_amount: totalAmount
    };
  } catch (error) {
    Logger.log("=== ERROR in syncAllWithdrawals ===");
    Logger.log("Error message: " + error.toString());
    Logger.log("Error stack: " + (error.stack || "No stack trace"));
    return {
      success: false,
      error: error.toString()
    };
  }
}

/**
 * Ensure withdrawal headers are present
 */
function ensureWithdrawalHeaders(sheet) {
  try {
    var headers = ["ID", "Cashier ID", "Cashier Name", "Amount", "Reason", "Receipt Number", "Date", "Notes"];
    
    // Check if sheet is empty or headers don't match
    var lastRow = sheet.getLastRow();
    var needsHeaders = false;
    
    if (lastRow === 0) {
      // Sheet is completely empty
      needsHeaders = true;
      Logger.log("Sheet is empty, will set headers");
    } else {
      // Check if first row has correct headers
      var headerRange = sheet.getRange(1, 1, 1, headers.length);
      var existingHeaders = headerRange.getValues()[0];
      if (!existingHeaders[0] || existingHeaders[0].toString().trim() !== headers[0]) {
        needsHeaders = true;
        Logger.log("Headers don't match, will set headers");
      }
    }
    
    if (needsHeaders) {
      var headerRange = sheet.getRange(1, 1, 1, headers.length);
      headerRange.setValues([headers]);
      headerRange.setFontWeight("bold");
      headerRange.setBackground("#ef4444");
      headerRange.setFontColor("#ffffff");
      
      // Freeze header row
      sheet.setFrozenRows(1);
      
      // Set column widths
      sheet.setColumnWidth(1, 80);  // ID
      sheet.setColumnWidth(2, 100);  // Cashier ID
      sheet.setColumnWidth(3, 150);  // Cashier Name
      sheet.setColumnWidth(4, 120);  // Amount
      sheet.setColumnWidth(5, 200);  // Reason
      sheet.setColumnWidth(6, 150);  // Receipt Number
      sheet.setColumnWidth(7, 180);  // Date
      sheet.setColumnWidth(8, 250);  // Notes
      
      Logger.log("Set withdrawal headers on sheet");
    } else {
      Logger.log("Headers already exist and are correct");
    }
  } catch (error) {
    Logger.log("Error ensuring withdrawal headers: " + error.toString());
    throw error;
  }
}

/**
 * Set API key for security (optional)
 * Run this function once from the script editor to set an API key
 */
function setApiKey() {
  var ui = SpreadsheetApp.getUi();
  var response = ui.prompt(
    'Set API Key',
    'Enter an API key to secure your web app (or leave blank to disable):',
    ui.ButtonSet.OK_CANCEL
  );
  
  if (response.getSelectedButton() == ui.Button.OK) {
    var apiKey = response.getResponseText();
    PropertiesService.getScriptProperties().setProperty('API_KEY', apiKey);
    ui.alert(apiKey ? 'API key set successfully!' : 'API key disabled');
  }
}

