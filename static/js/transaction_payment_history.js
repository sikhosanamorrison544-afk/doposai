// Transaction Payment History Page
let transactionId = null;
let transactionData = null;
let paymentHistory = [];

// Get transaction ID from URL
function getTransactionIdFromUrl() {
    const path = window.location.pathname;
    const match = path.match(/\/layby\/transaction\/(\d+)\/payments/);
    if (match) {
        return parseInt(match[1], 10);
    }
    return null;
}

// API wrapper
async function api(path, options = {}) {
    const token = localStorage.getItem('pos_token');
    const headers = options.headers || {};
    headers['Content-Type'] = 'application/json';
    if (token) {
        headers['Authorization'] = 'Bearer ' + token.trim();
    }
    const res = await fetch(path, {
        ...options,
        headers,
    });
    if (!res.ok) {
        if (res.status === 401) {
            window.location.href = '/';
            return;
        }
        const text = await res.text();
        throw new Error(text || res.statusText);
    }
    if (res.status === 204) return null;
    return res.json();
}

// Load transaction and payment history
async function loadTransactionPaymentHistory() {
    try {
        const tbody = document.getElementById('payment-history-body');
        
        if (!transactionId) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: 40px; color: #ef4444; font-size: 18px;">Error: Transaction ID not found</td></tr>';
            return;
        }
        
        // Get transaction details
        const transactions = await api(`/api/layby/transactions`);
        const transaction = transactions.find(t => t.id === transactionId);
        
        if (!transaction) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: 40px; color: #ef4444; font-size: 18px;">Transaction not found</td></tr>';
            return;
        }
        
        transactionData = transaction;
        
        // Update transaction info
        document.getElementById('customer-name').textContent = transaction.customer_name;
        document.getElementById('product-name').textContent = `${transaction.product_name} x${transaction.quantity}`;
        document.getElementById('total-amount').textContent = `$${parseFloat(transaction.total_amount).toFixed(2)}`;
        document.getElementById('paid-amount').textContent = `$${parseFloat(transaction.paid_amount).toFixed(2)}`;
        document.getElementById('balance').textContent = `$${parseFloat(transaction.balance).toFixed(2)}`;
        
        // Get payments for this transaction
        paymentHistory = await api(`/api/layby/payments/${transactionId}`);
        
        // Sort payments by date (newest first)
        paymentHistory.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
        
        // Display payments
        tbody.innerHTML = '';
        if (paymentHistory.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: 2.5em; color: #ffffff; font-size: 1.125em;">No payments recorded for this transaction</td></tr>';
        } else {
            paymentHistory.forEach(payment => {
                const tr = document.createElement('tr');
                const date = new Date(payment.created_at);
                const dateStr = date.toLocaleDateString('en-GB', { day: '2-digit', month: '2-digit', year: 'numeric' });
                const timeStr = date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                tr.innerHTML = `
                    <td style="color: #ffffff; font-weight: 500; line-height: 1.6; letter-spacing: 0.025em; word-wrap: break-word; overflow-wrap: break-word;">${dateStr}, ${timeStr}</td>
                    <td style="text-align: right; color: #10b981; font-weight: 600; line-height: 1.6; letter-spacing: 0.025em; word-wrap: break-word; overflow-wrap: break-word;">$${parseFloat(payment.amount).toFixed(2)}</td>
                    <td style="color: #ffffff; line-height: 1.6; letter-spacing: 0.025em; word-wrap: break-word; overflow-wrap: break-word;">${payment.payment_method.toUpperCase()}</td>
                    <td style="color: #ffffff; line-height: 1.6; letter-spacing: 0.025em; word-wrap: break-word; overflow-wrap: break-word;">${payment.receipt_number || '-'}</td>
                    <td style="color: #ffffff; line-height: 1.6; letter-spacing: 0.025em; word-wrap: break-word; overflow-wrap: break-word;">${payment.cashier_name || '-'}</td>
                `;
                tbody.appendChild(tr);
            });
        }
    } catch (e) {
        console.error('Error loading payment history:', e);
        const tbody = document.getElementById('payment-history-body');
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: 2.5em; color: #ef4444; font-size: 1.125em;">Error loading payment history: ' + (e.message || 'Unknown error') + '</td></tr>';
    }
}

