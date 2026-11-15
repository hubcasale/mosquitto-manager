import { h, clear, openModal, confirmDialog, toast, field, errorBox } from '../dom.js';
import { api } from '../api.js';
import { t } from '../i18n.js';

export function renderGroups(root) {
  let groups = [];
  let roles = [];
  let clients = [];
  let selected = null;

  const view = h('div', { class: 'view' });
  const side = h('div', { class: 'side-list' });
  const detail = h('div', { class: 'detail' });
  view.append(
    h('div', { class: 'page-head' },
      h('h1', {}, t('nav.groups')),
      h('button', { class: 'btn primary', type: 'button', onclick: openCreate }, t('groups.new'))),
    h('p', { class: 'muted' }, t('groups.intro')),
    h('div', { class: 'split' }, side, detail));
  root.append(view);

  async function load() {
    try {
      const [g, r, c] = await Promise.all([api('/groups'), api('/roles'), api('/clients')]);
      groups = g.groups; roles = r.roles; clients = c.clients;
      if (!groups.find((x) => x.groupname === selected)) selected = groups.length ? groups[0].groupname : null;
      drawSide(); drawDetail();
    } catch (err) {
      clear(detail).append(errorBox(err.message));
    }
  }

  function drawSide() {
    clear(side).append(...groups.map((g) => h('button', {
      class: `side-item${g.groupname === selected ? ' active' : ''}`, type: 'button',
      onclick: () => { selected = g.groupname; drawSide(); drawDetail(); },
    }, h('strong', {}, g.groupname), h('span', { class: 'muted small' },
      t('groups.members', { n: (g.clients || []).length })))));
    if (!groups.length) side.append(h('p', { class: 'muted' }, t('groups.empty')));
  }

  const run = (fn, msg) => async () => {
    try { await fn(); toast(msg); load(); } catch (e) { toast(e.message, 'error'); }
  };

  function chipRow(items, label, onRemove) {
    if (!items.length) return h('span', { class: 'muted' }, t('common.none'));
    return h('div', { class: 'chips' }, items.map((it) => h('span', { class: 'chip' }, label(it),
      h('button', { class: 'chip-x', type: 'button', 'aria-label': t('common.remove'),
        onclick: () => onRemove(it) }, '×'))));
  }

  function picker(options, onAdd) {
    if (!options.length) return h('p', { class: 'muted small' }, t('common.nothing.to.add'));
    const sel = h('select', {}, options.map((o) => h('option', { value: o }, o)));
    return h('div', { class: 'row' }, sel,
      h('button', { class: 'btn', type: 'button', onclick: () => onAdd(sel.value) }, t('common.add')));
  }

  function drawDetail() {
    const g = groups.find((x) => x.groupname === selected);
    if (!g) { clear(detail); return; }
    const members = (g.clients || []).map((c) => c.username);
    const myRoles = (g.roles || []).map((r) => r.rolename);
    clear(detail).append(
      h('div', { class: 'card' },
        h('div', { class: 'card-head' },
          h('div', {}, h('h2', {}, g.groupname), g.textname ? h('div', { class: 'muted' }, g.textname) : null),
          h('button', { class: 'btn danger small', type: 'button', onclick: async () => {
            const ok = await confirmDialog({ title: t('groups.delete'),
              message: t('groups.delete.confirm', { g: g.groupname }),
              confirmLabel: t('common.delete'), danger: true });
            if (ok) await run(() => api('/groups/delete', { groupname: g.groupname }), t('common.deleted'))();
          } }, t('groups.delete')))),
      h('div', { class: 'card' }, h('h3', {}, t('nav.roles')),
        chipRow(myRoles, (r) => r, (r) => run(() => api('/groups/role-remove',
          { groupname: g.groupname, rolename: r }), t('common.removed'))()),
        picker(roles.map((r) => r.rolename).filter((n) => !myRoles.includes(n)),
          (name) => run(() => api('/groups/role-add', { groupname: g.groupname, rolename: name }),
            t('common.added'))())),
      h('div', { class: 'card' }, h('h3', {}, t('groups.col.members')),
        chipRow(members, (u) => u, (u) => run(() => api('/clients/group-remove',
          { username: u, groupname: g.groupname }), t('common.removed'))()),
        picker(clients.map((c) => c.username).filter((n) => !members.includes(n)),
          (name) => run(() => api('/clients/group-add', { username: name, groupname: g.groupname }),
            t('common.added'))())));
  }

  function openCreate() {
    const m = openModal({ title: t('groups.new') });
    const name = h('input', { required: true, maxLength: 256 });
    const text = h('input', { maxLength: 512 });
    const err = h('div');
    m.set(h('form', { class: 'form', onsubmit: async (e) => {
      e.preventDefault();
      try {
        await api('/groups/create', { groupname: name.value.trim(), textname: text.value });
        selected = name.value.trim();
        m.close(); load();
      } catch (ex) { clear(err).append(errorBox(ex.message)); }
    } },
    field(t('groups.f.name'), name), field(t('roles.f.text'), text), err,
    h('div', { class: 'actions' },
      h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, t('common.cancel')),
      h('button', { class: 'btn primary', type: 'submit' }, t('common.create')))));
    name.focus();
  }

  load();
  return { dispose() {} };
}
