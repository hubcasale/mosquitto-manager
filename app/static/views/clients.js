import { h, clear, openModal, confirmDialog, toast, randomPassword, field, errorBox } from '../dom.js';
import { api } from '../api.js';
import { t } from '../i18n.js';
import { ago, fmtTime } from '../fmt.js';

// Explains a failed CONNACK in plain words.
export function loginHint(reason) {
  const r = (reason || '').toLowerCase();
  if (r.includes('not authorized') || r.includes('bad user')) return t('test.hint.auth');
  if (r.includes('cannot reach') || r.includes('timed out')) return t('test.hint.net');
  return '';
}

export function testResult(res) {
  return h('div', { class: `notice ${res.ok ? 'ok' : 'error'}`, role: 'status' },
    h('strong', {}, res.ok ? t('test.ok') : t('test.fail')),
    ` — ${res.reason} (${res.ms} ms)`,
    !res.ok && loginHint(res.reason) ? h('div', { class: 'small' }, loginHint(res.reason)) : null);
}

function passwordField(label, input) {
  const gen = h('button', { class: 'btn small', type: 'button',
    onclick: () => { input.value = randomPassword(); input.type = 'text'; } }, t('common.generate'));
  const show = h('button', { class: 'btn small', type: 'button',
    onclick: () => { input.type = input.type === 'password' ? 'text' : 'password'; } },
  t('common.show'));
  return h('div', { class: 'field' },
    h('span', { class: 'field-label' }, label),
    h('div', { class: 'row' }, input, show, gen),
    h('span', { class: 'hint' }, t('clients.pw.hint')));
}

function chips(items, labelOf, onRemove, removable = true) {
  if (!items.length) return h('span', { class: 'muted' }, t('common.none'));
  return h('div', { class: 'chips' }, items.map((it) => h('span', { class: 'chip' },
    labelOf(it),
    removable ? h('button', { class: 'chip-x', type: 'button', 'aria-label': t('common.remove'),
      onclick: () => onRemove(it) }, '×') : null)));
}

function pick(label, options, onAdd) {
  if (!options.length) return h('p', { class: 'muted small' }, t('common.nothing.to.add'));
  const sel = h('select', {}, options.map((o) => h('option', { value: o }, o)));
  return h('div', { class: 'row' }, sel,
    h('button', { class: 'btn', type: 'button', onclick: () => onAdd(sel.value) }, label));
}

