// Customer Payment History Page
let customerId = null;
let customerData = null; // Store loaded customer data for download

// Get customer ID from URL
function getCustomerIdFromUrl() {
    const path = window.location.pathname;
    const match = path.match(/\/layby\/customer\/(\d+)/);
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
        headers['Authorization'] = 'Bearer ' + token;
    }
    const res = await fetch(path, {
        ...options,
        headers,
    });
    if (!res.ok) {
        const text = await res.text();
        throw new Error(text || res.statusText);
    }
    if (res.status === 204) return null;
    return res.json();
}

// Load customer payment history
async function loadCustomerPaymentHistory() {
    try {
        const tbody = document.getElementById('payment-history-body-full');
        
        if (!customerId) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; padding: 40px; color: #ef4444; font-size: 16px;">Error: Customer ID not found</td></tr>';
            return;
        }
        
        // Get all transactions for this customer
        const transactions = await api(`/api/layby/transactions?customer_id=${customerId}`);
        
        // Calculate totals
        let totalAmount = 0;
        let totalPaid = 0;
        const allPayments = [];
        
        for (const txn of transactions) {
            totalAmount += parseFloat(txn.total_amount);
            totalPaid += parseFloat(txn.paid_amount);
            
            // Get payments for this transaction
            try {
                const payments = await api(`/api/layby/payments/${txn.id}`);
                payments.forEach(payment => {
                    allPayments.push({
                        ...payment,
                        transaction_id: txn.id,
                        product_name: txn.product_name,
                        quantity: txn.quantity
                    });
                });
            } catch (e) {
                console.error('Error loading payments for transaction', txn.id, e);
            }
        }
        
        const outstanding = totalAmount - totalPaid;
        
        // Store data for download
        customerData = {
            customerId: customerId,
            customerName: document.getElementById('history-customer-name-full').textContent,
            transactions: transactions,
            payments: allPayments,
            totalAmount: totalAmount,
            totalPaid: totalPaid,
            outstanding: outstanding
        };
        
        // Update summary
        document.getElementById('history-total-amount-full').textContent = `$${totalAmount.toFixed(2)}`;
        document.getElementById('history-total-paid-full').textContent = `$${totalPaid.toFixed(2)}`;
        document.getElementById('history-outstanding-full').textContent = `$${outstanding.toFixed(2)}`;
        
        // Sort payments by date (newest first)
        allPayments.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
        
        // Display financial statement
        const financialTbody = document.getElementById('financial-statement-body');
        if (financialTbody) {
            financialTbody.innerHTML = '';
            if (transactions.length === 0) {
                financialTbody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 40px; color: #ffffff; font-size: 16px;">No transactions found for this customer</td></tr>';
            } else {
                transactions.forEach(txn => {
                    const tr = document.createElement('tr');
                    tr.style.borderBottom = '1px solid rgba(255,255,255,0.1)';
                    tr.style.transition = 'background-color 0.2s';
                    tr.onmouseover = () => tr.style.backgroundColor = 'rgba(255,255,255,0.05)';
                    tr.onmouseout = () => tr.style.backgroundColor = '';
                    
                    const statusColor = txn.status === 'completed' ? '#10b981' : txn.status === 'cancelled' ? '#ef4444' : '#fbbf24';
                    const balance = parseFloat(txn.balance);
                    const balanceColor = balance > 0 ? '#fbbf24' : '#10b981';
                    
                    tr.innerHTML = `
                        <td style="padding: 12px; font-weight: bold;">#${txn.id}</td>
                        <td style="padding: 12px;">${txn.product_name} (x${txn.quantity})</td>
                        <td style="padding: 12px;">${new Date(txn.created_at).toLocaleDateString()}</td>
                        <td style="padding: 12px; text-align: right; font-weight: bold; color: #3b82f6;">$${parseFloat(txn.total_amount).toFixed(2)}</td>
                        <td style="padding: 12px; text-align: right; font-weight: bold; color: #10b981;">$${parseFloat(txn.paid_amount).toFixed(2)}</td>
                        <td style="padding: 12px; text-align: right; font-weight: bold; color: ${balanceColor}; font-size: 16px;">$${balance.toFixed(2)}</td>
                        <td style="padding: 12px;"><span style="color: ${statusColor}; font-weight: bold;">${txn.status.toUpperCase()}</span></td>
                    `;
                    financialTbody.appendChild(tr);
                });
            }
        }
        
        // Display payments
        tbody.innerHTML = '';
        if (allPayments.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; padding: 40px; color: #ffffff; font-size: 16px;">No payments recorded for this customer</td></tr>';
        } else {
            allPayments.forEach((payment, index) => {
                const tr = document.createElement('tr');
                tr.style.borderBottom = '1px solid rgba(255,255,255,0.1)';
                tr.style.transition = 'background-color 0.2s';
                tr.onmouseover = () => tr.style.backgroundColor = 'rgba(255,255,255,0.05)';
                tr.onmouseout = () => tr.style.backgroundColor = '';
                tr.innerHTML = `
                    <td style="padding: 14px;">${new Date(payment.created_at).toLocaleString()}</td>
                    <td style="padding: 14px; font-weight: bold;">#${payment.transaction_id}</td>
                    <td style="padding: 14px;">${payment.product_name} (x${payment.quantity})</td>
                    <td style="padding: 14px; text-align: right; font-weight: bold; color: #10b981; font-size: 18px;">$${parseFloat(payment.amount).toFixed(2)}</td>
                    <td style="padding: 14px;">${payment.payment_method.replace('_', ' ').toUpperCase()}</td>
                    <td style="padding: 14px; font-size: 0.95em; color: #ffffff; font-family: monospace;">${payment.receipt_number || '-'}</td>
                `;
                tbody.appendChild(tr);
            });
        }
        
    } catch (e) {
        console.error('Error loading customer payment history:', e);
        const tbody = document.getElementById('payment-history-body-full');
        if (tbody) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; padding: 40px; color: #ef4444; font-size: 16px;">Error loading payment history: ' + (e.message || 'Unknown error') + '</td></tr>';
        }
    }
}

