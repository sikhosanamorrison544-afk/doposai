/**
 * Section 13 — active branch cache + selector helpers.
 * Server remains authoritative; localStorage is preference only.
 */
(function (global) {
  'use strict';

  function cacheKey(tenantId, userIdOrName) {
    return 'pos_active_branch:' + String(tenantId == null ? 'null' : tenantId) + ':' + String(userIdOrName || '');
  }

  function readCachedBranch(tenantId, userIdOrName) {
    try {
      var raw = localStorage.getItem(cacheKey(tenantId, userIdOrName));
      if (!raw) return null;
      return JSON.parse(raw);
    } catch (_) {
      return null;
    }
  }

  function writeCachedBranch(tenantId, userIdOrName, payload) {
    try {
      if (!payload) {
        localStorage.removeItem(cacheKey(tenantId, userIdOrName));
        return;
      }
      localStorage.setItem(cacheKey(tenantId, userIdOrName), JSON.stringify(payload));
    } catch (_) {}
  }

  function authHeaders(token) {
    var h = { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' };
    var ab = null;
    try {
      ab = JSON.parse(localStorage.getItem('pos_branch_ctx') || 'null');
    } catch (_) {}
    if (ab && ab.branchId && ab.scope !== 'all') {
      h['X-Branch-Id'] = String(ab.branchId);
    }
    return h;
  }

  async function refreshMe(token) {
    var r = await fetch('/api/auth/me', { headers: { Authorization: 'Bearer ' + token } });
    if (!r.ok) throw new Error('auth/me failed');
    return r.json();
  }

  async function switchBranch(token, body) {
    var r = await fetch('/api/branches/switch', {
      method: 'POST',
      headers: {
        Authorization: 'Bearer ' + token,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });
    var data = await r.json().catch(function () { return {}; });
    if (!r.ok) {
      var err = new Error(data.detail || 'Branch switch failed');
      err.status = r.status;
      err.detail = data.detail;
      throw err;
    }
    if (data.access_token) {
      localStorage.setItem('pos_token', data.access_token);
    }
    return data;
  }

  function renderSelector(el, me, opts) {
    if (!el) return;
    opts = opts || {};
    var branches = me.availableBranches || [];
    var active = me.activeBranch;
    var scope = me.branchScope || 'branch';
    var perms = me.permissions || [];
    var canConsolidated =
      perms.indexOf('branch.analytics.consolidated') !== -1 ||
      me.role === 'admin' ||
      me.role === 'owner';

    if (branches.length <= 1 && !canConsolidated) {
      el.style.display = branches.length === 1 ? 'inline-flex' : 'none';
      if (branches.length === 1) {
        el.innerHTML =
          '<span class="branch-selector-label" title="Active branch">' +
          (branches[0].name || branches[0].code || 'Branch') +
          '</span>';
      }
      return;
    }

    el.style.display = 'inline-flex';
    var options = branches
      .map(function (b) {
        var sel =
          scope === 'branch' && active && Number(active.id) === Number(b.id) ? ' selected' : '';
        return (
          '<option value="' +
          b.id +
          '"' +
          sel +
          '>' +
          (b.name || b.code || 'Branch ' + b.id) +
          '</option>'
        );
      })
      .join('');
    if (canConsolidated) {
      options =
        '<option value="__all__"' +
        (scope === 'all' ? ' selected' : '') +
        '>All Branches</option>' +
        options;
    }
    el.innerHTML =
      '<label class="branch-selector-wrap"><span class="branch-selector-label">Branch</span>' +
      '<select id="pos-branch-select" class="branch-selector-select" aria-label="Active branch">' +
      options +
      '</select></label>';

    var sel = el.querySelector('#pos-branch-select');
    if (!sel) return;
    sel.onchange = async function () {
      var token = localStorage.getItem('pos_token');
      if (!token) return;
      try {
        var body =
          sel.value === '__all__'
            ? { scope: 'all' }
            : { branchId: Number(sel.value), scope: 'branch' };
        var result = await switchBranch(token, body);
        localStorage.setItem(
          'pos_branch_ctx',
          JSON.stringify({
            branchId: result.activeBranch ? result.activeBranch.id : null,
            scope: result.scope,
          })
        );
        writeCachedBranch(me.tenant_id, me.username, {
          branchId: result.activeBranch ? result.activeBranch.id : null,
          scope: result.scope,
        });
        if (typeof opts.onSwitched === 'function') {
          opts.onSwitched(result);
        } else {
          window.location.reload();
        }
      } catch (e) {
        alert(e.detail || e.message || 'Could not switch branch');
        if (typeof opts.onError === 'function') opts.onError(e);
        try {
          var fresh = await refreshMe(localStorage.getItem('pos_token'));
          renderSelector(el, fresh, opts);
        } catch (_) {}
      }
    };
  }

  global.PosBranch = {
    cacheKey: cacheKey,
    readCachedBranch: readCachedBranch,
    writeCachedBranch: writeCachedBranch,
    authHeaders: authHeaders,
    switchBranch: switchBranch,
    refreshMe: refreshMe,
    renderSelector: renderSelector,
  };
})(window);