export function renderClients(root, _ctx, query = {}) {
  let clients = [];
  let filter = '';
  let timer;
  const view = h('div', { class: 'view' });
  const listEl = h('div');
  const errEl = h('div');

  const search = h('input', { type: 'search', placeholder: t('clients.search'),
    'aria-label': t('clients.search'),
    oninput: (e) => { filter = e.target.value.trim().toLowerCase(); draw(); } });
  view.append(
    h('div', { class: 'page-head' },
      h('h1', {}, t('nav.clients')),
      h('div', { class: 'row' }, search,
        h('button', { class: 'btn primary', type: 'button', onclick: openCreate }, t('clients.new')))),
    errEl, listEl);
  root.append(view);

  async function load() {
    try {
      const data = await api('/clients');
      clients = data.clients;
      clear(errEl);
      draw();
    } catch (err) {
      clear(errEl).append(errorBox(err.message));
    }
  }

  function statusCell(c) {
    if (c.disabled) return h('span', { class: 'badge muted' }, t('clients.disabled'));
    if (c.online) {
      return h('span', { class: 'badge ok' }, h('i', { class: 'dot' }),
        t('clients.online', { n: c.connections.length }));
    }
    return h('span', {},
      h('span', { class: 'badge muted' }, t('clients.offline')),
      c.saved_sessions ? h('div', { class: 'muted small', title: t('clients.saved.hint') },
        t('clients.saved', { n: c.saved_sessions })) : null);
  }

  function seenCell(c) {
    if (c.online) {
      return h('span', { class: 'small' },
        c.connections.map((x) => x.address).filter(Boolean).join(', '));
    }
    return c.last_seen
      ? h('span', { class: 'muted small', title: fmtTime(c.last_seen.ts) },
        t('clients.lastseen', { v: ago(c.last_seen.ts) }))
      : h('span', { class: 'muted' }, '—');
  }

  function draw() {
    const rows = clients.filter((c) => !filter
      || [c.username, c.textname, c.textdescription].some((s) => (s || '').toLowerCase().includes(filter))
      || c.roles.some((r) => r.rolename.toLowerCase().includes(filter))
      || c.groups.some((g) => g.groupname.toLowerCase().includes(filter)));
    if (!rows.length) {
      clear(listEl).append(h('p', { class: 'muted empty' },
        clients.length ? t('clients.nomatch') : t('clients.empty')));
      return;
    }
    clear(listEl).append(h('div', { class: 'card flush scroll' }, h('table', { class: 'table clickable' },
      h('thead', {}, h('tr', {}, h('th', {}, t('clients.col.status')), h('th', {}, t('clients.col.user')),
        h('th', {}, t('clients.col.access')), h('th', {}, t('clients.col.conn')), h('th', {}))),
      h('tbody', {}, rows.map((c) => h('tr', { tabindex: 0,
        onclick: () => openClient(c.username),
        onkeydown: (e) => { if (e.key === 'Enter') openClient(c.username); } },
      h('td', {}, statusCell(c)),
      h('td', {}, h('strong', {}, c.username), c.is_manager
        ? h('span', { class: 'badge info', title: t('clients.manager.hint') }, t('clients.manager')) : null,
      c.textname ? h('div', { class: 'muted small' }, c.textname) : null),
      h('td', {}, h('div', { class: 'chips' },
        c.roles.map((r) => h('span', { class: 'chip role' }, r.rolename)),
        c.groups.map((g) => h('span', { class: 'chip group' }, g.groupname)))),
      h('td', {}, seenCell(c)),
      h('td', { class: 'right' }, h('button', { class: 'btn small', type: 'button' }, t('common.manage'))))))
    )));
  }

  // ------------------------------------------------------------- create
  async function openCreate() {
    const m = openModal({ title: t('clients.new') });
    let roles = []; let groups = [];
    try {
      [roles, groups] = (await Promise.all([api('/roles'), api('/groups')]))
        .map((r, i) => (i ? r.groups : r.roles));
    } catch (err) { m.set(errorBox(err.message)); return; }

    const username = h('input', { required: true, maxLength: 256, autocomplete: 'off' });
    const password = h('input', { type: 'password', required: true, autocomplete: 'new-password' });
    const textname = h('input', { maxLength: 512 });
    const desc = h('input', { maxLength: 512 });
    const roleBoxes = roles.map((r) => ({ name: r.rolename, box: h('input', { type: 'checkbox' }) }));
    const groupBoxes = groups.map((g) => ({ name: g.groupname, box: h('input', { type: 'checkbox' }) }));
    const err = h('div');
    const save = h('button', { class: 'btn primary', type: 'submit' }, t('common.create'));

    const checks = (items) => (items.length
      ? h('div', { class: 'checks' }, items.map((i) => h('label', { class: 'check' }, i.box, i.name)))
      : h('span', { class: 'muted small' }, t('common.none')));

    const form = h('form', { class: 'form', onsubmit: async (e) => {
      e.preventDefault();
      save.disabled = true;
      try {
        await api('/clients/create', {
          username: username.value.trim(), password: password.value,
          textname: textname.value, textdescription: desc.value,
          roles: roleBoxes.filter((r) => r.box.checked).map((r) => r.name),
          groups: groupBoxes.filter((g) => g.box.checked).map((g) => g.name),
        });
        toast(t('clients.created', { u: username.value.trim() }));
        m.close();
        load();
      } catch (ex) { clear(err).append(errorBox(ex.message)); } finally { save.disabled = false; }
    } },
    field(t('clients.f.username'), username, t('clients.f.username.hint')),
    passwordField(t('clients.f.password'), password),
    field(t('clients.f.name'), textname), field(t('clients.f.desc'), desc),
    h('div', { class: 'field' }, h('span', { class: 'field-label' }, t('nav.roles')), checks(roleBoxes)),
    h('div', { class: 'field' }, h('span', { class: 'field-label' }, t('nav.groups')), checks(groupBoxes)),
    err,
    h('div', { class: 'actions' },
      h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, t('common.cancel')), save));
    m.set(form);
    username.focus();
  }

  // ------------------------------------------------------------- manage
  async function openClient(username) {
    const m = openModal({ title: username, wide: true });
    let roleList = []; let groupList = [];

    const act = (fn, okMsg) => async () => {
      try { await fn(); if (okMsg) toast(okMsg); await paint(); } catch (ex) { toast(ex.message, 'error'); }
    };

    async function paint() {
      const [clientsRes, rolesRes, groupsRes] = await Promise.all(
        [api('/clients'), api('/roles'), api('/groups')]);
      clients = clientsRes.clients; draw();
      roleList = rolesRes.roles; groupList = groupsRes.groups;
      const c = clients.find((x) => x.username === username);
      if (!c) { m.close(); return; }
      m.set(...panel(c));
    }

    function panel(c) {
      const textname = h('input', { value: c.textname, maxLength: 512 });
      const desc = h('input', { value: c.textdescription, maxLength: 512 });
      const clientid = h('input', { value: c.clientid, maxLength: 256, disabled: c.is_manager,
        autocomplete: 'off' });
      const newpw = h('input', { type: 'password', autocomplete: 'new-password' });
      const testpw = h('input', { type: 'password', autocomplete: 'off' });
      const testOut = h('div');
      const testBtn = h('button', { class: 'btn', type: 'button' }, t('test.run'));
      testBtn.onclick = async () => {
        testBtn.disabled = true;
        try {
          clear(testOut).append(testResult(await api('/test-login',
            { username: c.username, password: testpw.value })));
        } catch (ex) { clear(testOut).append(errorBox(ex.message)); } finally { testBtn.disabled = false; }
      };

      const myRoles = new Set(c.roles.map((r) => r.rolename));
      const myGroups = new Set(c.groups.map((g) => g.groupname));
      const roleOpts = roleList.map((r) => r.rolename).filter((n) => !myRoles.has(n));
      const groupOpts = groupList.map((g) => g.groupname).filter((n) => !myGroups.has(n));

      return [
        c.is_manager ? h('div', { class: 'notice info' }, t('clients.manager.note')) : null,
        h('div', { class: 'detail-head' }, statusBadge(c),
          c.last_seen ? h('span', { class: 'muted small' },
            t('clients.lastseen', { v: ago(c.last_seen.ts) })) : null),

        h('section', {}, h('h3', {}, t('clients.sec.details')),
          h('div', { class: 'form' },
            field(t('clients.f.name'), textname), field(t('clients.f.desc'), desc),
            field(t('clients.f.clientid'), clientid, t('clients.f.clientid.hint')),
            h('div', { class: 'actions' }, h('button', { class: 'btn primary', type: 'button',
              onclick: act(() => api('/clients/update', {
                username: c.username, textname: textname.value, textdescription: desc.value,
                ...(c.is_manager ? {} : { clientid: clientid.value }),
              }), t('common.saved')) }, t('common.save'))))),

        h('section', {}, h('h3', {}, t('clients.sec.connections')),
          c.connections.length
            ? h('table', { class: 'table compact' },
              h('thead', {}, h('tr', {}, h('th', {}, t('act.address')), h('th', {}, t('clients.f.clientid')),
                h('th', {}, t('clients.proto')), h('th', {}, t('clients.since')))),
              h('tbody', {}, c.connections.map((x) => h('tr', {},
                h('td', {}, h('code', {}, x.address || '?')), h('td', {}, x.clientid || '—'),
                h('td', {}, x.protocol ? `${x.protocol} · ${x.keepalive}s` : '—'),
                h('td', {}, x.since ? ago(x.since) : '—')))))
            : h('p', { class: 'muted' }, t('clients.noconn'),
              c.saved_sessions ? ` ${t('clients.saved', { n: c.saved_sessions })}. ${t('clients.saved.hint')}` : '')),

        h('section', {}, h('h3', {}, t('nav.roles')),
          chips(c.roles, (r) => r.rolename, (r) => act(
            () => api('/clients/role-remove', { username: c.username, rolename: r.rolename }),
            t('common.removed'))()),
          pick(t('common.add'), roleOpts, (name) => act(
            () => api('/clients/role-add', { username: c.username, rolename: name }),
            t('common.added'))())),

        h('section', {}, h('h3', {}, t('nav.groups')),
          chips(c.groups, (g) => g.groupname, (g) => act(
            () => api('/clients/group-remove', { username: c.username, groupname: g.groupname }),
            t('common.removed'))()),
          pick(t('common.add'), groupOpts, (name) => act(
            () => api('/clients/group-add', { username: c.username, groupname: name }),
            t('common.added'))())),

        c.is_manager ? null : h('section', {}, h('h3', {}, t('clients.sec.password')),
          passwordField(t('clients.f.newpassword'), newpw),
          h('div', { class: 'actions' }, h('button', { class: 'btn', type: 'button', onclick: async () => {
            if (!newpw.value) return;
            await act(() => api('/clients/password', { username: c.username, password: newpw.value }),
              t('clients.pw.changed'))();
          } }, t('clients.pw.set')))),

        h('section', {}, h('h3', {}, t('clients.sec.test')),
          h('p', { class: 'muted small' }, t('clients.test.hint')),
          h('div', { class: 'row' }, testpw, testBtn), testOut),

        c.is_manager ? null : h('section', { class: 'danger-zone' },
          h('h3', {}, t('clients.sec.danger')),
          h('div', { class: 'actions left' },
            h('button', { class: 'btn', type: 'button', onclick: act(() => api('/clients/enable',
              { username: c.username, enabled: c.disabled }),
            c.disabled ? t('clients.enabled') : t('clients.disabled.done')) },
            c.disabled ? t('clients.enable') : t('clients.disable')),
            h('button', { class: 'btn danger', type: 'button', onclick: async () => {
              const ok = await confirmDialog({ title: t('clients.delete'),
                message: t('clients.delete.confirm', { u: c.username }),
                confirmLabel: t('common.delete'), danger: true });
              if (!ok) return;
              try {
                await api('/clients/delete', { username: c.username });
                toast(t('common.deleted'));
                m.close();
                load();
              } catch (ex) { toast(ex.message, 'error'); }
            } }, t('clients.delete')))),
      ];
    }

    function statusBadge(c) {
      if (c.disabled) return h('span', { class: 'badge muted' }, t('clients.disabled'));
      return c.online
        ? h('span', { class: 'badge ok' }, h('i', { class: 'dot' }), t('clients.online', { n: c.connections.length }))
        : h('span', { class: 'badge muted' }, t('clients.offline'));
    }

    try { await paint(); } catch (ex) { m.set(errorBox(ex.message)); }
  }

  load().then(() => {
    if (query.open) {
      history.replaceState(null, '', '#/clients');
      openClient(query.open);
    }
  });
  timer = setInterval(load, 5000);
  return { dispose: () => clearInterval(timer) };
}
