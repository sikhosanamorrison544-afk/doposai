// Payment panel functions - defined first for inline onclick handlers
window.togglePaymentPanel = function() {
    console.log('=== togglePaymentPanel called ===');
    const panel = document.getElementById('payment-panel');
    const settingsPanel = document.getElementById('settings-panel');
    const backdrop = document.getElementById('pos-backdrop');
    
    console.log('Elements found:', {
        panel: !!panel,
        settingsPanel: !!settingsPanel,
        backdrop: !!backdrop
    });
    
    if (!panel) {
        console.error('payment-panel not found');
        return;
    }
    if (!backdrop) {
        console.error('pos-backdrop not found');
        return;
    }
    
    // Check if panel is currently visible
    const computedStyle = window.getComputedStyle(panel);
    const currentDisplay = computedStyle.display;
    const isVisible = currentDisplay !== 'none' && currentDisplay !== '';
    console.log('Current display:', currentDisplay, 'Is visible:', isVisible);
    
    // Close settings panel if open
    if (settingsPanel) {
        settingsPanel.style.setProperty('display', 'none', 'important');
    }
    
    // Toggle payment panel
    if (isVisible) {
        // Hide panel
        console.log('Hiding payment panel');
        panel.style.setProperty('display', 'none', 'important');
        backdrop.style.setProperty('display', 'none', 'important');
        console.log('Payment panel hidden');
    } else {
        // Show panel
        console.log('Showing payment panel');
        panel.style.setProperty('display', 'block', 'important');
        panel.style.setProperty('visibility', 'visible', 'important');
        panel.style.setProperty('opacity', '1', 'important');
        panel.style.setProperty('z-index', '9999', 'important');
        backdrop.style.setProperty('display', 'block', 'important');
        backdrop.style.setProperty('visibility', 'visible', 'important');
        backdrop.style.setProperty('z-index', '9998', 'important');
        
        // Verify after setting
        const afterStyle = window.getComputedStyle(panel);
        console.log('After setting - Panel display:', afterStyle.display);
        console.log('After setting - Panel visibility:', afterStyle.visibility);
        console.log('After setting - Panel z-index:', afterStyle.zIndex);
        console.log('Payment panel shown');
        
        // Add water droplets if light theme is active
        if (document.body.classList.contains('theme-light') && typeof window.addWaterDroplets === 'function') {
            setTimeout(() => window.addWaterDroplets(), 100);
        }
    }
};

window.closePaymentPanel = function() {
    const panel = document.getElementById('payment-panel');
    const backdrop = document.getElementById('pos-backdrop');
    if (panel) panel.style.setProperty('display', 'none', 'important');
    if (backdrop) backdrop.style.setProperty('display', 'none', 'important');
};

// Settings panel functions
window.toggleSettingsPanel = function() {
    console.log('toggleSettingsPanel called');
    const panel = document.getElementById('settings-panel');
    const paymentPanel = document.getElementById('payment-panel');
    const backdrop = document.getElementById('pos-backdrop');
    
    if (!panel) {
        console.error('settings-panel not found');
        return;
    }
    if (!backdrop) {
        console.error('pos-backdrop not found');
        return;
    }
    
    // Check if panel is currently visible
    const computedStyle = window.getComputedStyle(panel);
    const isVisible = computedStyle.display !== 'none' && computedStyle.display !== '';
    console.log('Toggle settings panel, isVisible:', isVisible, 'computed display:', computedStyle.display);
    
    // Close payment panel if open
    if (paymentPanel) {
        paymentPanel.style.setProperty('display', 'none', 'important');
    }
    
    // Toggle settings panel
    if (isVisible) {
        // Hide panel
        panel.style.setProperty('display', 'none', 'important');
        backdrop.style.setProperty('display', 'none', 'important');
        console.log('Settings panel hidden');
    } else {
        // Show panel
        panel.style.setProperty('display', 'block', 'important');
        panel.style.setProperty('visibility', 'visible', 'important');
        panel.style.setProperty('opacity', '1', 'important');
        backdrop.style.setProperty('display', 'block', 'important');
        backdrop.style.setProperty('visibility', 'visible', 'important');
        console.log('Settings panel shown');
        
        // Add water droplets if light theme is active
        if (document.body.classList.contains('theme-light') && typeof window.addWaterDroplets === 'function') {
            setTimeout(() => window.addWaterDroplets(), 100);
        }
    }
};

window.closeSettingsPanel = function() {
    const panel = document.getElementById('settings-panel');
    const backdrop = document.getElementById('pos-backdrop');
    if (panel) panel.style.setProperty('display', 'none', 'important');
    if (backdrop) backdrop.style.setProperty('display', 'none', 'important');
};

// Withdrawal panel functions
window.toggleWithdrawalModal = function() {
    console.log('toggleWithdrawalModal called');
    const modal = document.getElementById('withdrawal-modal');
    const backdrop = document.getElementById('pos-backdrop');
    const settingsPanel = document.getElementById('settings-panel');
    const paymentPanel = document.getElementById('payment-panel');
    
    console.log('Elements found:', {
        modal: !!modal,
        backdrop: !!backdrop,
        settingsPanel: !!settingsPanel,
        paymentPanel: !!paymentPanel
    });
    
    if (!modal) {
        console.error('withdrawal-modal element not found in DOM');
        return;
    }
    if (!backdrop) {
        console.error('pos-backdrop element not found in DOM');
        return;
    }
    
    // Close other panels
    if (settingsPanel) settingsPanel.style.setProperty('display', 'none', 'important');
    if (paymentPanel) paymentPanel.style.setProperty('display', 'none', 'important');
    
    const isVisible = modal.style.display !== 'none' && modal.style.display !== '';
    
    if (isVisible) {
        modal.style.setProperty('display', 'none', 'important');
        backdrop.style.setProperty('display', 'none', 'important');
    } else {
        modal.style.setProperty('display', 'block', 'important');
        modal.style.setProperty('visibility', 'visible', 'important');
        modal.style.setProperty('opacity', '1', 'important');
        modal.style.setProperty('z-index', '9999', 'important');
        backdrop.style.setProperty('display', 'block', 'important');
        backdrop.style.setProperty('visibility', 'visible', 'important');
        backdrop.style.setProperty('z-index', '9998', 'important');
        
        // Clear form
        document.getElementById('withdrawal-amount').value = '';
        document.getElementById('withdrawal-reason').value = '';
        document.getElementById('withdrawal-other-reason').value = '';
        document.getElementById('withdrawal-other-reason-container').style.display = 'none';
        document.getElementById('withdrawal-notes').value = '';
        document.getElementById('withdrawal-message').textContent = '';
        
        // Focus on amount input
        setTimeout(() => document.getElementById('withdrawal-amount').focus(), 100);
    }
};

window.closeWithdrawalModal = function() {
    const modal = document.getElementById('withdrawal-modal');
    const backdrop = document.getElementById('pos-backdrop');
    if (modal) modal.style.setProperty('display', 'none', 'important');
    if (backdrop) backdrop.style.setProperty('display', 'none', 'important');
};

async function processWithdrawal() {
    const msgEl = document.getElementById('withdrawal-message');
    const amountInput = document.getElementById('withdrawal-amount');
    const reasonSelect = document.getElementById('withdrawal-reason');
    const otherReasonInput = document.getElementById('withdrawal-other-reason');
    const notesInput = document.getElementById('withdrawal-notes');
    const btnProcess = document.getElementById('btn-process-withdrawal');
    
    if (!msgEl || !amountInput || !reasonSelect || !btnProcess) {
        console.error('Withdrawal form elements not found');
        return;
    }
    
    msgEl.textContent = '';
    
    const amount = parseFloat(amountInput.value);
    const reason = reasonSelect.value;
    const otherReason = otherReasonInput ? otherReasonInput.value.trim() : '';
    const notes = notesInput ? notesInput.value.trim() : '';
    
    // Validation
    if (!amount || amount <= 0) {
        msgEl.textContent = 'Please enter a valid amount';
        msgEl.style.color = 'rgba(239, 68, 68, 1)';
        amountInput.focus();
        return;
    }
    
    if (!reason) {
        msgEl.textContent = 'Please select a reason';
        msgEl.style.color = 'rgba(239, 68, 68, 1)';
        reasonSelect.focus();
        return;
    }
    
    if (reason === 'Other' && !otherReason) {
        msgEl.textContent = 'Please specify the reason';
        msgEl.style.color = 'rgba(239, 68, 68, 1)';
        if (otherReasonInput) otherReasonInput.focus();
        return;
    }
    
    // Validate salary details if Salary is selected
    if (reason === 'Salary') {
        const employeeName = document.getElementById('salary-employee-name')?.value.trim();
        const salaryPeriod = document.getElementById('salary-period')?.value.trim();
        
        if (!employeeName) {
            msgEl.textContent = 'Please enter employee name';
            msgEl.style.color = 'rgba(239, 68, 68, 1)';
            document.getElementById('salary-employee-name')?.focus();
            return;
        }
        
        if (!salaryPeriod) {
            msgEl.textContent = 'Please enter salary period';
            msgEl.style.color = 'rgba(239, 68, 68, 1)';
            document.getElementById('salary-period')?.focus();
            return;
        }
    }
    
    const finalReason = reason === 'Other' ? otherReason : reason;
    
    // Collect salary details if Salary is selected
    let salaryDetails = null;
    if (reason === 'Salary') {
        salaryDetails = {
            employee_name: document.getElementById('salary-employee-name')?.value.trim() || '',
            employee_id: document.getElementById('salary-employee-id')?.value.trim() || '',
            position: document.getElementById('salary-position')?.value.trim() || '',
            period: document.getElementById('salary-period')?.value.trim() || '',
            additional_notes: document.getElementById('salary-notes')?.value.trim() || ''
        };
    }
    
    btnProcess.disabled = true;
    msgEl.textContent = 'Processing withdrawal...';
    msgEl.style.color = 'rgba(255, 255, 255, 0.9)';

    const withdrawalPrintWin = window.posReceipt && typeof posReceipt.preparePrintWindow === 'function'
        ? posReceipt.preparePrintWindow()
        : null;
    
    try {
        const response = await api('/api/withdrawals', {
            method: 'POST',
            body: JSON.stringify({
                amount: amount,
                reason: finalReason,
                notes: notes || null,
                salary_details: salaryDetails
            })
        });
        
        msgEl.textContent = `Withdrawal successful! Receipt #: ${response.receipt_number}`;
        msgEl.style.color = 'rgba(34, 197, 94, 1)';

        if (window.posReceipt) {
            posReceipt.printWithdrawalReceipt({
                withdrawalId: response.id,
                receiptNumber: response.receipt_number,
                amount: amount,
                reason: finalReason,
                notes: notes || null,
                cashierName: currentUser?.username || currentUser?.full_name,
                createdAt: new Date(),
                store: posReceipt.getStoreSettings(),
            }, withdrawalPrintWin);
        } else if (withdrawalPrintWin && !withdrawalPrintWin.closed) {
            withdrawalPrintWin.close();
        }
        
        // Clear form
        amountInput.value = '';
        reasonSelect.value = '';
        if (otherReasonInput) {
            otherReasonInput.value = '';
            document.getElementById('withdrawal-other-reason-container').style.display = 'none';
        }
        if (notesInput) notesInput.value = '';
        
        // Clear salary fields
        const salaryContainer = document.getElementById('withdrawal-salary-details-container');
        if (salaryContainer) {
            salaryContainer.style.display = 'none';
            document.getElementById('salary-employee-name').value = '';
            document.getElementById('salary-employee-id').value = '';
            document.getElementById('salary-position').value = '';
            document.getElementById('salary-period').value = '';
            document.getElementById('salary-notes').value = '';
        }
        
        // Close modal after 2 seconds
        setTimeout(() => {
            window.closeWithdrawalModal();
        }, 2000);
        
    } catch (e) {
        console.error('Withdrawal error:', e);
        msgEl.textContent = 'Withdrawal failed: ' + (e.message || 'Unknown error');
        msgEl.style.color = 'rgba(239, 68, 68, 1)';
    } finally {
        btnProcess.disabled = false;
    }
}

