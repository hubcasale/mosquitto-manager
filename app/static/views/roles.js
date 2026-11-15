import { h, clear, openModal, confirmDialog, toast, field, errorBox } from '../dom.js';
import { api } from '../api.js';
import { t } from '../i18n.js';

const ACL_TYPES = ['publishClientSend', 'publishClientReceive', 'subscribePattern',
  'subscribeLiteral', 'unsubscribePattern', 'unsubscribeLiteral'];
const DEFAULT_TYPES = ['publishClientSend', 'publishClientReceive', 'subscribe', 'unsubscribe'];

const READWRITE = ['publishClientSend', 'publishClientReceive', 'subscribePattern', 'unsubscribePattern'];
const READ = ['publishClientReceive', 'subscribePattern', 'unsubscribePattern'];

// Dynamic Security stores "read and write on a topic" as several technical rules.
// Group them back by topic so the table reads like what the user meant.
export function groupRules(acls) {
  const map = new Map();
  for (const a of acls) {
    const key = `${a.topic}\u0000${a.allow}\u0000${a.priority ?? 0}`;
    if (!map.has(key)) map.set(key, { topic: a.topic, allow: !!a.allow, priority: a.priority ?? 0, types: [] });
    map.get(key).types.push(a.acltype);
  }
  return [...map.values()].sort((a, b) => a.topic.localeCompare(b.topic));
}

function summary(types) {
  const has = (list) => list.every((x) => types.includes(x));
  let base = [];
  let label = null;
  if (has(READWRITE)) { base = READWRITE; label = 'roles.sum.readwrite'; }
  else if (has(READ)) { base = READ; label = 'roles.sum.read'; }
  else if (types.length === 1 && types[0] === 'publishClientSend') { base = types; label = 'roles.sum.write'; }
  return { label, extras: types.filter((x) => !base.includes(x)) };
}