// Initialize
window.addEventListener('load', async () => {
    // Check authentication
    const token = localStorage.getItem('pos_token');
    if (!token) {
        window.location.href = '/';
        return;
    }
    
    // Get customer ID from URL
    customerId = getCustomerIdFromUrl();
    if (!customerId) {
        alert('Invalid customer ID');
        window.location.href = '/layby';
        return;
    }
    
    // Setup event listeners
    document.getElementById('btn-back-layby').addEventListener('click', () => {
        window.location.href = '/layby';
    });
    
    document.getElementById('btn-logout').addEventListener('click', () => {
        localStorage.removeItem('pos_token');
        localStorage.removeItem('pos_user');
        window.location.href = '/';
    });
    
    // Download history button
    document.getElementById('btn-download-history').addEventListener('click', downloadCustomerHistory);
    
    // Load payment history
    await loadCustomerPaymentHistory();
});

// Download customer history as CSV
function downloadCustomerHistory() {
    if (!customerData) {
        alert('Please wait for customer history to load before downloading.');
        return;
    }
    
    const customerName = customerData.customerName || `Customer_${customerData.customerId}`;
    const filename = `layby_history_${customerName.replace(/\s+/g, '_')}_${new Date().toISOString().split('T')[0]}.csv`;
    
    // Build CSV content
    let csv = [];
    
    // Customer Information Header
    csv.push('LAYBY CUSTOMER HISTORY');
    csv.push('');
    csv.push('Customer Information');
    csv.push(`Customer ID,${customerData.customerId}`);
    csv.push(`Customer Name,${customerData.customerName}`);
    csv.push(`Total Amount,$${customerData.totalAmount.toFixed(2)}`);
    csv.push(`Total Paid,$${customerData.totalPaid.toFixed(2)}`);
    csv.push(`Outstanding Balance,$${customerData.outstanding.toFixed(2)}`);
    csv.push('');
    
    // Financial Statement Section
    csv.push('Financial Statement (Transactions)');
    csv.push('Transaction ID,Product,Quantity,Date,Total Amount,Amount Paid,Balance,Status');
    customerData.transactions.forEach(txn => {
        const date = new Date(txn.created_at).toLocaleDateString();
        csv.push(`${txn.id},"${txn.product_name}",${txn.quantity},"${date}",$${parseFloat(txn.total_amount).toFixed(2)},$${parseFloat(txn.paid_amount).toFixed(2)},$${parseFloat(txn.balance).toFixed(2)},${txn.status.toUpperCase()}`);
    });
    csv.push('');
    
    // Payment History Section
    csv.push('Payment History');
    csv.push('Date & Time,Transaction ID,Product,Quantity,Amount Paid,Payment Method,Receipt Number');
    
    // Sort payments by date (oldest first for CSV)
    const sortedPayments = [...customerData.payments].sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
    sortedPayments.forEach(payment => {
        const dateTime = new Date(payment.created_at).toLocaleString();
        const method = payment.payment_method.replace('_', ' ').toUpperCase();
        csv.push(`"${dateTime}",${payment.transaction_id},"${payment.product_name}",${payment.quantity},$${parseFloat(payment.amount).toFixed(2)},${method},"${payment.receipt_number || '-'}"`);
    });
    
    // Create CSV blob and download
    const csvContent = csv.join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    
    link.setAttribute('href', url);
    link.setAttribute('download', filename);
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