// Theme management (only 3 themes: default, light, classic)
function applyTheme(themeName) {
    const allowed = ['default', 'light', 'classic'];
    const theme = allowed.includes(themeName) ? themeName : 'default';
    const themeClasses = ['theme-default', 'theme-light', 'theme-classic'];
    document.body.classList.remove(...themeClasses);
    document.documentElement.classList.remove(...themeClasses);
    if (theme !== 'default') {
        const cls = 'theme-' + theme;
        document.body.classList.add(cls);
        document.documentElement.classList.add(cls);
    }
    
    if (theme === 'light') {
        if (typeof window.playLightThemeVideo === 'function') {
            window.playLightThemeVideo();
        }
        setTimeout(() => {
            if (typeof window.addWaterDroplets === 'function') {
                window.addWaterDroplets();
            }
        }, 200);
    } else {
        if (typeof window.hideLightThemeVideo === 'function') {
            window.hideLightThemeVideo();
        }
        document.querySelectorAll('.water-droplet').forEach((droplet) => droplet.remove());
    }
    
    localStorage.setItem('pos-theme', theme);
    document.querySelectorAll('.theme-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.dataset.theme === theme) btn.classList.add('active');
    });
}

function loadTheme() {
    const saved = localStorage.getItem('pos-theme') || 'default';
    const theme = ['default', 'light', 'classic'].includes(saved) ? saved : 'default';
    applyTheme(theme);
    
    if (theme === 'light') {
        setTimeout(() => {
            if (typeof window.playLightThemeVideo === 'function') {
                window.playLightThemeVideo();
            }
            if (typeof window.addWaterDroplets === 'function') {
                window.addWaterDroplets();
            }
        }, 200);
    }
    
    if (theme === 'default' || !theme) {
        setTimeout(() => {
            const canvas = document.getElementById('bg3d-canvas');
            if (canvas && document.body && !document.body.classList.contains('theme-light') && !document.body.classList.contains('theme-classic')) {
                canvas.style.display = 'block';
            }
        }, 300);
    }
}

let token = null;
let currentUser = null;
let productsIndex = {};
let cart = [];
let productsList = [];

function showScreen(id) {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById(id).classList.add('active');
}

async function api(path, options = {}) {
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
        let body = null;
        try {
            body = text ? JSON.parse(text) : null;
        } catch (_) {}
        const err = new Error(
            body && typeof body.detail === 'string'
                ? body.detail
                : body && body.detail && body.detail.detail
                  ? body.detail.detail
                  : text || res.statusText,
        );
        err.status = res.status;
        const locked =
            body && body.code === 'plan_feature_locked'
                ? body
                : body && body.detail && typeof body.detail === 'object' && body.detail.code === 'plan_feature_locked'
                  ? body.detail
                  : null;
        err.body = locked || body;
        throw err;
    }
    if (res.status === 204) return null;
    return res.json();
}

async function parseFastApiErrorResponse(res) {
    const text = await res.text();
    try {
        const j = JSON.parse(text);
        if (typeof j.detail === 'string') return j.detail;
        if (Array.isArray(j.detail) && j.detail.length > 0) {
            const msg = j.detail[0].msg;
            if (typeof msg === 'string') return msg.replace(/^Value error,\s*/, '').trim();
        }
    } catch (_) {}
    return text ? text.slice(0, 350) : res.statusText;
}

function meetsSaaSRegisterPasswordRules(password) {
    if (!password || password.length < 8 || password.length > 128) return false;
    const hasLetter = /[A-Za-z]/.test(password);
    const hasDigit = /\d/.test(password);
    return hasLetter && hasDigit;
}

function formatTrialEndLabel(iso) {
    if (!iso) return '';
    try {
        return new Date(iso).toLocaleString();
    } catch (e) {
        return iso;
    }
}

function hideTrialSubscribeModal() {
    const modal = document.getElementById('trial-subscribe-modal');
    if (modal) modal.style.setProperty('display', 'none', 'important');
    const backdrop = document.getElementById('pos-backdrop');
    if (backdrop) backdrop.style.setProperty('display', 'none', 'important');
}

/** After login / register: remind trial tenants to subscribe (POS stays usable). */
async function maybeShowTrialSubscribeModal() {
    if (!token) return;
    let sub;
    try {
        sub = await api('/api/subscriptions/status');
    } catch (_) {
        return;
    }
    if (!sub || sub.effective_status !== 'trial') return;
    const modal = document.getElementById('trial-subscribe-modal');
    const backdrop = document.getElementById('pos-backdrop');
    if (!modal || !backdrop) return;
    const bodyEl = document.getElementById('trial-reminder-body');
    const detailEl = document.getElementById('trial-reminder-detail');
    const isAdmin = currentUser && currentUser.role === 'admin';
    if (bodyEl) {
        bodyEl.textContent = isAdmin
            ? 'Your 14-day trial includes all Pro features. Subscribe before it ends to keep access on Starter, Business, or Pro.'
            : 'Your business is on a free trial with full features. Ask your admin to subscribe before the trial ends.';
    }
    if (detailEl) {
        let line = '';
        if (typeof sub.days_remaining === 'number') {
            line = sub.days_remaining + ' days left in your trial.';
        } else if (sub.trial_end) {
            line = 'Trial ends: ' + formatTrialEndLabel(sub.trial_end) + '.';
        }
        detailEl.textContent = line;
        detailEl.style.display = line ? 'block' : 'none';
    }
    const btnBilling = document.getElementById('btn-trial-go-billing');
    if (btnBilling) btnBilling.style.display = isAdmin ? 'inline-block' : 'none';
    backdrop.style.setProperty('display', 'block', 'important');
    modal.style.setProperty('display', 'block', 'important');
}

/** After OAuth token or SaaS /auth/register — same JWT shape for API calls */
async function enterPosAfterAuth(data) {
    token = data.access_token;
    currentUser = { username: data.username, role: data.role };
    localStorage.setItem('pos_token', token);
    localStorage.setItem('pos_user', JSON.stringify(currentUser));
    if (window.PosBranding && typeof window.PosBranding.clearCache === 'function') {
        window.PosBranding.clearCache();
        window.PosBranding.refresh();
    }

    const next = new URLSearchParams(window.location.search).get('next');
    if (
        next &&
        next.startsWith('/') &&
        !next.startsWith('//') &&
        !next.includes(':')
    ) {
        try {
            const abs = new URL(next, window.location.origin);
            if (abs.origin === window.location.origin) {
                window.location.replace(next);
                return;
            }
        } catch (_) {}
    }

    document.getElementById('user-info').textContent = `${currentUser.username} (${currentUser.role})`;
    const adminBtn = document.getElementById('btn-admin');
    const billingBtn = document.getElementById('btn-billing');
    if (currentUser.role === 'admin') {
        adminBtn.style.display = 'inline-block';
        if (billingBtn) billingBtn.style.display = 'inline-block';
    } else {
        adminBtn.style.display = 'none';
        if (billingBtn) billingBtn.style.display = 'none';
    }

    const btnPendingCollection = document.getElementById('btn-pending-collection');
    if (btnPendingCollection) {
        if (currentUser.role === 'admin' || currentUser.role === 'supervisor') {
            btnPendingCollection.style.display = 'inline-block';
        } else {
            btnPendingCollection.style.display = 'none';
        }
    }

    const btnWithdraw = document.getElementById('btn-withdraw');
    if (btnWithdraw) {
        if (currentUser.role === 'supervisor' || currentUser.role === 'admin') {
            btnWithdraw.style.display = 'flex';
        } else {
            btnWithdraw.style.display = 'none';
        }
    }

    await loadProducts();
    if (window.posReceipt) {
        posReceipt.loadStoreSettings(api).catch(() => {});
    }
    if (window.posPlanFeatures) {
        try {
            await posPlanFeatures.loadFromApi(api);
            posPlanFeatures.applyNavGates();
        } catch (_) {
            posPlanFeatures.loadFromStorage();
            posPlanFeatures.applyNavGates();
        }
    }
    showScreen('pos-screen');
    void maybeShowTrialSubscribeModal();

    const btnTogglePayment = document.getElementById('btn-toggle-payment');
    if (btnTogglePayment) {
        btnTogglePayment.onclick = function (e) {
            e.preventDefault();
            e.stopPropagation();
            console.log('Payment icon clicked (after login)');
            window.togglePaymentPanel();
            return false;
        };
    }

    if (btnWithdraw && (currentUser.role === 'supervisor' || currentUser.role === 'admin')) {
        btnWithdraw.onclick = function (e) {
            e.preventDefault();
            e.stopPropagation();
            console.log('Withdraw button clicked');
            window.toggleWithdrawalModal();
            return false;
        };
    }

    const btnCloseWithdrawal = document.getElementById('btn-close-withdrawal');
    if (btnCloseWithdrawal) {
        btnCloseWithdrawal.onclick = function (e) {
            e.preventDefault();
            e.stopPropagation();
            window.closeWithdrawalModal();
            return false;
        };
    }

    const withdrawalReason = document.getElementById('withdrawal-reason');
    const withdrawalOtherReason = document.getElementById('withdrawal-other-reason-container');
    const withdrawalSalaryDetails = document.getElementById('withdrawal-salary-details-container');
    if (withdrawalReason) {
        withdrawalReason.addEventListener('change', function () {
            const reason = this.value;

            if (withdrawalOtherReason) {
                if (reason === 'Other') {
                    withdrawalOtherReason.style.display = 'block';
                    document.getElementById('withdrawal-other-reason').required = true;
                } else {
                    withdrawalOtherReason.style.display = 'none';
                    document.getElementById('withdrawal-other-reason').required = false;
                    document.getElementById('withdrawal-other-reason').value = '';
                }
            }

            if (withdrawalSalaryDetails) {
                if (reason === 'Salary') {
                    withdrawalSalaryDetails.style.display = 'block';
                    document.getElementById('salary-employee-name').required = true;
                    document.getElementById('salary-period').required = true;
                } else {
                    withdrawalSalaryDetails.style.display = 'none';
                    document.getElementById('salary-employee-name').required = false;
                    document.getElementById('salary-period').required = false;
                    document.getElementById('salary-employee-name').value = '';
                    document.getElementById('salary-employee-id').value = '';
                    document.getElementById('salary-position').value = '';
                    document.getElementById('salary-period').value = '';
                    document.getElementById('salary-notes').value = '';
                }
            }
        });
    }

    const btnProcessWithdrawal = document.getElementById('btn-process-withdrawal');
    if (btnProcessWithdrawal) {
        btnProcessWithdrawal.onclick = async function (e) {
            e.preventDefault();
            e.stopPropagation();
            await processWithdrawal();
            return false;
        };
    }

    document.getElementById('barcode-input').focus();
}

