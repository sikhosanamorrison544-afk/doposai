/**
 * POS Inventory Backup - Google Apps Script
 * 
 * This script enhances your inventory backup spreadsheet with:
 * - Auto-formatting of headers and data
 * - Data validation
 * - Color coding for active/inactive products
 * - Protected headers
 * - Helpful functions
 * 
 * To use:
 * 1. Open your Google Spreadsheet
 * 2. Go to Extensions > Apps Script
 * 3. Paste this entire script
 * 4. Save (Ctrl+S or Cmd+S)
 * 5. Run the onOpen() function once to set up formatting
 */

/**
 * Runs when the spreadsheet is opened
 * Note: This requires authorization on first run
 */
function onOpen(e) {
  try {
    var ui = SpreadsheetApp.getUi();
    ui.createMenu('📊 POS Inventory')
      .addItem('Format Sheet', 'formatInventorySheet')
      .addItem('Protect Headers', 'protectHeaders')
      .addItem('Validate Data', 'validateInventoryData')
      .addItem('Clear Formatting', 'clearFormatting')
      .addSeparator()
      .addItem('Get Summary', 'getInventorySummary')
      .addItem('Export as CSV', 'exportAsCSV')
      .addItem('Create Backup Copy', 'createBackupCopy')
      .addToUi();
  } catch (error) {
    // If authorization is needed, menu won't appear until authorized
    Logger.log('Error creating menu: ' + error);
  }
}

/**
 * Manual trigger to create menu (run this from script editor if menu doesn't appear)
 */
function createMenu() {
  onOpen();
}

/**
 * Format the inventory sheet with proper styling
 */
function formatInventorySheet() {
  var sheet = SpreadsheetApp.getActiveSheet();
  var lastRow = sheet.getLastRow();
  var lastCol = sheet.getLastColumn();
  
  if (lastRow < 1) {
    SpreadsheetApp.getUi().alert('No data found. Please sync from POS system first.');
    return;
  }
  
  // Format header row
  var headerRange = sheet.getRange(1, 1, 1, lastCol);
  headerRange.setFontWeight('bold');
  headerRange.setBackground('#4285f4');
  headerRange.setFontColor('#ffffff');
  headerRange.setHorizontalAlignment('center');
  headerRange.setVerticalAlignment('middle');
  headerRange.setWrap(true);
  
  // Freeze header row
  sheet.setFrozenRows(1);
  
  // Format data rows
  if (lastRow > 1) {
    var dataRange = sheet.getRange(2, 1, lastRow - 1, lastCol);
    
    // Format ID column (column A)
    var idRange = sheet.getRange(2, 1, lastRow - 1, 1);
    idRange.setNumberFormat('0');
    idRange.setHorizontalAlignment('center');
    
    // Format Name column (column B)
    var nameRange = sheet.getRange(2, 2, lastRow - 1, 1);
    nameRange.setHorizontalAlignment('left');
    
    // Format Barcode column (column C)
    var barcodeRange = sheet.getRange(2, 3, lastRow - 1, 1);
    barcodeRange.setHorizontalAlignment('left');
    
    // Format Stock Qty column (column E)
    var stockRange = sheet.getRange(2, 5, lastRow - 1, 1);
    stockRange.setNumberFormat('#,##0.00');
    stockRange.setHorizontalAlignment('right');
    
    // Format Cost Price column (column F)
    var costRange = sheet.getRange(2, 6, lastRow - 1, 1);
    costRange.setNumberFormat('$#,##0.00');
    costRange.setHorizontalAlignment('right');
    
    // Format Selling Price column (column G)
    var priceRange = sheet.getRange(2, 7, lastRow - 1, 1);
    priceRange.setNumberFormat('$#,##0.00');
    priceRange.setHorizontalAlignment('right');
    
    // Color code active/inactive products
    var statusRange = sheet.getRange(2, 8, lastRow - 1, 1);
    var statusValues = statusRange.getValues();
    
    for (var i = 0; i < statusValues.length; i++) {
      var rowNum = i + 2;
      var isActive = statusValues[i][0].toString().toLowerCase();
      
      if (isActive === 'yes' || isActive === 'true' || isActive === '1') {
        sheet.getRange(rowNum, 1, 1, lastCol).setBackground('#e8f5e9'); // Light green
      } else {
        sheet.getRange(rowNum, 1, 1, lastCol).setBackground('#ffebee'); // Light red
      }
    }
    
    // Add borders to all data
    dataRange.setBorder(true, true, true, true, true, true);
    
    // Set row heights
    headerRange.setRowHeight(30);
    sheet.setRowHeights(2, lastRow - 1, 22);
  }
  
  // Auto-resize columns
  sheet.autoResizeColumns(1, lastCol);
  
  // Set minimum column widths
  sheet.setColumnWidth(1, 60);  // ID
  sheet.setColumnWidth(2, 200); // Name
  sheet.setColumnWidth(3, 120); // Barcode
  sheet.setColumnWidth(4, 100); // Category
  sheet.setColumnWidth(5, 100); // Stock Qty
  sheet.setColumnWidth(6, 100); // Cost Price
  sheet.setColumnWidth(7, 100); // Selling Price
  sheet.setColumnWidth(8, 80);  // Is Active
  sheet.setColumnWidth(9, 180); // Last Updated
  
    SpreadsheetApp.getUi().alert('Sheet formatted successfully! ✅');
  } catch (error) {
    SpreadsheetApp.getUi().alert('Error formatting sheet: ' + error.toString());
    Logger.log('Format error: ' + error);
  }
}