// Download Payment History as PDF
function downloadPaymentHistoryPDF() {
    if (!paymentHistory || paymentHistory.length === 0) {
        alert('No payment history to download');
        return;
    }

    if (!transactionData) {
        alert('Transaction data not available');
        return;
    }

    const { jsPDF } = window.jspdf;
    const doc = new jsPDF();
    
    // Store name
    const storeName = document.querySelector('.shop-name')?.textContent || 'Store';
    
    // Transaction info
    const transaction = transactionData;
    const customerName = transaction.customer_name;
    const productName = transaction.product_name;
    const txnId = transaction.id;
    
    // Title
    doc.setFontSize(18);
    doc.setFont(undefined, 'bold');
    doc.text('Payment History', 14, 20);
    
    // Store name
    doc.setFontSize(12);
    doc.setFont(undefined, 'normal');
    doc.text(storeName, 14, 30);
    
    // Transaction details
    doc.setFontSize(10);
    doc.text(`Transaction ID: ${txnId}`, 14, 40);
    doc.text(`Customer: ${customerName}`, 14, 46);
    doc.text(`Product: ${productName}`, 14, 52);
    doc.text(`Total Amount: $${parseFloat(transaction.total_amount).toFixed(2)}`, 14, 58);
    doc.text(`Paid Amount: $${parseFloat(transaction.paid_amount).toFixed(2)}`, 14, 64);
    doc.text(`Balance: $${parseFloat(transaction.balance).toFixed(2)}`, 14, 70);
    
    // Table header - adjusted column positions for better spacing
    let yPos = 80;
    doc.setFontSize(9);
    doc.setFont(undefined, 'bold');
    const colDate = 14;
    const colAmount = 60;
    const colMethod = 78;
    const colReceipt = 96;
    const colCashier = 145;
    const maxWidth = 190;
    
    doc.text('Date & Time', colDate, yPos);
    doc.text('Amount', colAmount, yPos);
    doc.text('Method', colMethod, yPos);
    doc.text('Receipt #', colReceipt, yPos);
    doc.text('Cashier', colCashier, yPos);
    
    // Draw line under header
    yPos += 3;
    doc.line(14, yPos, maxWidth, yPos);
    yPos += 8;
    
    // Table data
    doc.setFont(undefined, 'normal');
    doc.setFontSize(8); // Smaller font for better fitting
    paymentHistory.forEach((payment, index) => {
        if (yPos > 270) { // New page if needed
            doc.addPage();
            yPos = 20;
            // Redraw header on new page
            doc.setFontSize(9);
            doc.setFont(undefined, 'bold');
            doc.text('Date & Time', colDate, yPos);
            doc.text('Amount', colAmount, yPos);
            doc.text('Method', colMethod, yPos);
            doc.text('Receipt #', colReceipt, yPos);
            doc.text('Cashier', colCashier, yPos);
            yPos += 3;
            doc.line(14, yPos, maxWidth, yPos);
            yPos += 8;
            doc.setFont(undefined, 'normal');
            doc.setFontSize(8);
        }
        
        const date = new Date(payment.created_at);
        const dateStr = date.toLocaleDateString('en-GB', { day: '2-digit', month: '2-digit', year: 'numeric' });
        const timeStr = date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        
        // Date & Time column (width: 44mm) - wrap if needed
        const dateTimeText = `${dateStr} ${timeStr}`;
        const dateTimeLines = doc.splitTextToSize(dateTimeText, 44);
        doc.text(dateTimeLines, colDate, yPos);
        
        // Amount column (width: 16mm)
        doc.text(`$${parseFloat(payment.amount).toFixed(2)}`, colAmount, yPos);
        
        // Method column (width: 16mm) - wrap if needed
        const methodText = payment.payment_method.toUpperCase();
        const methodLines = doc.splitTextToSize(methodText, 16);
        doc.text(methodLines, colMethod, yPos);
        
        // Receipt # column (width: 47mm) - wrap text if needed for long receipt numbers
        const receiptText = payment.receipt_number || '-';
        const receiptLines = doc.splitTextToSize(receiptText, 47);
        doc.text(receiptLines, colReceipt, yPos);
        
        // Cashier column (width: 43mm) - wrap text if needed for long names
        const cashierText = payment.cashier_name || '-';
        const cashierLines = doc.splitTextToSize(cashierText, 43);
        doc.text(cashierLines, colCashier, yPos);
        
        // Calculate the maximum number of lines for this row
        const maxLines = Math.max(
            dateTimeLines.length,
            methodLines.length,
            receiptLines.length,
            cashierLines.length,
            1 // At least 1 line
        );
        
        // Move to next row based on the tallest column
        yPos += (maxLines * 5) + 2; // 5 units per line, 2 units spacing
    });
    
    // Footer
    const totalPages = doc.internal.getNumberOfPages();
    for (let i = 1; i <= totalPages; i++) {
        doc.setPage(i);
        doc.setFontSize(8);
        doc.text(`Page ${i} of ${totalPages}`, 14, 285);
        doc.text(`Generated: ${new Date().toLocaleString()}`, 100, 285);
    }
    
    // Generate filename
    const filename = `payment_history_${customerName.replace(/\s+/g, '_')}_TXN${txnId}_${new Date().toISOString().split('T')[0]}.pdf`;
    doc.save(filename);
}