async function registerBusiness() {
    const errorEl = document.getElementById('register-error');
    errorEl.textContent = '';

    const business_name = document.getElementById('reg-business-name').value.trim();
    const owner_name = document.getElementById('reg-owner-name').value.trim();
    const phone = document.getElementById('reg-phone').value.trim();
    const email = document.getElementById('reg-email').value.trim();
    const password = document.getElementById('reg-password').value;

    if (business_name.length < 2 || owner_name.length < 2 || phone.length < 6 || !email.includes('@')) {
        errorEl.textContent = 'Please fill all fields correctly.';
        return;
    }
    if (!meetsSaaSRegisterPasswordRules(password)) {
        errorEl.textContent = 'Use at least 8 characters with letters and numbers.';
        return;
    }

    try {
        const res = await fetch('/auth/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                business_name,
                owner_name,
                phone,
                email,
                password,
            }),
        });
        if (!res.ok) {
            errorEl.textContent = (await parseFastApiErrorResponse(res)) || 'Could not complete registration';
            return;
        }
        const data = await res.json();
        document.getElementById('register-form-card').style.display = 'none';
        document.getElementById('login-form-card').style.display = '';
        const titleEl = document.getElementById('login-screen-title');
        if (titleEl) titleEl.textContent = 'POS Login';
        await enterPosAfterAuth(data);
    } catch (e) {
        errorEl.textContent = 'Registration failed';
        console.error(e);
    }
}

async function login() {
    const username = document.getElementById('login-username').value.trim();
    const password = document.getElementById('login-password').value;
    const errorEl = document.getElementById('login-error');
    errorEl.textContent = '';
    try {
        let res;
        if (username.includes('@')) {
            res = await fetch('/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: username, password: password }),
            });
        } else {
            const form = new URLSearchParams();
            form.append('username', username);
            form.append('password', password);
            form.append('grant_type', 'password');
            res = await fetch('/api/auth/token', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: form.toString(),
            });
        }
        if (!res.ok) {
            errorEl.textContent = 'Invalid username or password';
            return;
        }
        const data = await res.json();
        await enterPosAfterAuth(data);
    } catch (e) {
        errorEl.textContent = 'Login failed';
        console.error(e);
    }
}

async function loadProducts() {
    try {
        productsIndex = {};
        productsList = await api('/api/products');
        console.log(`Loaded ${productsList.length} products`);
        for (const p of productsList) {
            productsIndex[p.id] = p;
            if (p.barcode) {
                const code = String(p.barcode).toUpperCase();
                productsIndex['barcode:' + code] = p;
            }
        }
        console.log(`Product index created with ${Object.keys(productsIndex).length} entries`);
    } catch (e) {
        console.error('Error loading products:', e);
        productsList = [];
        productsIndex = {};
    }
}

function addToCart(product, qty = 1) {
    const qtyInt = Math.max(1, Math.round(qty)); // Ensure integer and at least 1
    
    // Check stock but don't block - just show warnings
    // Account for reserved stock (items bought but not collected)
    const totalStock = parseFloat(product.stock_qty) || 0;
    const reservedStock = parseFloat(product.reserved_qty) || 0;
    const stockQty = totalStock - reservedStock; // Available stock = Total - Reserved
    const existing = cart.find(line => line.product.id === product.id);
    const currentQty = existing ? Math.round(existing.quantity) : 0;
    const totalQty = currentQty + qtyInt;
    
    // Show warnings but allow adding to cart
    const msgEl = document.getElementById('pos-message');
    if (stockQty <= 0) {
        if (msgEl) {
            msgEl.textContent = `⚠️ Warning: ${product.name} is out of stock. Transaction will be blocked.`;
            msgEl.style.color = '#ef4444';
            msgEl.style.fontWeight = 'bold';
        }
    } else if (totalQty > stockQty) {
        if (msgEl) {
            msgEl.textContent = `⚠️ Warning: Adding ${qtyInt} would make total ${totalQty}, but only ${stockQty} available for ${product.name}. Transaction will be blocked if quantity exceeds stock.`;
            msgEl.style.color = '#ef4444';
            msgEl.style.fontWeight = 'bold';
        }
    }
    
    // Always allow adding to cart - user can type any quantity
    if (existing) {
        existing.quantity = totalQty;
    } else {
        cart.push({
            product,
            quantity: qtyInt,
            discount: 0,
        });
    }
    renderCart();
}

function removeFromCart(index) {
    cart.splice(index, 1);
    renderCart();
}

function renderCart() {
    const tbody = document.getElementById('cart-body');
    tbody.innerHTML = '';
    let subtotal = 0;
    let discount = 0;
    cart.forEach((line, idx) => {
        const price = parseFloat(line.product.selling_price);
        const qty = line.quantity;
        const disc = line.discount || 0;
        const lineTotal = price * qty - disc;
        subtotal += price * qty;
        discount += disc;
        // Get current available stock (accounting for reserved items)
        const totalStock = parseFloat(line.product.stock_qty) || 0;
        const reservedStock = parseFloat(line.product.reserved_qty) || 0;
        const stockQty = totalStock - reservedStock; // Available = Total - Reserved
        
        const tr = document.createElement('tr');
        // Show warning if quantity exceeds stock, but don't change the value
        const qtyWarning = (qty > stockQty && stockQty > 0) ? ` <span style="color: #ef4444; font-weight: bold;">(Only ${stockQty} available!)</span>` : '';
        const outOfStockWarning = stockQty <= 0 ? ' <span style="color: #ef4444;">(Out of Stock)</span>' : '';
        tr.innerHTML = `
            <td>${line.product.name}${outOfStockWarning}${qtyWarning}</td>
            <td><input type="number" id="cart-qty-${idx}" name="cart-qty-${idx}" min="1" step="1" value="${Math.round(qty)}" data-idx="${idx}" class="qty-input" style="${qty > stockQty && stockQty > 0 ? 'border: 2px solid #ef4444; background-color: #fee2e2;' : ''}"></td>
            <td>${new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 }).format(price)}</td>
            <td><input type="number" id="cart-disc-${idx}" name="cart-disc-${idx}" min="0" step="1" value="${Math.round(disc)}" data-idx="${idx}" class="disc-input"></td>
            <td>${new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 }).format(lineTotal)}</td>
            <td><button class="small danger" data-idx="${idx}">X</button></td>
        `;
        tbody.appendChild(tr);
    });
    const formatUSD = (amount) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 }).format(amount);
    document.getElementById('subtotal').textContent = formatUSD(subtotal);
    document.getElementById('discount').textContent = formatUSD(discount);
    document.getElementById('total').textContent = formatUSD(subtotal - discount);

    tbody.querySelectorAll('.qty-input').forEach(input => {
        input.addEventListener('change', e => {
            const idx = parseInt(e.target.dataset.idx, 10);
            const line = cart[idx];
            // Account for reserved stock
            const totalStock = parseFloat(line.product.stock_qty) || 0;
            const reservedStock = parseFloat(line.product.reserved_qty) || 0;
            const stockQty = totalStock - reservedStock; // Available = Total - Reserved
            let v = Math.max(1, Math.round(parseFloat(e.target.value) || 1));
            
            // Don't change the typed quantity - just show a warning
            const msgEl = document.getElementById('pos-message');
            if (v > stockQty && stockQty > 0) {
                if (msgEl) {
                    msgEl.textContent = `⚠️ Warning: Requested ${v} of ${line.product.name}, but only ${stockQty} available. Transaction will be blocked.`;
                    msgEl.style.color = '#ef4444';
                    msgEl.style.fontWeight = 'bold';
                }
                // Highlight the input field
                e.target.style.border = '2px solid #ef4444';
                e.target.style.backgroundColor = '#fee2e2';
            } else if (stockQty <= 0) {
                if (msgEl) {
                    msgEl.textContent = `⚠️ Warning: ${line.product.name} is out of stock. Transaction will be blocked.`;
                    msgEl.style.color = '#ef4444';
                    msgEl.style.fontWeight = 'bold';
                }
                e.target.style.border = '2px solid #ef4444';
                e.target.style.backgroundColor = '#fee2e2';
            } else {
                // Clear warning if quantity is valid
                if (msgEl && msgEl.textContent.includes('Warning')) {
                    msgEl.textContent = '';
                }
                e.target.style.border = '';
                e.target.style.backgroundColor = '';
            }
            
            e.target.value = v; // Ensure display is integer
            cart[idx].quantity = v;
            renderCart(); // Re-render to update warnings
        });
    });
    tbody.querySelectorAll('.disc-input').forEach(input => {
        input.addEventListener('change', e => {
            const idx = parseInt(e.target.dataset.idx, 10);
            const v = Math.max(0, Math.round(parseFloat(e.target.value) || 0));
            e.target.value = v; // Ensure display is integer
            cart[idx].discount = v;
            renderCart();
        });
    });
    tbody.querySelectorAll('button.danger').forEach(btn => {
        btn.addEventListener('click', e => {
            const idx = parseInt(e.target.dataset.idx, 10);
            removeFromCart(idx);
        });
    });
}