/**
 * Protect the header row from editing
 */
function protectHeaders() {
  var sheet = SpreadsheetApp.getActiveSheet();
  var headerRange = sheet.getRange(1, 1, 1, sheet.getLastColumn());
  
  var protection = headerRange.protect().setDescription('Protect header row');
  
  // Ensure the current user is an editor before removing others. Otherwise, if the user's account
  // doesn't have permission to unprotect the range, this will throw an exception.
  var me = Session.getEffectiveUser();
  protection.addEditor(me);
  protection.removeEditors(protection.getEditors());
  if (protection.canDomainEdit()) {
    protection.setDomainEdit(false);
  }
  
  SpreadsheetApp.getUi().alert('Header row protected!');
}

/**
 * Add data validation to the sheet
 */
function validateInventoryData() {
  var sheet = SpreadsheetApp.getActiveSheet();
  var lastRow = sheet.getLastRow();
  
  if (lastRow < 2) {
    SpreadsheetApp.getUi().alert('No data to validate.');
    return;
  }
  
  // Validate Stock Qty (must be >= 0)
  if (lastRow > 1) {
    var stockRange = sheet.getRange(2, 5, lastRow - 1, 1);
    var stockRule = SpreadsheetApp.newDataValidation()
      .requireNumberGreaterThanOrEqualTo(0)
      .setAllowInvalid(false)
      .setHelpText('Stock quantity must be a number >= 0')
      .build();
    stockRange.setDataValidation(stockRule);
    
    // Validate Cost Price (must be >= 0)
    var costRange = sheet.getRange(2, 6, lastRow - 1, 1);
    var costRule = SpreadsheetApp.newDataValidation()
      .requireNumberGreaterThanOrEqualTo(0)
      .setAllowInvalid(false)
      .setHelpText('Cost price must be a number >= 0')
      .build();
    costRange.setDataValidation(costRule);
    
    // Validate Selling Price (must be >= 0)
    var priceRange = sheet.getRange(2, 7, lastRow - 1, 1);
    var priceRule = SpreadsheetApp.newDataValidation()
      .requireNumberGreaterThanOrEqualTo(0)
      .setAllowInvalid(false)
      .setHelpText('Selling price must be a number >= 0')
      .build();
    priceRange.setDataValidation(priceRule);
    
    // Validate Is Active (Yes/No)
    var statusRange = sheet.getRange(2, 8, lastRow - 1, 1);
    var statusRule = SpreadsheetApp.newDataValidation()
      .requireValueInList(['Yes', 'No'], true)
      .setAllowInvalid(false)
      .setHelpText('Must be "Yes" or "No"')
      .build();
    statusRange.setDataValidation(statusRule);
  }
  
  SpreadsheetApp.getUi().alert('Data validation rules applied!');
}

