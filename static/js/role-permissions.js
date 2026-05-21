/**
 * POS role helpers — mirrors app/permissions.py for UI gating.
 */
(function (global) {
    'use strict';

    var ROLE_DESCRIPTIONS = {
        admin: 'Full access — inventory, settings, users, billing, enterprise, and all reports.',
        supervisor:
            'Operational lead — process withdrawals, approve refunds, mark pending collections, and manage shifts.',
        cashier: 'Point of sale only — ring up sales and view stock levels.',
    };

    function roleOf(user) {
        if (!user) return '';
        var r = (user.role || '').toLowerCase();
        return r === 'owner' ? 'admin' : r;
    }

    function isAdmin(user) {
        return roleOf(user) === 'admin';
    }

    function isSupervisor(user) {
        return roleOf(user) === 'supervisor';
    }

    function isCashier(user) {
        return roleOf(user) === 'cashier';
    }

    function isSupervisorOrAdmin(user) {
        var r = roleOf(user);
        return r === 'admin' || r === 'supervisor';
    }

    function canAccessAdmin(user) {
        return isAdmin(user);
    }

    function canProcessWithdrawals(user) {
        return isSupervisorOrAdmin(user);
    }

    function canViewWithdrawals(user) {
        return isSupervisorOrAdmin(user);
    }

    function canManagePendingCollection(user) {
        return isSupervisorOrAdmin(user);
    }

    function canViewReports(user) {
        return isSupervisorOrAdmin(user);
    }

    function canManageShifts(user) {
        return isSupervisorOrAdmin(user);
    }

    function roleDescription(role) {
        var r = (role || '').toLowerCase();
        if (r === 'owner') r = 'admin';
        return ROLE_DESCRIPTIONS[r] || '';
    }

    function applyPosRoleGates(user) {
        var adminBtn = document.getElementById('btn-admin');
        var billingBtn = document.getElementById('btn-billing');
        var btnPending = document.getElementById('btn-pending-collection');
        var btnWithdraw = document.getElementById('btn-withdraw');

        if (adminBtn) adminBtn.style.display = canAccessAdmin(user) ? 'inline-block' : 'none';
        if (billingBtn) billingBtn.style.display = canAccessAdmin(user) ? 'inline-block' : 'none';
        if (btnPending) {
            btnPending.style.display = canManagePendingCollection(user) ? 'inline-block' : 'none';
        }
        if (btnWithdraw) {
            btnWithdraw.style.display = canProcessWithdrawals(user) ? 'flex' : 'none';
        }
    }

    global.PosRoles = {
        ROLE_DESCRIPTIONS: ROLE_DESCRIPTIONS,
        roleOf: roleOf,
        isAdmin: isAdmin,
        isSupervisor: isSupervisor,
        isCashier: isCashier,
        isSupervisorOrAdmin: isSupervisorOrAdmin,
        canAccessAdmin: canAccessAdmin,
        canProcessWithdrawals: canProcessWithdrawals,
        canViewWithdrawals: canViewWithdrawals,
        canManagePendingCollection: canManagePendingCollection,
        canViewReports: canViewReports,
        canManageShifts: canManageShifts,
        roleDescription: roleDescription,
        applyPosRoleGates: applyPosRoleGates,
    };
})(typeof window !== 'undefined' ? window : globalThis);