async function handleBarcodeEnter() {
    const input = document.getElementById('barcode-input');
    const value = input.value.trim();
    if (!value) return;

    // Try barcode exact match
    const product = productsIndex['barcode:' + value.toUpperCase()];
    if (product) {
        addToCart(product, 1);
        input.value = '';
        clearSearchResults();
        return;
    }

    // Fallback: name search
    searchByName(value);
    input.select();
}

function clearSearchResults() {
    const box = document.getElementById('search-results');
    if (box) box.innerHTML = '';
}

function searchByName(query) {
    const box = document.getElementById('search-results');
    if (!box) return;
    const q = query.trim().toLowerCase();
    box.innerHTML = '';
    if (!q) return;

    console.log(`Searching for: "${q}" in ${productsList.length} products`);
    const matches = productsList.filter(p =>
        p.is_active !== false && p.name.toLowerCase().includes(q)
    );
    console.log(`Found ${matches.length} matches`);

    if (matches.length === 1) {
        addToCart(matches[0], 1);
        clearSearchResults();
        return;
    }

    if (matches.length > 0) {
        matches.slice(0, 20).forEach(p => {
            const stockQty = parseFloat(p.stock_qty) || 0;
            const isOutOfStock = stockQty <= 0;
            const div = document.createElement('div');
            div.style.cssText = `padding: 8px; color: #ffffff; ${isOutOfStock ? 'opacity: 0.6;' : 'cursor: pointer;'} border-bottom: 1px solid rgba(255,255,255,0.1);`;
            const priceFormatted = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 }).format(parseFloat(p.selling_price));
            div.innerHTML = `${p.name} (${p.barcode || 'no barcode'}) - ${priceFormatted}${isOutOfStock ? ' <span style="color: #ef4444;">(Out of Stock)</span>' : ` (Stock: ${stockQty})`}`;
            
            if (!isOutOfStock) {
                div.addEventListener('mouseenter', () => {
                    div.style.backgroundColor = 'rgba(59, 130, 246, 0.3)';
                });
                div.addEventListener('mouseleave', () => {
                    div.style.backgroundColor = '';
                });
                div.addEventListener('click', () => {
                    addToCart(p, 1);
                    clearSearchResults();
                    const input = document.getElementById('barcode-input');
                    if (input) {
                        input.value = '';
                        input.focus();
                    }
                });
            }
            box.appendChild(div);
        });
        box.style.display = 'block';
    } else {
        const div = document.createElement('div');
        div.textContent = `No products found matching "${query}"`;
        div.style.cssText = 'padding: 8px; color: #fbbf24;';
        box.appendChild(div);
        box.style.display = 'block';
    }
}

async function completeSale() {
    const msgEl = document.getElementById('pos-message');
    msgEl.textContent = '';
    if (cart.length === 0) {
        msgEl.textContent = 'Cart is empty';
        return;
    }

    // Open print target synchronously (before any await) so the browser allows print after sale API returns
    const printWin = window.posReceipt && typeof posReceipt.preparePrintWindow === 'function'
        ? posReceipt.preparePrintWindow()
        : null;
    
    // Validate stock availability before completing sale
    // Reload products to get latest stock quantities
    await loadProducts();
    
    // Check each item in cart against current stock
    const stockIssues = [];
    for (const line of cart) {
        // Find the updated product with current stock
        const updatedProduct = productsList.find(p => p.id === line.product.id);
        if (!updatedProduct) {
            stockIssues.push(`${line.product.name} - Product not found`);
            continue;
        }
        
        const requestedQty = Math.round(line.quantity) || 1;
        const totalStock = parseFloat(updatedProduct.stock_qty) || 0;
        const reservedStock = parseFloat(updatedProduct.reserved_qty) || 0;
        const availableStock = totalStock - reservedStock; // Available = Total - Reserved
        
        if (availableStock <= 0) {
            stockIssues.push(`${line.product.name} - Out of stock (Available: 0, Reserved: ${reservedStock}, Total: ${totalStock}, Requested: ${requestedQty})`);
        } else if (availableStock < requestedQty) {
            stockIssues.push(`${line.product.name} - Insufficient stock (Available: ${availableStock}, Reserved: ${reservedStock}, Total: ${totalStock}, Requested: ${requestedQty})`);
        }
    }
    
    // If there are stock issues, prevent sale completion and receipt printing
    if (stockIssues.length > 0) {
        if (printWin && !printWin.closed) printWin.close();
        msgEl.textContent = `⚠️ Transaction blocked: ${stockIssues.join('; ')}. Receipt will NOT be printed. Please adjust quantities.`;
        msgEl.style.color = '#ef4444';
        msgEl.style.fontWeight = 'bold';
        msgEl.style.fontSize = '16px';
        return; // Stop here - don't proceed with sale or print receipt
    }
    
    const customerName = document.getElementById('customer-name').value.trim();
    let customerId = null;

    if (customerName) {
        // Create ad-hoc customer record
        try {
            const customer = await api('/api/customers', {
                method: 'POST',
                body: JSON.stringify({name: customerName}),
            });
            customerId = customer.id;
        } catch (e) {
            console.error(e);
        }
    }

    const cash = parseFloat(document.getElementById('pay-cash').value) || 0;
    const mobile = parseFloat(document.getElementById('pay-mobile').value) || 0;
    const card = parseFloat(document.getElementById('pay-card').value) || 0;
    const credit = parseFloat(document.getElementById('pay-credit').value) || 0;

    const items = cart.map(line => ({
        product_id: line.product.id,
        quantity: Math.round(line.quantity) || 1,
        unit_price: line.product.selling_price,
        discount: line.discount || 0,
    }));

    const payments = [];
    if (cash > 0) payments.push({method: 'cash', amount: cash});
    if (mobile > 0) payments.push({method: 'mobile_money', amount: mobile});
    if (card > 0) payments.push({method: 'card', amount: card});
    if (credit > 0) payments.push({method: 'credit', amount: credit});

    // Get collection status
    const collectionStatusEl = document.getElementById('collection-status');
    const collectionStatus = collectionStatusEl ? collectionStatusEl.value : 'collected';

    const cartSnapshot = cart.map(line => {
        const qty = Math.round(line.quantity) || 1;
        const unit = Number(line.product.selling_price) || 0;
        const disc = Number(line.discount) || 0;
        return {
            name: line.product.name,
            quantity: qty,
            unit_price: unit,
            line_total: unit * qty - disc,
        };
    });
    let subtotalSnap = 0;
    let discountSnap = 0;
    for (const line of cart) {
        const qty = Math.round(line.quantity) || 1;
        subtotalSnap += (Number(line.product.selling_price) || 0) * qty;
        discountSnap += Number(line.discount) || 0;
    }

    try {
        const sale = await api('/api/sales', {
            method: 'POST',
            body: JSON.stringify({
                customer_id: customerId,
                items,
                payments,
                notes: '',
                collection_status: collectionStatus,
            }),
        });
        msgEl.textContent = `Sale #${sale.id} completed`;
        msgEl.style.color = ''; // Reset color on success
        if (window.posReceipt) {
            posReceipt.printSaleReceipt({
                saleId: sale.id,
                createdAt: sale.created_at,
                items: cartSnapshot,
                subtotal: sale.subtotal != null ? sale.subtotal : subtotalSnap,
                discountTotal: sale.discount_total != null ? sale.discount_total : discountSnap,
                total: sale.total,
                payments: payments,
                customerName: customerName || null,
                collectionStatus: collectionStatus,
                cashierName: currentUser?.username,
                cashierRole: currentUser?.role,
                store: posReceipt.getStoreSettings(),
            }, printWin);
        } else if (printWin && !printWin.closed) {
            printWin.close();
        }
        cart = [];
        renderCart();
        document.getElementById('pay-cash').value = '';
        document.getElementById('pay-mobile').value = '';
        document.getElementById('pay-card').value = '';
        document.getElementById('pay-credit').value = '';
        document.getElementById('customer-name').value = '';
        await loadProducts();
    } catch (e) {
        console.error('Sale error:', e);
        if (printWin && !printWin.closed) {
            printWin.close();
        }
        const errorMsg = e.message || 'Sale failed';
        // Check if error is about stock
        if (errorMsg.includes('stock') || errorMsg.includes('Stock') || errorMsg.includes('out of stock') || errorMsg.includes('Insufficient')) {
            msgEl.textContent = `⚠️ Transaction failed: ${errorMsg}. Receipt will NOT be printed. Please adjust quantities and try again.`;
        } else {
            msgEl.textContent = `Transaction failed: ${errorMsg}`;
        }
        msgEl.style.color = '#ef4444';
        msgEl.style.fontWeight = 'bold';
    }
}