/**
 * Clear all formatting
 */
function clearFormatting() {
  var sheet = SpreadsheetApp.getActiveSheet();
  var lastRow = sheet.getLastRow();
  var lastCol = sheet.getLastColumn();
  
  if (lastRow > 0) {
    var range = sheet.getRange(1, 1, lastRow, lastCol);
    range.clearFormat();
    range.setNumberFormat('@'); // Set to text format
  }
  
  SpreadsheetApp.getUi().alert('Formatting cleared!');
}

/**
 * Export current sheet as CSV
 */
function exportAsCSV() {
  var sheet = SpreadsheetApp.getActiveSheet();
  var fileName = sheet.getName() + '_' + Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd') + '.csv';
  
  var csvFile = convertRangeToCsvFile_(sheet.getName());
  
  DriveApp.createFile(fileName, csvFile, MimeType.CSV);
  
  SpreadsheetApp.getUi().alert('CSV file created in your Google Drive: ' + fileName);
}

/**
 * Convert sheet data to CSV format
 */
function convertRangeToCsvFile_(sheetName) {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(sheetName);
  var data = sheet.getDataRange().getValues();
  var csv = '';
  
  for (var i = 0; i < data.length; i++) {
    var row = [];
    for (var j = 0; j < data[i].length; j++) {
      var cell = data[i][j];
      if (cell == null) {
        cell = '';
      } else {
        cell = cell.toString();
        // Escape quotes
        cell = cell.replace(/"/g, '""');
        // Add quotes if contains comma, quote, or newline
        if (cell.indexOf(',') > -1 || cell.indexOf('"') > -1 || cell.indexOf('\n') > -1) {
          cell = '"' + cell + '"';
        }
      }
      row.push(cell);
    }
    csv += row.join(',') + '\n';
  }
  
  return csv;
}

/**
 * Create a backup copy of the current sheet
 */
function createBackupCopy() {
  var spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = spreadsheet.getActiveSheet();
  var today = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd_HH-mm-ss');
  var backupName = sheet.getName() + '_Backup_' + today;
  
  var backupSheet = sheet.copyTo(spreadsheet);
  backupSheet.setName(backupName);
  
  // Move backup to end
  spreadsheet.setActiveSheet(backupSheet);
  var numSheets = spreadsheet.getNumSheets();
  spreadsheet.moveActiveSheet(numSheets);
  
  SpreadsheetApp.getUi().alert('Backup copy created: ' + backupName);
}

/**
 * Auto-format when new data is added (runs on edit)
 * Note: This can be slow for large datasets, so it's optional
 */
function onEdit(e) {
  // Uncomment the line below if you want auto-formatting on every edit
  // formatInventorySheet();
}

/**
 * Get summary statistics
 */
function getInventorySummary() {
  var sheet = SpreadsheetApp.getActiveSheet();
  var lastRow = sheet.getLastRow();
  
  if (lastRow < 2) {
    return 'No data found';
  }
  
  var data = sheet.getRange(2, 1, lastRow - 1, 8).getValues();
  
  var totalProducts = data.length;
  var activeProducts = 0;
  var totalStock = 0;
  var totalValue = 0;
  
  for (var i = 0; i < data.length; i++) {
    var isActive = data[i][7].toString().toLowerCase();
    if (isActive === 'yes' || isActive === 'true' || isActive === '1') {
      activeProducts++;
    }
    totalStock += parseFloat(data[i][4]) || 0;
    var cost = parseFloat(data[i][5]) || 0;
    var stock = parseFloat(data[i][4]) || 0;
    totalValue += cost * stock;
  }
  
  var summary = 'Inventory Summary:\n\n';
  summary += 'Total Products: ' + totalProducts + '\n';
  summary += 'Active Products: ' + activeProducts + '\n';
  summary += 'Inactive Products: ' + (totalProducts - activeProducts) + '\n';
  summary += 'Total Stock Units: ' + totalStock.toFixed(2) + '\n';
  summary += 'Total Inventory Value: $' + totalValue.toFixed(2);
  
  SpreadsheetApp.getUi().alert(summary);
  
  return summary;
}