export function renderRoles(root) {
  let roles = [];
  let clients = [];
  let groups = [];
  let selected = null;
  let raw = false;

  const view = h('div', { class: 'view' });
  const side = h('div', { class: 'side-list' });
  const detail = h('div', { class: 'detail' });
  const defaults = h('div');
  view.append(
    h('div', { class: 'page-head' },
      h('h1', {}, t('nav.roles')),
      h('button', { class: 'btn primary', type: 'button', onclick: openCreate }, t('roles.new'))),
    h('p', { class: 'muted' }, t('roles.intro')),
    h('div', { class: 'split' }, side, detail), defaults);
  root.append(view);

  async function load() {
    try {
      const [r, c, g] = await Promise.all([api('/roles'), api('/clients'), api('/groups')]);
      roles = r.roles; clients = c.clients; groups = g.groups;
      if (!roles.find((x) => x.rolename === selected)) selected = roles.length ? roles[0].rolename : null;
      drawSide(); drawDetail();
    } catch (err) {
      clear(detail).append(errorBox(err.message));
    }
  }

  function drawSide() {
    clear(side).append(...roles.map((r) => h('button', {
      class: `side-item${r.rolename === selected ? ' active' : ''}`, type: 'button',
      onclick: () => { selected = r.rolename; drawSide(); drawDetail(); },
    }, h('strong', {}, r.rolename), h('span', { class: 'muted small' },
      t('roles.topics', { n: groupRules(r.acls || []).length })))));
    if (!roles.length) side.append(h('p', { class: 'muted' }, t('roles.empty')));
  }

  function drawDetail() {
    const role = roles.find((r) => r.rolename === selected);
    if (!role) { clear(detail); return; }
    const users = clients.filter((c) => c.roles.some((x) => x.rolename === role.rolename));
    const grp = groups.filter((g) => (g.roles || []).some((x) => x.rolename === role.rolename));
    const acls = [...(role.acls || [])].sort((a, b) =>
      a.topic.localeCompare(b.topic) || a.acltype.localeCompare(b.acltype));

    const del = async () => {
      const ok = await confirmDialog({ title: t('roles.delete'),
        message: t('roles.delete.confirm', { r: role.rolename }), confirmLabel: t('common.delete'), danger: true });
      if (!ok) return;
      try { await api('/roles/delete', { rolename: role.rolename }); toast(t('common.deleted')); load(); } catch (e) { toast(e.message, 'error'); }
    };

    clear(detail).append(
      h('div', { class: 'card' },
        h('div', { class: 'card-head' },
          h('div', {}, h('h2', {}, role.rolename),
            role.textname ? h('div', { class: 'muted' }, role.textname) : null),
          h('button', { class: 'btn danger small', type: 'button', onclick: del }, t('roles.delete'))),
        h('p', { class: 'small' }, h('strong', {}, `${t('roles.usedby')}: `),
          users.length || grp.length
            ? [...users.map((u) => u.username), ...grp.map((g) => `${g.groupname} (${t('nav.groups').toLowerCase()})`)].join(', ')
            : t('roles.unused'))),
      h('label', { class: 'check', for: 'raw-rules' },
        h('input', { type: 'checkbox', id: 'raw-rules', checked: raw,
          onchange: (e) => { raw = e.target.checked; drawDetail(); } }), t('roles.raw')),
      raw ? rawTable(role, acls) : groupedTable(role),
      addRuleForm(role));
  }

  function groupedTable(role) {
    const groups = groupRules(role.acls || []);
    const removeGroup = async (g) => {
      try {
        for (const acltype of g.types) {
          await api('/roles/acl-remove', { rolename: role.rolename, acltype, topic: g.topic });
        }
        load();
      } catch (e) { toast(e.message, 'error'); load(); }
    };
    return h('div', { class: 'card flush scroll' }, h('table', { class: 'table compact' },
      h('thead', {}, h('tr', {}, h('th', {}, t('roles.col.what')), h('th', {}, t('roles.col.topic')),
        h('th', {}, t('roles.col.access')), h('th', {}, t('roles.col.priority')), h('th', {}))),
      h('tbody', {}, groups.length ? groups.map((g) => {
        const sum = summary(g.types);
        return h('tr', {},
          h('td', {}, sum.label ? h('strong', { title: g.types.map((x) => t(`acl.${x}`)).join(', ') }, t(sum.label)) : null,
            sum.extras.map((x) => h('span', { class: 'chip' }, t(`acl.${x}`)))),
          h('td', {}, h('code', {}, g.topic)),
          h('td', {}, h('span', { class: `badge ${g.allow ? 'ok' : 'bad'}` }, g.allow ? t('roles.allow') : t('roles.deny'))),
          h('td', {}, g.priority),
          h('td', { class: 'right' }, h('button', { class: 'btn small', type: 'button',
            onclick: () => removeGroup(g) }, t('common.remove'))));
      }) : h('tr', {}, h('td', { colspan: 5, class: 'muted' }, t('roles.norules'))))));
  }

  function rawTable(role, acls) {
    return h('div', { class: 'card flush scroll' }, h('table', { class: 'table compact' },
      h('thead', {}, h('tr', {}, h('th', {}, t('roles.col.type')), h('th', {}, t('roles.col.topic')),
        h('th', {}, t('roles.col.access')), h('th', {}, t('roles.col.priority')), h('th', {}))),
      h('tbody', {}, acls.length ? acls.map((a) => h('tr', {},
        h('td', {}, h('span', { title: t(`acl.${a.acltype}.help`) }, t(`acl.${a.acltype}`))),
        h('td', {}, h('code', {}, a.topic)),
        h('td', {}, h('span', { class: `badge ${a.allow ? 'ok' : 'bad'}` }, a.allow ? t('roles.allow') : t('roles.deny'))),
        h('td', {}, a.priority ?? 0),
        h('td', { class: 'right' }, h('button', { class: 'btn small', type: 'button', onclick: async () => {
          try { await api('/roles/acl-remove', { rolename: role.rolename, acltype: a.acltype, topic: a.topic }); load(); } catch (e) { toast(e.message, 'error'); }
        } }, t('common.remove')))))
        : h('tr', {}, h('td', { colspan: 5, class: 'muted' }, t('roles.norules'))))));
  }

  function addRuleForm(role) {
    const preset = h('select', {}, ['readwrite', 'read', 'write', 'single'].map((p) =>
      h('option', { value: p }, t(`roles.preset.${p}`))));
    const topic = h('input', { placeholder: 'shellies/#', required: true, maxLength: 1024 });
    const allow = h('select', {}, h('option', { value: 'true' }, t('roles.allow')),
      h('option', { value: 'false' }, t('roles.deny')));
    const type = h('select', {}, ACL_TYPES.map((a) => h('option', { value: a }, t(`acl.${a}`))));
    const typeField = field(t('roles.col.type'), type, t('roles.single.hint'));
    typeField.hidden = true;
    const hint = h('p', { class: 'muted small' }, t('roles.preset.readwrite.help'));
    preset.onchange = () => {
      typeField.hidden = preset.value !== 'single';
      hint.textContent = t(`roles.preset.${preset.value}.help`);
    };
    const err = h('div');
    const btn = h('button', { class: 'btn primary', type: 'submit' }, t('roles.addrule'));
    return h('form', { class: 'card form', onsubmit: async (e) => {
      e.preventDefault();
      btn.disabled = true;
      try {
        const body = { rolename: role.rolename, topic: topic.value.trim(), allow: allow.value === 'true' };
        if (preset.value === 'single') body.acltype = type.value; else body.preset = preset.value;
        await api('/roles/acl-add', body);
        toast(t('common.added'));
        clear(err);
        load();
      } catch (ex) { clear(err).append(errorBox(ex.message)); } finally { btn.disabled = false; }
    } },
    h('h3', {}, t('roles.addrule')),
    h('div', { class: 'grid form-grid' },
      field(t('roles.preset'), preset), field(t('roles.col.topic'), topic, t('roles.topic.hint')),
      field(t('roles.col.access'), allow), typeField),
    hint, err, h('div', { class: 'actions' }, btn));
  }

  function openCreate() {
    const m = openModal({ title: t('roles.new') });
    const name = h('input', { required: true, maxLength: 256 });
    const text = h('input', { maxLength: 512 });
    const err = h('div');
    m.set(h('form', { class: 'form', onsubmit: async (e) => {
      e.preventDefault();
      try {
        await api('/roles/create', { rolename: name.value.trim(), textname: text.value });
        selected = name.value.trim();
        m.close(); load();
      } catch (ex) { clear(err).append(errorBox(ex.message)); }
    } },
    field(t('roles.f.name'), name), field(t('roles.f.text'), text), err,
    h('div', { class: 'actions' },
      h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, t('common.cancel')),
      h('button', { class: 'btn primary', type: 'submit' }, t('common.create')))));
    name.focus();
  }

  // ---- default access (applies when no role rule matches)
  async function loadDefaults() {
    try {
      const { acls } = await api('/default-acl');
      const boxes = DEFAULT_TYPES.map((k) => ({ k, box: h('input', { type: 'checkbox', checked: !!acls[k] }) }));
      clear(defaults).append(h('div', { class: 'card' },
        h('h3', {}, t('defacl.title')),
        h('p', { class: 'muted small' }, t('defacl.help')),
        h('div', { class: 'checks' }, boxes.map((b) => h('label', { class: 'check' }, b.box, t(`defacl.${b.k}`)))),
        h('div', { class: 'actions' }, h('button', { class: 'btn', type: 'button', onclick: async () => {
          try {
            await api('/default-acl', { acls: Object.fromEntries(boxes.map((b) => [b.k, b.box.checked])) });
            toast(t('common.saved'));
          } catch (e) { toast(e.message, 'error'); }
        } }, t('common.save')))));
    } catch (err) {
      clear(defaults).append(errorBox(err.message));
    }
  }

  load();
  loadDefaults();
  return { dispose() {} };
}