function setupEvents() {
    // Prevent browser password saving - additional measures
    const passwordField = document.getElementById('login-password');
    const usernameField = document.getElementById('login-username');
    
    // Remove name attributes to prevent browser from recognizing login form
    if (passwordField) {
        passwordField.removeAttribute('name');
        passwordField.setAttribute('data-original-type', 'password');
    }
    if (usernameField) {
        usernameField.removeAttribute('name');
    }
    
    // Change input type to text then back to password to confuse password managers
    if (passwordField) {
        passwordField.type = 'text';
        setTimeout(() => {
            passwordField.type = 'password';
        }, 100);
    }
    
    const loginButton = document.getElementById('login-button');

    if (loginButton) {
        loginButton.addEventListener('click', login);
    }

    const registerButton = document.getElementById('register-button');
    if (registerButton) {
        registerButton.addEventListener('click', registerBusiness);
    }

    const linkShowRegister = document.getElementById('link-show-register');
    const linkShowRegisterTop = document.getElementById('link-show-register-top');
    const linkBackToLogin = document.getElementById('link-back-to-login');
    const loginFormCard = document.getElementById('login-form-card');
    const registerFormCard = document.getElementById('register-form-card');
    const loginTitleEl = document.getElementById('login-screen-title');

    function openRegisterForm(e) {
        if (e) e.preventDefault();
        if (!loginFormCard || !registerFormCard) return;
        loginFormCard.style.display = 'none';
        registerFormCard.style.display = '';
        const errLogin = document.getElementById('login-error');
        if (errLogin) errLogin.textContent = '';
        if (loginTitleEl) loginTitleEl.textContent = 'Register your business';
    }
    [linkShowRegister, linkShowRegisterTop].forEach((el) => {
        if (el) el.addEventListener('click', openRegisterForm);
    });
    if (linkBackToLogin && loginFormCard && registerFormCard) {
        linkBackToLogin.addEventListener('click', function (e) {
            e.preventDefault();
            registerFormCard.style.display = 'none';
            loginFormCard.style.display = '';
            document.getElementById('register-error').textContent = '';
            if (loginTitleEl) loginTitleEl.textContent = 'POS Login';
        });
    }
    
    // Note: Enter key handlers for username and password fields are attached
    // in the HTML head's DOMContentLoaded handler for earlier initialization
    const barcodeInput = document.getElementById('barcode-input');
    barcodeInput.addEventListener('keyup', e => {
        if (e.key === 'Enter') {
            handleBarcodeEnter();
        } else {
            searchByName(barcodeInput.value);
        }
    });
    document.getElementById('btn-complete-sale').addEventListener('click', completeSale);
    document.getElementById('btn-admin').addEventListener('click', () => {
        window.location.href = '/admin';
    });
    const btnBillingNav = document.getElementById('btn-billing');
    if (btnBillingNav) {
        btnBillingNav.addEventListener('click', () => {
            window.location.href = '/billing';
        });
    }
    document.getElementById('btn-layby').addEventListener('click', () => {
        window.location.href = '/layby';
    });
    document.getElementById('btn-logout').addEventListener('click', () => {
        token = null;
        currentUser = null;
        cart = [];
        renderCart();
        localStorage.removeItem('pos_token');
        localStorage.removeItem('pos_user');
        if (window.PosBranding && typeof window.PosBranding.clearCache === 'function') {
            window.PosBranding.clearCache();
        }
        const regCard = document.getElementById('register-form-card');
        const logCard = document.getElementById('login-form-card');
        const lt = document.getElementById('login-screen-title');
        if (regCard) regCard.style.display = 'none';
        if (logCard) logCard.style.display = '';
        if (lt) lt.textContent = 'POS Login';
        showScreen('login-screen');
    });
    
    // Settings panel toggle
    const btnToggleSettings = document.getElementById('btn-toggle-settings');
    const btnCloseSettings = document.getElementById('btn-close-settings');
    
    if (btnToggleSettings) {
        btnToggleSettings.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            console.log('Settings icon clicked');
            window.toggleSettingsPanel();
            return false;
        };
    }
    
    if (btnCloseSettings) {
        btnCloseSettings.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            window.closeSettingsPanel();
            return false;
        };
    }
    
    // Theme buttons - set up after a short delay to ensure DOM is ready
    setTimeout(() => {
        document.querySelectorAll('.theme-btn').forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                const theme = this.dataset.theme;
                console.log('Theme selected:', theme);
                applyTheme(theme);
            });
        });
    }, 100);
    
    // Payment panel toggle - using same method as settings panel
    const btnTogglePayment = document.getElementById('btn-toggle-payment');
    const btnClosePayment = document.getElementById('btn-close-payment');
    const posBackdrop = document.getElementById('pos-backdrop');
    
    if (btnTogglePayment) {
        btnTogglePayment.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            console.log('Payment icon clicked');
            window.togglePaymentPanel();
            return false;
        };
    } else {
        console.error('btn-toggle-payment not found in DOM');
    }
    
    if (btnClosePayment) {
        btnClosePayment.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            window.closePaymentPanel();
            return false;
        };
    }
    
    if (posBackdrop) {
        posBackdrop.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            window.closePaymentPanel();
            window.closeSettingsPanel();
            window.closeWithdrawalModal();
            return false;
        };
    }
    
    // Setup withdrawal button handler (in case it wasn't set up during login)
    // Only show and enable for supervisors and admins
    const btnWithdraw = document.getElementById('btn-withdraw');
    if (btnWithdraw) {
        // Check user role from localStorage
        const savedUser = localStorage.getItem('pos_user');
        if (savedUser) {
            try {
                const user = JSON.parse(savedUser);
                if (user.role === 'supervisor' || user.role === 'admin') {
                    btnWithdraw.style.display = 'flex';
                    btnWithdraw.onclick = function(e) {
                        e.preventDefault();
                        e.stopPropagation();
                        console.log('Withdraw button clicked (from setupEvents)');
                        window.toggleWithdrawalModal();
                        return false;
                    };
                } else {
                    btnWithdraw.style.display = 'none';
                }
            } catch (e) {
                console.error('Error parsing user data:', e);
                btnWithdraw.style.display = 'none';
            }
        } else {
            btnWithdraw.style.display = 'none';
        }
    }
    
    // Setup withdrawal modal close button
    const btnCloseWithdrawal = document.getElementById('btn-close-withdrawal');
    if (btnCloseWithdrawal) {
        btnCloseWithdrawal.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            window.closeWithdrawalModal();
            return false;
        };
    }
    
    // Setup withdrawal reason change handler
    const withdrawalReason = document.getElementById('withdrawal-reason');
    const withdrawalOtherReason = document.getElementById('withdrawal-other-reason-container');
    const withdrawalSalaryDetails = document.getElementById('withdrawal-salary-details-container');
    if (withdrawalReason) {
        withdrawalReason.addEventListener('change', function() {
            const reason = this.value;
            
            // Handle "Other" reason
            if (withdrawalOtherReason) {
                if (reason === 'Other') {
                    withdrawalOtherReason.style.display = 'block';
                    document.getElementById('withdrawal-other-reason').required = true;
                } else {
                    withdrawalOtherReason.style.display = 'none';
                    document.getElementById('withdrawal-other-reason').required = false;
                    document.getElementById('withdrawal-other-reason').value = '';
                }
            }
            
            // Handle "Salary" reason
            if (withdrawalSalaryDetails) {
                if (reason === 'Salary') {
                    withdrawalSalaryDetails.style.display = 'block';
                    document.getElementById('salary-employee-name').required = true;
                    document.getElementById('salary-period').required = true;
                } else {
                    withdrawalSalaryDetails.style.display = 'none';
                    document.getElementById('salary-employee-name').required = false;
                    document.getElementById('salary-period').required = false;
                    // Clear salary fields
                    document.getElementById('salary-employee-name').value = '';
                    document.getElementById('salary-employee-id').value = '';
                    document.getElementById('salary-position').value = '';
                    document.getElementById('salary-period').value = '';
                    document.getElementById('salary-notes').value = '';
                }
            }
        });
    }
    
    // Setup withdrawal form submission
    const btnProcessWithdrawal = document.getElementById('btn-process-withdrawal');
    if (btnProcessWithdrawal) {
        btnProcessWithdrawal.onclick = async function(e) {
            e.preventDefault();
            e.stopPropagation();
            await processWithdrawal();
            return false;
        };
    }
}

// Layby Payment Functions
let laybyCustomers = [];
let selectedLaybyCustomer = null;
let selectedLaybyTransaction = null;
// newLaybyCustomer variable removed - no longer using customer search for new customer form

async function searchLaybyCustomers(query) {
    const resultsDiv = document.getElementById('layby-customer-results');
    if (!resultsDiv) {
        console.error('layby-customer-results div not found');
        return;
    }
    
    // If query is empty, show all customers (up to 10)
    const showAll = !query || query.trim().length === 0;
    
    try {
        const customers = await api('/api/layby/customers');
        console.log('Loaded layby customers:', customers.length);
        
        let filtered;
        if (showAll) {
            // Show all customers when field is focused or empty
            filtered = customers.slice(0, 10);
        } else {
            const searchTerm = query.toLowerCase().trim();
            filtered = customers.filter(c => 
                c.name && c.name.toLowerCase().includes(searchTerm)
            );
        }
        
        console.log('Filtered customers:', filtered.length);
        
        if (filtered.length === 0) {
            resultsDiv.innerHTML = '<div style="padding: 8px; color: #fbbf24;">No customers found</div>';
            resultsDiv.style.display = 'block';
            return;
        }
        
        resultsDiv.innerHTML = '';
        filtered.slice(0, 10).forEach(customer => {
            const div = document.createElement('div');
            div.style.cssText = 'padding: 10px; cursor: pointer; border-bottom: 1px solid rgba(255,255,255,0.1); transition: background 0.2s;';
            div.textContent = customer.name;
            div.onmouseover = () => {
                div.style.background = 'rgba(59, 130, 246, 0.3)';
            };
            div.onmouseout = () => {
                div.style.background = '';
            };
            div.onclick = (e) => {
                e.preventDefault();
                e.stopPropagation();
                selectLaybyCustomer(customer);
            };
            resultsDiv.appendChild(div);
        });
        resultsDiv.style.display = 'block';
        resultsDiv.style.zIndex = '10000';
        resultsDiv.style.position = 'relative';
    } catch (e) {
        console.error('Error searching layby customers:', e);
        resultsDiv.innerHTML = '<div style="padding: 8px; color: #ef4444;">Error loading customers: ' + (e.message || 'Unknown error') + '</div>';
        resultsDiv.style.display = 'block';
    }
}

async function selectLaybyCustomer(customer) {
    selectedLaybyCustomer = customer;
    selectedLaybyTransaction = null; // Reset transaction selection
    document.getElementById('layby-customer-name').value = customer.name;
    document.getElementById('layby-customer-results').style.display = 'none';
    
    // Clear previous transaction info
    const selectEl = document.getElementById('layby-transaction-select');
    const selectLabel = selectEl.previousElementSibling;
    const infoDiv = document.getElementById('layby-outstanding-info');
    const msgEl = document.getElementById('layby-message');
    msgEl.textContent = '';
    
    // Load active transactions for this customer
    try {
        const transactions = await api(`/api/layby/transactions?customer_id=${customer.id}&status=active`);
        
        if (transactions.length === 0) {
            selectEl.style.display = 'none';
            if (selectLabel) selectLabel.style.display = 'none';
            infoDiv.style.display = 'none';
            selectedLaybyTransaction = null;
            msgEl.textContent = 'No active layby transactions found for this customer';
            msgEl.style.color = '#fbbf24';
            return;
        }
        
        // If only one transaction, auto-select it
        if (transactions.length === 1) {
            selectedLaybyTransaction = transactions[0];
            selectLaybyTransaction(transactions[0]);
            selectEl.style.display = 'none';
            if (selectLabel) selectLabel.style.display = 'none';
            msgEl.textContent = `✓ Transaction selected: ${transactions[0].product_name}`;
            msgEl.style.color = '#10b981';
        } else {
            // Multiple transactions - show dropdown
            selectEl.innerHTML = '<option value="">-- Select Transaction --</option>';
            transactions.forEach(txn => {
                const option = document.createElement('option');
                option.value = txn.id;
                const balanceFormatted = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 }).format(parseFloat(txn.balance));
                option.textContent = `${txn.product_name} (x${txn.quantity}) - Balance: ${balanceFormatted}`;
                option.dataset.transaction = JSON.stringify(txn);
                selectEl.appendChild(option);
            });
            selectEl.style.display = 'block';
            if (selectLabel) selectLabel.style.display = 'block';
            infoDiv.style.display = 'none';
            selectedLaybyTransaction = null;
            
            // Remove old event listeners and add new one
            const newSelectEl = selectEl.cloneNode(true);
            selectEl.parentNode.replaceChild(newSelectEl, selectEl);
            
            newSelectEl.addEventListener('change', function(e) {
                if (e.target.value) {
                    const selectedOption = e.target.options[e.target.selectedIndex];
                    const txn = JSON.parse(selectedOption.dataset.transaction);
                    selectedLaybyTransaction = txn;
                    selectLaybyTransaction(txn);
                    msgEl.textContent = `✓ Transaction selected: ${txn.product_name}`;
                    msgEl.style.color = '#10b981';
                } else {
                    selectedLaybyTransaction = null;
                    infoDiv.style.display = 'none';
                    msgEl.textContent = '';
                }
            });
        }
    } catch (e) {
        console.error('Error loading transactions:', e);
        msgEl.textContent = 'Error loading transactions: ' + e.message;
        msgEl.style.color = '#ef4444';
        selectEl.style.display = 'none';
        if (selectLabel) selectLabel.style.display = 'none';
        infoDiv.style.display = 'none';
    }
}

