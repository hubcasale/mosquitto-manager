import { h, clear, errorBox } from '../dom.js';
import { api } from '../api.js';
import { t } from '../i18n.js';
import { fmtTime, ago } from '../fmt.js';

const KIND_TONE = { connect: 'ok', disconnect: 'muted', auth_failed: 'bad', admin: 'info', log: 'warn' };

export function kindBadge(kind) {
  return h('span', { class: `badge ${KIND_TONE[kind] || 'muted'}` }, t(`kind.${kind}`));
}

function describe(e) {
  const who = e.username || e.clientid || '—';
  switch (e.kind) {
    case 'connect':
      return t('ev.connect', { who, addr: e.address || '?', proto: (e.extra && e.extra.protocol) || '' });
    case 'disconnect':
      return t('ev.disconnect', { who, addr: e.address || '?' }) + (e.reason ? ` (${e.reason})` : '');
    case 'auth_failed':
      return t('ev.authfailed', { who: e.clientid || '—', addr: e.address || '?' });
    case 'admin': {
      const actor = (e.actor || '').startsWith('mosquitto-manager') ? t('ev.viamanager') : e.actor;
      return `${e.extra.command} ${e.extra.args || ''}`.trim() + (actor ? ` — ${actor}` : '');
    }
    default:
      return e.message;
  }
}

// One compact line, used by the dashboard.
export function eventLine(e) {
  return h('li', {}, kindBadge(e.kind), h('span', { class: 'ev-text' }, describe(e)),
    h('time', { class: 'muted', title: fmtTime(e.ts) }, ago(e.ts)));
}

const FILTERS = [
  { id: 'all', kinds: '' },
  { id: 'connections', kinds: 'connect,disconnect' },
  { id: 'auth_failed', kinds: 'auth_failed' },
  { id: 'admin', kinds: 'admin' },
];

export function renderActivity(root, ctx, query = {}) {
  let filter = FILTERS.find((f) => f.id === query.kind || f.kinds === query.kind) || FILTERS[0];
  let internal = false;
  let timer;
  const view = h('div', { class: 'view' });
  const tabs = h('div', { class: 'tabs', role: 'tablist' });
  const body = h('div');
  const internalBox = h('input', { type: 'checkbox', id: 'show-internal',
    onchange: (e) => { internal = e.target.checked; load(); } });
  view.append(
    h('div', { class: 'page-head' }, h('h1', {}, t('nav.activity'))),
    tabs,
    h('label', { class: 'check', for: 'show-internal' }, internalBox, t('act.internal')),
    body);
  root.append(view);

  function drawTabs() {
    clear(tabs).append(...FILTERS.map((f) => h('button', {
      class: `tab${f === filter ? ' active' : ''}`, type: 'button', role: 'tab',
      'aria-selected': f === filter ? 'true' : 'false',
      onclick: () => { filter = f; drawTabs(); load(); },
    }, t(`act.filter.${f.id}`))));
  }

  function failingSources(events) {
    const counts = new Map();
    for (const e of events) {
      if (e.kind !== 'auth_failed') continue;
      const key = e.address || '?';
      const cur = counts.get(key) || { n: 0, ids: new Set(), last: 0 };
      cur.n += 1; cur.ids.add(e.clientid); cur.last = Math.max(cur.last, e.ts);
      counts.set(key, cur);
    }
    if (!counts.size) return null;
    const rows = [...counts.entries()].sort((a, b) => b[1].n - a[1].n).slice(0, 8);
    return h('div', { class: 'card' },
      h('h3', {}, t('act.sources')),
      h('p', { class: 'muted small' }, t('act.sources.hint')),
      h('table', { class: 'table compact' },
        h('thead', {}, h('tr', {}, h('th', {}, t('act.address')), h('th', {}, t('act.attempts')),
          h('th', {}, t('act.clientids')), h('th', {}, t('act.last')))),
        h('tbody', {}, rows.map(([addr, c]) => h('tr', {},
          h('td', {}, h('code', {}, addr)), h('td', {}, c.n),
          h('td', {}, [...c.ids].slice(0, 4).join(', ')), h('td', {}, ago(c.last)))))));
  }

  async function load() {
    try {
      const data = await api(`/events?limit=300&internal=${internal}`
        + (filter.kinds ? `&kind=${filter.kinds}` : ''));
      clear(body);
      if (!data.log_feed) {
        body.append(h('div', { class: 'notice info' },
          h('strong', {}, t('dash.nolog.title')), ' ', t('dash.nolog.body'),
          h('code', {}, ' log_dest topic')));
      }
      if (filter.id === 'auth_failed') {
        const src = failingSources(data.events);
        if (src) body.append(src);
      }
      if (!data.events.length) {
        body.append(h('p', { class: 'muted empty' }, t('act.empty')));
        return;
      }
      body.append(h('div', { class: 'card flush' }, h('table', { class: 'table' },
        h('thead', {}, h('tr', {}, h('th', {}, t('act.time')), h('th', {}, t('act.type')),
          h('th', {}, t('act.details')))),
        h('tbody', {}, data.events.map((e) => h('tr', {},
          h('td', { class: 'nowrap', title: fmtTime(e.ts) }, fmtTime(e.ts)),
          h('td', {}, kindBadge(e.kind)),
          h('td', {}, describe(e))))))));
    } catch (err) {
      clear(body).append(errorBox(err.message));
    }
  }

  drawTabs();
  load();
  timer = setInterval(load, 4000);
  return { dispose: () => clearInterval(timer) };
}