// Theme management
function applyTheme(themeName) {
    const themeClasses = ['theme-default', 'theme-light', 'theme-classic'];
    document.body.classList.remove(...themeClasses);
    document.documentElement.classList.remove(...themeClasses);
    
    const theme = ['default', 'light', 'classic'].includes(themeName) ? themeName : 'default';
    const cls = 'theme-' + theme;
    document.body.classList.add(cls);
    document.documentElement.classList.add(cls);
    
    if (themeName === 'light') {
        if (typeof window.playLightThemeVideo === 'function') window.playLightThemeVideo();
    } else if (typeof window.hideLightThemeVideo === 'function') {
        window.hideLightThemeVideo();
    }
    
    // Handle 3D background for default theme
    const canvas = document.getElementById('bg3d-canvas');
    if (canvas) {
        if (themeName === 'default' || !themeName) {
            canvas.style.display = 'block';
        } else {
            canvas.style.display = 'none';
        }
    }
    
    // Save to localStorage
    localStorage.setItem('pos-theme', themeName || 'default');
}

function loadTheme() {
    const savedTheme = localStorage.getItem('pos-theme') || 'default';
    applyTheme(savedTheme);
    
    // Ensure video plays if light theme is already active
    if (savedTheme === 'light') {
        setTimeout(() => {
            if (typeof window.playLightThemeVideo === 'function') window.playLightThemeVideo();
        }, 200);
    }
    
    // For default theme, ensure 3D background initializes
    if (savedTheme === 'default' || !savedTheme) {
        if (typeof window.check3DBackgroundTheme === 'function') {
            setTimeout(() => {
                window.check3DBackgroundTheme();
            }, 300);
        }
    }
}

// Event listeners
document.addEventListener('DOMContentLoaded', async () => {
    // Load theme first - ensure body has the class
    loadTheme();
    
    // Double-check body has theme class (in case instant script didn't apply it)
    const savedTheme = localStorage.getItem('pos-theme') || 'default';
    const themeClass = savedTheme && savedTheme !== 'default' ? 'theme-' + savedTheme : '';
    if (document.body) {
        if (themeClass && !document.body.classList.contains(themeClass)) {
            document.body.classList.remove('theme-default', 'theme-light', 'theme-classic');
            document.body.classList.add(themeClass);
        } else if (!themeClass) {
            // Default theme - remove all theme classes
            document.body.classList.remove('theme-default', 'theme-light', 'theme-classic');
        }
    }
    
    // Listen for theme changes from other tabs/windows
    window.addEventListener('storage', (e) => {
        if (e.key === 'pos-theme') {
            const newTheme = e.newValue || 'default';
            applyTheme(newTheme);
        }
    });
    
    // Also check for theme changes periodically (in case storage event doesn't fire)
    setInterval(() => {
        const currentTheme = localStorage.getItem('pos-theme') || 'default';
        const bodyTheme = document.body.className.match(/theme-(\w+)/);
        const bodyThemeName = bodyTheme ? bodyTheme[1] : 'default';
        
        if (currentTheme !== bodyThemeName) {
            applyTheme(currentTheme);
        }
    }, 500);
    
    transactionId = getTransactionIdFromUrl();
    
    // Back to layby button
    document.getElementById('btn-back-layby').addEventListener('click', () => {
        window.location.href = '/layby';
    });
    
    // Logout button
    document.getElementById('btn-logout').addEventListener('click', () => {
        localStorage.removeItem('pos_token');
        localStorage.removeItem('pos_user');
        window.location.href = '/';
    });
    
    // Download PDF button
    document.getElementById('btn-download-history-pdf').addEventListener('click', downloadPaymentHistoryPDF);
    
    // Load payment history
    await loadTransactionPaymentHistory();
});