function selectLaybyTransaction(transaction) {
    selectedLaybyTransaction = transaction;
    const infoDiv = document.getElementById('layby-outstanding-info');
    const formatUSD = (amount) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 }).format(amount);
    document.getElementById('layby-total-amount').textContent = formatUSD(parseFloat(transaction.total_amount));
    document.getElementById('layby-paid-amount').textContent = formatUSD(parseFloat(transaction.paid_amount));
    document.getElementById('layby-outstanding-amount').textContent = formatUSD(parseFloat(transaction.balance));
    infoDiv.style.display = 'block';
    
    // Set max amount to outstanding balance
    const amountInput = document.getElementById('layby-amount-paid');
    amountInput.max = parseFloat(transaction.balance);
    amountInput.value = '';
}

async function recordLaybyPayment() {
    const msgEl = document.getElementById('layby-message');
    msgEl.textContent = '';
    
    if (!selectedLaybyCustomer) {
        msgEl.textContent = 'Please select a customer';
        msgEl.style.color = '#ef4444';
        return;
    }
    
    if (!selectedLaybyTransaction) {
        const selectEl = document.getElementById('layby-transaction-select');
        if (selectEl && selectEl.style.display !== 'none' && selectEl.value === '') {
            msgEl.textContent = 'Please select a transaction from the dropdown above';
        } else {
            msgEl.textContent = 'No transaction selected. Please select a customer with active layby transactions.';
        }
        msgEl.style.color = '#ef4444';
        
        // Highlight the transaction select if visible
        if (selectEl && selectEl.style.display !== 'none') {
            selectEl.style.border = '2px solid #ef4444';
            setTimeout(() => {
                selectEl.style.border = '';
            }, 3000);
        }
        return;
    }
    
    const amount = parseFloat(document.getElementById('layby-amount-paid').value);
    const method = document.getElementById('layby-payment-method').value;
    
    if (!amount || amount <= 0) {
        msgEl.textContent = 'Please enter a valid payment amount';
        msgEl.style.color = '#ef4444';
        return;
    }
    
    if (amount > parseFloat(selectedLaybyTransaction.balance)) {
        msgEl.textContent = 'Payment amount exceeds outstanding balance';
        msgEl.style.color = '#ef4444';
        return;
    }
    
    if (!method) {
        msgEl.textContent = 'Please select a payment method';
        msgEl.style.color = '#ef4444';
        return;
    }
    
    try {
        const payment = await api('/api/layby/payments', {
            method: 'POST',
            body: JSON.stringify({
                transaction_id: selectedLaybyTransaction.id,
                amount: amount,
                payment_method: method,
                notes: null,
            }),
        });
        
        msgEl.textContent = `✓ Payment recorded! Receipt: ${payment.receipt_number}`;
        msgEl.style.color = '#10b981';
        
        // Reload transaction to get updated balance
        const transactions = await api(`/api/layby/transactions?customer_id=${selectedLaybyCustomer.id}&status=active`);
        const updatedTxn = transactions.find(t => t.id === selectedLaybyTransaction.id);
        if (updatedTxn) {
            selectedLaybyTransaction = updatedTxn;
            selectLaybyTransaction(updatedTxn);
        }
        
        // Clear payment fields
        document.getElementById('layby-amount-paid').value = '';
        document.getElementById('layby-payment-method').value = '';
        
        // If balance is zero, clear selection
        if (parseFloat(updatedTxn.balance) <= 0) {
            selectedLaybyTransaction = null;
            document.getElementById('layby-transaction-select').style.display = 'none';
            document.getElementById('layby-transaction-select').previousElementSibling.style.display = 'none';
            document.getElementById('layby-outstanding-info').style.display = 'none';
        }
    } catch (e) {
        msgEl.textContent = 'Error: ' + (e.message || 'Failed to record payment');
        msgEl.style.color = '#ef4444';
    }
}

// Customer search functions removed - new customer form creates customers directly
// Stub function to prevent errors if cached code tries to call it
function searchNewLaybyCustomers(query) {
    // This function is no longer used - customer form creates customers directly
    return;
}

function selectNewLaybyCustomer(customer) {
    // This function is no longer used - customer form creates customers directly
    return;
}

function populateProductDropdown() {
    // This function is no longer used - product dropdown was removed
    return;
}

// Product search for layby customer form
let selectedLaybyProduct = null;

function escapeHtml(text) {
    if (text == null) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

async function searchLaybyProducts(query) {
    const resultsDiv = document.getElementById('new-layby-product-results');
    if (!resultsDiv) {
        return;
    }
    
    if (!query || query.trim().length === 0) {
        resultsDiv.style.display = 'none';
        resultsDiv.innerHTML = '';
        return;
    }
    
    const searchTerm = query.toLowerCase().trim();
    
    try {
        // Filter products from the products list
        const filtered = productsList.filter(product => 
            product.is_active && 
            (product.name.toLowerCase().includes(searchTerm) ||
             (product.barcode && product.barcode.toLowerCase().includes(searchTerm)))
        );
        
        if (filtered.length === 0) {
            resultsDiv.innerHTML = '<div style="padding: 8px; color: #fbbf24;">No products found</div>';
            resultsDiv.style.display = 'block';
            return;
        }
        
        resultsDiv.innerHTML = '';
        filtered.slice(0, 10).forEach(product => {
            // Account for reserved stock
            const totalStock = parseFloat(product.stock_qty) || 0;
            const reservedStock = parseFloat(product.reserved_qty) || 0;
            const stockQty = totalStock - reservedStock; // Available = Total - Reserved
            const isOutOfStock = stockQty <= 0;
            const div = document.createElement('div');
            div.style.cssText = `padding: 10px; color: #ffffff; ${isOutOfStock ? 'opacity: 0.6; cursor: not-allowed;' : 'cursor: pointer;'} border-bottom: 1px solid rgba(255,255,255,0.1); transition: background 0.2s;`;
            div.innerHTML = `
                <div style="font-weight: bold; color: #ffffff;">${escapeHtml(product.name)}</div>
                <div style="font-size: 0.9em; color: ${isOutOfStock ? '#ef4444' : '#ffffff'};">
                    $${parseFloat(product.selling_price).toFixed(2)} | 
                    ${isOutOfStock ? '<span style="color: #ef4444;">Out of Stock</span>' : `Stock: ${stockQty}`}
                </div>
            `;
            
            if (!isOutOfStock) {
                div.onmouseover = () => {
                    div.style.background = 'rgba(59, 130, 246, 0.3)';
                };
                div.onmouseout = () => {
                    div.style.background = '';
                };
                div.onclick = (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    selectLaybyProduct(product);
                };
            }
            resultsDiv.appendChild(div);
        });
        resultsDiv.style.display = 'block';
    } catch (e) {
        console.error('Error searching products:', e);
        resultsDiv.innerHTML = '<div style="padding: 8px; color: #ef4444;">Error loading products</div>';
        resultsDiv.style.display = 'block';
    }
}

function selectLaybyProduct(product) {
    selectedLaybyProduct = product;
    const itemInput = document.getElementById('new-layby-customer-item');
    if (itemInput) {
        itemInput.value = product.name;
    }
    const resultsDiv = document.getElementById('new-layby-product-results');
    if (resultsDiv) {
        resultsDiv.style.display = 'none';
    }
}


async function addNewLaybyCustomer() {
    const msgEl = document.getElementById('new-layby-customer-message');
    if (!msgEl) {
        console.error('Message element not found');
        return;
    }
    msgEl.textContent = '';
    
    // Get form values
    const nameInput = document.getElementById('new-layby-customer-name');
    const phoneInput = document.getElementById('new-layby-customer-phone');
    const emailInput = document.getElementById('new-layby-customer-email');
    const addressInput = document.getElementById('new-layby-customer-address');
    const itemInput = document.getElementById('new-layby-customer-item');
    const initialPaymentInput = document.getElementById('new-layby-initial-payment');
    const paymentMethodSelect = document.getElementById('new-layby-payment-method');
    
    if (!nameInput || !phoneInput || !emailInput || !addressInput || !itemInput || !initialPaymentInput || !paymentMethodSelect) {
        msgEl.textContent = 'Error: Form fields not found';
        msgEl.style.color = '#ef4444';
        return;
    }
    
    const name = nameInput.value.trim();
    const phone = phoneInput.value.trim();
    const email = emailInput.value.trim() || null;
    const address = addressInput.value.trim();
    const layby_item_name = itemInput.value.trim();
    const initialPayment = parseFloat(initialPaymentInput.value);
    const paymentMethod = paymentMethodSelect.value;
    
    // Validate all required fields
    if (!name) {
        msgEl.textContent = 'Customer name is required';
        msgEl.style.color = '#ef4444';
        nameInput.focus();
        return;
    }
    
    if (!phone) {
        msgEl.textContent = 'Phone number is required';
        msgEl.style.color = '#ef4444';
        phoneInput.focus();
        return;
    }
    
    // Validate email format only if provided
    if (email) {
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(email)) {
            msgEl.textContent = 'Please enter a valid email address';
            msgEl.style.color = '#ef4444';
            emailInput.focus();
            return;
        }
    }
    
    if (!address) {
        msgEl.textContent = 'Address is required';
        msgEl.style.color = '#ef4444';
        addressInput.focus();
        return;
    }
    
    if (!layby_item_name || !selectedLaybyProduct) {
        msgEl.textContent = 'Layby item name is required. Please search and select a product.';
        msgEl.style.color = '#ef4444';
        itemInput.focus();
        return;
    }
    
    if (!initialPayment || initialPayment <= 0) {
        msgEl.textContent = 'Initial payment amount is required and must be greater than 0';
        msgEl.style.color = '#ef4444';
        initialPaymentInput.focus();
        return;
    }
    
    if (!paymentMethod) {
        msgEl.textContent = 'Payment method is required';
        msgEl.style.color = '#ef4444';
        paymentMethodSelect.focus();
        return;
    }
    
    // Validate initial payment doesn't exceed product price
    const productPrice = parseFloat(selectedLaybyProduct.selling_price);
    if (initialPayment > productPrice) {
        msgEl.textContent = `Initial payment ($${initialPayment.toFixed(2)}) cannot exceed product price ($${productPrice.toFixed(2)})`;
        msgEl.style.color = '#ef4444';
        initialPaymentInput.focus();
        return;
    }
    
    try {
        // Step 1: Create the customer
        const customer = await api('/api/layby/customers', {
            method: 'POST',
            body: JSON.stringify({ name, phone, email, address, layby_item_name }),
        });
        
        // Step 2: Create the layby transaction
        const transaction = await api('/api/layby/transactions', {
            method: 'POST',
            body: JSON.stringify({
                customer_id: customer.id,
                product_id: selectedLaybyProduct.id,
                quantity: 1,
                notes: `Initial payment: $${initialPayment.toFixed(2)}`,
            }),
        });
        
        // Step 3: Record the initial payment (this will also print the receipt)
        const payment = await api('/api/layby/payments', {
            method: 'POST',
            body: JSON.stringify({
                transaction_id: transaction.id,
                amount: initialPayment,
                payment_method: paymentMethod,
                notes: 'Initial payment',
            }),
        });
        
        msgEl.textContent = `✓ Customer "${customer.name}" added successfully! Transaction #${transaction.id} created. Initial payment of $${initialPayment.toFixed(2)} recorded. Receipt printed.`;
        msgEl.style.color = '#10b981';
        
        // Clear form
        nameInput.value = '';
        phoneInput.value = '';
        emailInput.value = '';
        addressInput.value = '';
        itemInput.value = '';
        initialPaymentInput.value = '';
        paymentMethodSelect.value = '';
        selectedLaybyProduct = null;
        
        // Clear message after 8 seconds (longer since there's more info)
        setTimeout(() => {
            msgEl.textContent = '';
        }, 8000);
    } catch (e) {
        msgEl.textContent = 'Error: ' + (e.message || 'Failed to add customer');
        msgEl.style.color = '#ef4444';
    }
}

