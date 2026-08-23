(function () {
  'use strict';

  function token() {
    return localStorage.getItem('pos_token');
  }

  function headers() {
    return {
      Authorization: 'Bearer ' + token(),
      'Content-Type': 'application/json',
    };
  }

  function msg(text, ok) {
    var el = document.getElementById('branches-msg');
    if (!el) return;
    el.textContent = text || '';
    el.className = ok ? 'ok' : 'err';
  }

  async function api(path, opts) {
    var r = await fetch(path, Object.assign({ headers: headers() }, opts || {}));
    var data = await r.json().catch(function () { return {}; });
    if (!r.ok) {
      var d = data.detail;
      if (Array.isArray(d)) d = d.map(function (x) { return x.msg || x; }).join('; ');
      throw new Error(d || ('HTTP ' + r.status));
    }
    return data;
  }

  async function loadBranches() {
    var rows = await api('/api/branches?manage=1&include_inactive=true');
    var body = document.getElementById('branches-body');
    body.innerHTML = '';
    rows.forEach(function (b) {
      var tr = document.createElement('tr');
      if (!b.is_active) tr.className = 'inactive';
      tr.innerHTML =
        '<td>' +
        (b.name || '') +
        (b.is_main ? ' <span class="branch-badge">MAIN</span>' : '') +
        '</td>' +
        '<td>' +
        (b.code || '') +
        '</td>' +
        '<td>' +
        (b.is_active ? 'Active' : 'Inactive') +
        '</td>' +
        '<td>' +
        (b.staff_count != null ? b.staff_count : '—') +
        '</td>' +
        '<td class="actions"></td>';
      var actions = tr.querySelector('.actions');
      var staffBtn = document.createElement('button');
      staffBtn.type = 'button';
      staffBtn.textContent = 'Staff';
      staffBtn.className = 'small';
      staffBtn.onclick = function () {
        openStaff(b);
      };
      actions.appendChild(staffBtn);
      if (!b.is_main) {
        var mainBtn = document.createElement('button');
        mainBtn.type = 'button';
        mainBtn.textContent = 'Make main';
        mainBtn.className = 'small';
        mainBtn.onclick = async function () {
          try {
            await api('/api/branches/' + b.id, {
              method: 'PATCH',
              body: JSON.stringify({ is_main: true }),
            });
            msg('Main branch updated', true);
            loadBranches();
          } catch (e) {
            msg(e.message);
          }
        };
        actions.appendChild(mainBtn);
      }
      var tog = document.createElement('button');
      tog.type = 'button';
      tog.className = 'small';
      tog.textContent = b.is_active ? 'Deactivate' : 'Activate';
      tog.onclick = async function () {
        try {
          var path = b.is_active
            ? '/api/branches/' + b.id + '/deactivate'
            : '/api/branches/' + b.id + '/activate';
          await api(path, { method: 'POST', body: '{}' });
          msg(b.is_active ? 'Branch deactivated (history preserved)' : 'Branch activated', true);
          loadBranches();
        } catch (e) {
          msg(e.message);
        }
      };
      actions.appendChild(tog);
      body.appendChild(tr);
    });
  }

  async function openStaff(branch) {
    document.getElementById('staff-panel').hidden = false;
    document.getElementById('staff-branch-name').textContent = branch.name;
    document.getElementById('staff-branch-id').value = branch.id;
    var rows = await api('/api/branches/' + branch.id + '/staff');
    var body = document.getElementById('staff-body');
    body.innerHTML = '';
    rows.forEach(function (m) {
      var tr = document.createElement('tr');
      tr.innerHTML =
        '<td>' +
        (m.username || m.user_id) +
        '</td><td>' +
        m.role +
        '</td><td>' +
        (m.is_default ? 'yes' : '') +
        '</td><td>' +
        (m.is_active ? 'yes' : 'no') +
        '</td><td></td>';
      if (m.is_active) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'small danger';
        btn.textContent = 'Remove';
        btn.onclick = async function () {
          if (!confirm('Remove access to this branch for ' + (m.username || m.user_id) + '?')) return;
          try {
            await api('/api/branches/' + branch.id + '/staff/' + m.user_id, { method: 'DELETE' });
            openStaff(branch);
            loadBranches();
          } catch (e) {
            msg(e.message);
          }
        };
        tr.lastChild.appendChild(btn);
      }
      body.appendChild(tr);
    });
  }

  document.getElementById('create-branch-form').addEventListener('submit', async function (e) {
    e.preventDefault();
    var fd = new FormData(e.target);
    try {
      await api('/api/branches', {
        method: 'POST',
        body: JSON.stringify({
          name: fd.get('name'),
          code: fd.get('code') || null,
          address: fd.get('address') || null,
          phone: fd.get('phone') || null,
          email: fd.get('email') || null,
          is_main: !!fd.get('is_main'),
        }),
      });
      e.target.reset();
      msg('Branch created (inventory starts empty)', true);
      loadBranches();
    } catch (err) {
      msg(err.message);
    }
  });

  document.getElementById('assign-staff-form').addEventListener('submit', async function (e) {
    e.preventDefault();
    var fd = new FormData(e.target);
    var branchId = fd.get('branch_id');
    try {
      await api('/api/branches/' + branchId + '/staff', {
        method: 'POST',
        body: JSON.stringify({
          user_id: Number(fd.get('user_id')),
          role: fd.get('role'),
          is_default: !!fd.get('is_default'),
        }),
      });
      msg('Staff assigned', true);
      openStaff({ id: Number(branchId), name: document.getElementById('staff-branch-name').textContent });
      loadBranches();
    } catch (err) {
      msg(err.message);
    }
  });

  if (!token()) {
    window.location.href = '/?next=/admin/branches';
  } else {
    loadBranches().catch(function (e) {
      msg(e.message || 'Failed to load branches');
    });
  }
})();
