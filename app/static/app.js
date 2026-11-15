import { h, clear, field, errorBox } from './dom.js';
import { api, setAuthLostHandler } from './api.js';
import { t, lang, setLang, LANGS } from './i18n.js';
import { renderDashboard } from './views/dashboard.js';
import { renderClients } from './views/clients.js';
import { renderMap } from './views/map.js';
import { renderRoles } from './views/roles.js';
import { renderGroups } from './views/groups.js';
import { renderActivity } from './views/activity.js';
import { renderTools } from './views/tools.js';

const root = document.getElementById('app');

const ROUTES = [
  { id: 'dashboard', render: renderDashboard },
  { id: 'clients', render: renderClients },
  { id: 'map', render: renderMap },
  { id: 'roles', render: renderRoles },
  { id: 'groups', render: renderGroups },
  { id: 'activity', render: renderActivity },
  { id: 'test', render: renderTools },
];

// Shared live status, polled once for the whole app.
const ctx = {
  status: null,
  listeners: new Set(),
  subscribe(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); },
  emit() { this.listeners.forEach((fn) => fn(this.status)); },
  refresh() { return refreshStatus(); },
};

let session = { auth_required: true, version: '' };
let statusTimer = null;
let currentView = null;

function parseHash() {
  const [path, qs = ''] = location.hash.replace(/^#\/?/, '').split('?');
  return { id: path || 'dashboard', query: Object.fromEntries(new URLSearchParams(qs)) };
}

function stopPolling() {
  clearInterval(statusTimer);
  statusTimer = null;
}

// ------------------------------------------------------------------ login
function showLogin(message = '') {
  stopPolling();
  currentView && currentView.dispose && currentView.dispose();
  currentView = null;
  const pw = h('input', { type: 'password', required: true, autocomplete: 'current-password',
    autofocus: true, maxLength: 256 });
  const err = h('div');
  if (message) err.append(errorBox(message));
  const btn = h('button', { class: 'btn primary', type: 'submit' }, t('login.submit'));
  clear(root).append(h('main', { class: 'login' },
    h('form', { class: 'card form', onsubmit: async (e) => {
      e.preventDefault();
      btn.disabled = true;
      try {
        await api('/login', { password: pw.value });
        start();
      } catch (ex) {
        clear(err).append(errorBox(ex.message));
        pw.select();
      } finally { btn.disabled = false; }
    } },
    h('div', { class: 'brand big' }, h('span', { class: 'logo' }), 'Mosquitto Manager'),
    field(t('login.password'), pw), err, btn,
    h('p', { class: 'muted small center' }, session.version ? `v${session.version}` : ''))));
  pw.focus();
}

// ------------------------------------------------------------------ shell
function languagePicker() {
  const sel = h('select', { 'aria-label': t('common.language'), onchange: (e) => { setLang(e.target.value); start(); } },
    Object.entries(LANGS).map(([k, v]) => h('option', { value: k, selected: k === lang() }, v)));
  return sel;
}

function showShell() {
  const pill = h('span', { class: 'pill', id: 'broker-pill' });
  const main = h('main', { class: 'content', id: 'main' });
  const nav = h('nav', { class: 'nav', 'aria-label': 'Main' },
    ROUTES.map((r) => h('a', { href: `#/${r.id}`, dataset: { route: r.id } }, t(`nav.${r.id}`))));

  const updatePill = () => {
    const s = ctx.status;
    pill.className = `pill ${s ? (s.broker.connected ? 'ok' : 'bad') : 'muted'}`;
    pill.textContent = s ? (s.broker.connected ? t('pill.online') : t('pill.offline')) : '…';
  };

  clear(root).append(
    h('header', { class: 'topbar' },
      h('div', { class: 'brand' }, h('span', { class: 'logo' }), 'Mosquitto Manager'),
      nav,
      h('div', { class: 'tools' }, pill, languagePicker(),
        session.auth_required
          ? h('button', { class: 'btn small', type: 'button', onclick: async () => {
            await api('/logout', {}).catch(() => {});
            showLogin();
          } }, t('login.logout')) : null)),
    main,
    h('footer', { class: 'foot muted small' }, `Mosquitto Manager v${session.version}`));

  ctx.subscribe(updatePill);
  updatePill();

  function route() {
    currentView && currentView.dispose && currentView.dispose();
    const { id, query } = parseHash();
    const r = ROUTES.find((x) => x.id === id) || ROUTES[0];
    nav.querySelectorAll('a').forEach((a) => {
      const on = a.dataset.route === r.id;
      a.classList.toggle('active', on);
      if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
    clear(main);
    currentView = r.render(main, ctx, query) || null;
  }
  window.onhashchange = route;
  route();
}

async function refreshStatus() {
  let status;
  try {
    status = await api('/status');
  } catch {
    return; // the API wrapper handles 401; network errors keep the last status
  }
  ctx.status = status;
  ctx.emit();
}

async function start() {
  ctx.listeners.clear();
  stopPolling();
  document.documentElement.lang = lang();
  try {
    session = await api('/session');
  } catch (ex) {
    clear(root).append(h('main', { class: 'login' }, errorBox(ex.message)));
    return;
  }
  if (session.auth_required && !session.authenticated) { showLogin(); return; }
  showShell();
  await refreshStatus();
  statusTimer = setInterval(refreshStatus, 5000);
}

setAuthLostHandler(() => showLogin(t('err.auth')));
start();