// Add water droplets to cards and panels in light theme
// Make it globally accessible
window.addWaterDroplets = function addWaterDroplets() {
    // Remove existing droplets
    document.querySelectorAll('.water-droplet').forEach(droplet => droplet.remove());
    
    // Only add droplets if light theme is active
    if (!document.body.classList.contains('theme-light')) {
        console.log('Water droplets: Light theme not active');
        return;
    }
    
    // Find all cards and floating panels that are visible
    const cards = document.querySelectorAll('.card, .floating-panel');
    
    if (cards.length === 0) {
        console.log('Water droplets: No cards or panels found');
        return;
    }
    
    console.log('Water droplets: Found', cards.length, 'cards/panels');
    
    cards.forEach((card, index) => {
        // Check if card is visible
        const style = window.getComputedStyle(card);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
            return; // Skip hidden cards
        }
        
        // Check if droplets already exist for this card - prevent duplicates
        const existingDroplets = card.querySelectorAll('.water-droplet');
        if (existingDroplets.length > 0) {
            return; // Skip if droplets already exist
        }
        
        // Ensure card has position relative
        const cardStyle = window.getComputedStyle(card);
        if (cardStyle.position === 'static') {
            card.style.position = 'relative';
        }
        
        // Add 2-4 droplets per card (more visible)
        const dropletCount = Math.floor(Math.random() * 3) + 2; // 2 to 4 droplets
        
        for (let i = 0; i < dropletCount; i++) {
            const droplet = document.createElement('div');
            droplet.className = 'water-droplet';
            
            // Random position at the top (avoid edges)
            const leftPercent = 10 + Math.random() * 80; // 10% to 90%
            const topOffset = 15 + Math.random() * 35; // 15px to 50px from top
            
            // Larger size for better visibility
            const size = 10 + Math.random() * 8; // 10px to 18px
            const height = size * 1.6; // Height is 1.6x width for teardrop shape
            
            droplet.style.width = size + 'px';
            droplet.style.height = height + 'px';
            droplet.style.left = leftPercent + '%';
            droplet.style.top = topOffset + 'px';
            
            // Random animation delay (0s to 2s)
            droplet.style.animationDelay = (Math.random() * 2) + 's';
            
            // Random animation duration (2.5s to 4s)
            droplet.style.animationDuration = (2.5 + Math.random() * 1.5) + 's';
            
            card.appendChild(droplet);
        }
    });
    
    const addedDroplets = document.querySelectorAll('.water-droplet').length;
    console.log('Water droplets: Added', addedDroplets, 'droplets');
}

window.addEventListener('load', () => {
    setupEvents();
    
    // Load saved theme
    loadTheme();
    
    // Add water droplets after a short delay to ensure DOM is ready
    setTimeout(addWaterDroplets, 300);
    
    // Debounce function to limit how often addWaterDroplets is called
    let dropletDebounceTimer = null;
    const debouncedAddWaterDroplets = () => {
        if (dropletDebounceTimer) {
            clearTimeout(dropletDebounceTimer);
        }
        dropletDebounceTimer = setTimeout(() => {
            // Only add droplets if light theme is active
            if (document.body.classList.contains('theme-light')) {
                addWaterDroplets();
            }
        }, 500); // Wait 500ms before executing
    };
    
    // Watch for theme changes - optimized to only fire when theme actually changes
    let lastTheme = document.body.className;
    const observer = new MutationObserver(() => {
        const currentTheme = document.body.className;
        // Only trigger if theme actually changed to/from light theme
        const wasLightTheme = lastTheme.includes('theme-light');
        const isLightTheme = currentTheme.includes('theme-light');
        if (wasLightTheme !== isLightTheme) {
            lastTheme = currentTheme;
            debouncedAddWaterDroplets();
        }
    });
    observer.observe(document.body, {
        attributes: true,
        attributeFilter: ['class']
    });
    
    // Watch for panels appearing/disappearing - optimized with debouncing
    const panelObserver = new MutationObserver(() => {
        if (document.body.classList.contains('theme-light')) {
            debouncedAddWaterDroplets();
        }
    });
    panelObserver.observe(document.body, {
        childList: true,
        subtree: false // Only watch direct children, not entire subtree
    });
    
    // Ensure panels are hidden by default on page load
    const settingsPanel = document.getElementById('settings-panel');
    const paymentPanel = document.getElementById('payment-panel');
    const posBackdrop = document.getElementById('pos-backdrop');
    
    if (settingsPanel) {
        settingsPanel.style.setProperty('display', 'none', 'important');
    }
    if (paymentPanel) {
        paymentPanel.style.setProperty('display', 'none', 'important');
    }
    if (posBackdrop) {
        posBackdrop.style.setProperty('display', 'none', 'important');
    }
    
    // Verify functions are accessible
    console.log('togglePaymentPanel available:', typeof window.togglePaymentPanel);
    console.log('closePaymentPanel available:', typeof window.closePaymentPanel);
    console.log('toggleSettingsPanel available:', typeof window.toggleSettingsPanel);
    
    // Toggle layby sections
    function toggleLaybySections() {
        const container = document.getElementById('layby-sections-container');
        const icon = document.getElementById('layby-toggle-icon');
        if (!container || !icon) return;
        
        const isVisible = container.style.display !== 'none';
        if (isVisible) {
            container.style.display = 'none';
            icon.style.transform = 'rotate(0deg)';
            icon.textContent = '▼';
        } else {
            container.style.display = 'block';
            icon.style.transform = 'rotate(180deg)';
            icon.textContent = '▲';
        }
    }
    
    // Setup layby toggle button
    function setupLaybyToggle() {
        const btnToggleLayby = document.getElementById('btn-toggle-layby');
        if (btnToggleLayby) {
            // Remove existing listener by cloning
            const newBtn = btnToggleLayby.cloneNode(true);
            btnToggleLayby.parentNode.replaceChild(newBtn, btnToggleLayby);
            newBtn.addEventListener('click', toggleLaybySections);
        }
    }
    
    setupLaybyToggle();
    
    // Setup layby payment handlers - use a function that can be called when panel opens
    function setupLaybyHandlers() {
        // Payment section customer search
        const laybyCustomerInput = document.getElementById('layby-customer-name');
        if (laybyCustomerInput) {
            // Remove existing listeners by cloning
            const newInput = laybyCustomerInput.cloneNode(true);
            laybyCustomerInput.parentNode.replaceChild(newInput, laybyCustomerInput);
            
            newInput.addEventListener('input', (e) => {
                console.log('Customer name input:', e.target.value);
                searchLaybyCustomers(e.target.value);
            });
            
            newInput.addEventListener('focus', (e) => {
                console.log('Customer name field focused');
                // Show all customers when field is focused and empty
                if (!e.target.value || e.target.value.trim() === '') {
                    searchLaybyCustomers('');
                }
            });
            
            newInput.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') {
                    const resultsDiv = document.getElementById('layby-customer-results');
                    if (resultsDiv) resultsDiv.style.display = 'none';
                }
            });
        }
        
        // Product search for new layby customer form
        const laybyItemInput = document.getElementById('new-layby-customer-item');
        if (laybyItemInput) {
            const newItemInput = laybyItemInput.cloneNode(true);
            laybyItemInput.parentNode.replaceChild(newItemInput, laybyItemInput);
            
            newItemInput.addEventListener('input', (e) => {
                searchLaybyProducts(e.target.value);
            });
            
            newItemInput.addEventListener('focus', (e) => {
                if (e.target.value && e.target.value.trim() !== '') {
                    searchLaybyProducts(e.target.value);
                }
            });
            
            newItemInput.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') {
                    const resultsDiv = document.getElementById('new-layby-product-results');
                    if (resultsDiv) resultsDiv.style.display = 'none';
                }
            });
        }
        
        // Add new layby customer button
        const btnAddNewLaybyCustomer = document.getElementById('btn-add-new-layby-customer');
        if (btnAddNewLaybyCustomer) {
            const newBtn = btnAddNewLaybyCustomer.cloneNode(true);
            btnAddNewLaybyCustomer.parentNode.replaceChild(newBtn, btnAddNewLaybyCustomer);
            newBtn.addEventListener('click', addNewLaybyCustomer);
        }
        
        const btnRecordLayby = document.getElementById('btn-record-layby-payment');
        if (btnRecordLayby) {
            // Remove existing listener
            const newBtn = btnRecordLayby.cloneNode(true);
            btnRecordLayby.parentNode.replaceChild(newBtn, btnRecordLayby);
            newBtn.addEventListener('click', recordLaybyPayment);
        }
    }
    
    // Setup immediately
    setupLaybyHandlers();
    
    // Also setup when payment panel is opened (in case elements weren't ready)
    const originalTogglePaymentPanel = window.togglePaymentPanel;
    window.togglePaymentPanel = function() {
        originalTogglePaymentPanel();
        // Small delay to ensure panel is visible
        setTimeout(() => {
            setupLaybyHandlers();
            setupLaybyToggle();
        }, 100);
    };
    
    // Close results when clicking outside
    document.addEventListener('click', (e) => {
        const laybyCustomerInput = document.getElementById('layby-customer-name');
        const resultsDiv = document.getElementById('layby-customer-results');
        if (resultsDiv && laybyCustomerInput && 
            !laybyCustomerInput.contains(e.target) && 
            !resultsDiv.contains(e.target)) {
            resultsDiv.style.display = 'none';
        }
        
        // Close product results when clicking outside
        const laybyItemInput = document.getElementById('new-layby-customer-item');
        const productResultsDiv = document.getElementById('new-layby-product-results');
        if (productResultsDiv && laybyItemInput && 
            !laybyItemInput.contains(e.target) && 
            !productResultsDiv.contains(e.target)) {
            productResultsDiv.style.display = 'none';
        }
    });
});

// Notification functions
let notificationCheckInterval = null;

async function loadNotifications() {
    try {
        const token = localStorage.getItem('pos_token');
        if (!token) return;
        
        const response = await fetch('/api/notifications', {
            headers: {
                'Authorization': 'Bearer ' + token
            }
        });
        
        if (!response.ok) throw new Error('Failed to load notifications');
        
        const notifications = await response.json();
        renderNotifications(notifications);
        updateNotificationBadge();
    } catch (e) {
        console.error('Error loading notifications:', e);
    }
}

async function updateNotificationBadge() {
    try {
        const token = localStorage.getItem('pos_token');
        if (!token) return;
        
        const response = await fetch('/api/notifications/unread-count', {
            headers: {
                'Authorization': 'Bearer ' + token
            }
        });
        
        if (!response.ok) return;
        
        const data = await response.json();
        const badge = document.getElementById('notification-badge');
        const icon = document.getElementById('btn-notifications');
        
        if (badge && icon) {
            if (data.count > 0) {
                badge.textContent = data.count > 99 ? '99+' : data.count;
                badge.style.display = 'flex';
                icon.classList.add('has-unread');
            } else {
                badge.style.display = 'none';
                icon.classList.remove('has-unread');
            }
        }
    } catch (e) {
        console.error('Error updating notification badge:', e);
    }
}

function renderNotifications(notifications) {
    const content = document.getElementById('notifications-content');
    if (!content) return;
    
    if (notifications.length === 0) {
        content.innerHTML = '<div style="text-align:center;padding:20px;color:rgba(255,255,255,0.5);">No notifications</div>';
        return;
    }
    
    content.innerHTML = notifications.map(notif => {
        const timeAgo = getTimeAgo(new Date(notif.created_at));
        const itemClass = notif.is_read ? 'notification-item read' : 'notification-item unread';
        const productInfo = notif.product_name ? `<span class="notification-product">${notif.product_name}</span> - ` : '';
        
        return `
            <div class="${itemClass}" data-id="${notif.id}" onclick="markNotificationRead(${notif.id})">
                <div class="notification-message">${productInfo}${notif.message}</div>
                <div class="notification-time">${timeAgo}</div>
            </div>
        `;
    }).join('');
}

function getTimeAgo(date) {
    const now = new Date();
    const diff = now - date;
    const seconds = Math.floor(diff / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);
    
    if (days > 0) return `${days} day${days > 1 ? 's' : ''} ago`;
    if (hours > 0) return `${hours} hour${hours > 1 ? 's' : ''} ago`;
    if (minutes > 0) return `${minutes} minute${minutes > 1 ? 's' : ''} ago`;
    return 'Just now';
}

async function markNotificationRead(notificationId) {
    try {
        const token = localStorage.getItem('pos_token');
        if (!token) return;
        
        const response = await fetch(`/api/notifications/${notificationId}/read`, {
            method: 'PUT',
            headers: {
                'Authorization': 'Bearer ' + token
            }
        });
        
        if (response.ok) {
            loadNotifications();
            updateNotificationBadge();
        }
    } catch (e) {
        console.error('Error marking notification as read:', e);
    }
}

async function markAllNotificationsRead() {
    try {
        const token = localStorage.getItem('pos_token');
        if (!token) return;
        
        const response = await fetch('/api/notifications/mark-all-read', {
            method: 'PUT',
            headers: {
                'Authorization': 'Bearer ' + token
            }
        });
        
        if (response.ok) {
            loadNotifications();
            updateNotificationBadge();
        }
    } catch (e) {
        console.error('Error marking all notifications as read:', e);
    }
}

function toggleNotificationsPanel() {
    const panel = document.getElementById('notifications-panel');
    const backdrop = document.getElementById('pos-backdrop');
    const settingsPanel = document.getElementById('settings-panel');
    
    if (!panel) return;
    
    if (settingsPanel) {
        settingsPanel.style.setProperty('display', 'none', 'important');
    }
    
    const isVisible = panel.style.display !== 'none';
    
    if (isVisible) {
        panel.style.setProperty('display', 'none', 'important');
        if (backdrop) backdrop.style.setProperty('display', 'none', 'important');
    } else {
        panel.style.setProperty('display', 'block', 'important');
        if (backdrop) backdrop.style.setProperty('display', 'block', 'important');
        loadNotifications();
    }
}

// Restore session from localStorage on page load
async function restoreSession() {
    const savedToken = localStorage.getItem('pos_token');
    const savedUser = localStorage.getItem('pos_user');
    
    if (!savedToken || !savedUser) {
        console.log('No saved session found - showing login screen');
        showScreen('login-screen');
        return false;
    }
    
    try {
        // Validate token by making a test API call
        const response = await fetch('/api/products', {
            headers: {
                'Authorization': 'Bearer ' + savedToken
            }
        });
        
        if (!response.ok) {
            // Token is invalid or expired
            console.warn('Token validation failed - clearing session');
            localStorage.removeItem('pos_token');
            localStorage.removeItem('pos_user');
            showScreen('login-screen');
            return false;
        }
        
        // Token is valid - restore session
        token = savedToken;
        currentUser = JSON.parse(savedUser);
        
        // Update UI
        const userInfoEl = document.getElementById('user-info');
        if (userInfoEl) {
            userInfoEl.textContent = `${currentUser.username} (${currentUser.role})`;
        }
        
        const adminBtn = document.getElementById('btn-admin');
        const billingBtn = document.getElementById('btn-billing');
        if (adminBtn) {
            if (currentUser.role === 'admin') {
                adminBtn.style.display = 'inline-block';
            } else {
                adminBtn.style.display = 'none';
            }
        }
        if (billingBtn) {
            billingBtn.style.display = currentUser.role === 'admin' ? 'inline-block' : 'none';
        }
        
        // Show pending collection button for admin and supervisor
        const btnPendingCollection = document.getElementById('btn-pending-collection');
        if (btnPendingCollection) {
            if (currentUser.role === 'admin' || currentUser.role === 'supervisor') {
                btnPendingCollection.style.display = 'inline-block';
            } else {
                btnPendingCollection.style.display = 'none';
            }
        }
        
        // Show/hide withdrawal button based on role (only supervisor and admin can withdraw)
        const btnWithdraw = document.getElementById('btn-withdraw');
        if (btnWithdraw) {
            if (currentUser.role === 'supervisor' || currentUser.role === 'admin') {
                btnWithdraw.style.display = 'flex';
            } else {
                btnWithdraw.style.display = 'none';
            }
        }
        
        // Load products and show POS screen
        await loadProducts();
        if (window.posReceipt) {
            posReceipt.loadStoreSettings(api).catch(() => {});
        }
        showScreen('pos-screen');
        
        // Setup payment button handler
        const btnTogglePayment = document.getElementById('btn-toggle-payment');
        if (btnTogglePayment) {
            btnTogglePayment.onclick = function(e) {
                e.preventDefault();
                e.stopPropagation();
                console.log('Payment icon clicked (after session restore)');
                window.togglePaymentPanel();
                return false;
            };
        }
        
        // Setup withdrawal button handler (only if visible)
        if (btnWithdraw && (currentUser.role === 'supervisor' || currentUser.role === 'admin')) {
            btnWithdraw.onclick = function(e) {
                e.preventDefault();
                e.stopPropagation();
                window.toggleWithdrawalModal();
                return false;
            };
        }
        
        console.log('Session restored successfully');
        return true;
    } catch (error) {
        console.error('Error restoring session:', error);
        localStorage.removeItem('pos_token');
        localStorage.removeItem('pos_user');
        showScreen('login-screen');
        return false;
    }
}

// Initialize notifications on page load
document.addEventListener('DOMContentLoaded', async function() {
    // Always show login screen first - don't auto-restore session
    // Users must manually log in each time
    showScreen('login-screen');
    
    // Commented out automatic session restoration - always show login first
    // const sessionRestored = await restoreSession();
    
    const btnNotifications = document.getElementById('btn-notifications');
    const btnCloseNotifications = document.getElementById('btn-close-notifications');
    const btnMarkAllRead = document.getElementById('btn-mark-all-read');
    
    if (btnNotifications) {
        btnNotifications.addEventListener('click', toggleNotificationsPanel);
    }
    
    if (btnCloseNotifications) {
        btnCloseNotifications.addEventListener('click', toggleNotificationsPanel);
    }
    
    if (btnMarkAllRead) {
        btnMarkAllRead.addEventListener('click', async () => {
            await markAllNotificationsRead();
        });
    }

    const btnCloseTrial = document.getElementById('btn-close-trial-modal');
    const btnTrialLater = document.getElementById('btn-trial-later');
    const btnTrialBilling = document.getElementById('btn-trial-go-billing');
    if (btnCloseTrial) btnCloseTrial.addEventListener('click', hideTrialSubscribeModal);
    if (btnTrialLater) btnTrialLater.addEventListener('click', hideTrialSubscribeModal);
    if (btnTrialBilling) {
        btnTrialBilling.addEventListener('click', function () {
            window.location.href = '/billing';
        });
    }
    
    // Load notifications on page load if user is logged in (has token)
    // Check for token directly since session restoration is disabled
    if (localStorage.getItem('pos_token')) {
        loadNotifications();
        updateNotificationBadge();
        
        // Poll for new notifications every 30 seconds
        notificationCheckInterval = setInterval(() => {
            updateNotificationBadge();
        }, 30000);
    }
});


