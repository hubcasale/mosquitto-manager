import { h, svg, clear, openModal, toast, field, errorBox } from '../dom.js';
import { api } from '../api.js';
import { t } from '../i18n.js';
import { ago, fmtTime } from '../fmt.js';
import { encryptionBadge } from './clients.js';

const W = 1000;
const H = 760;
const CX = W / 2;
const CY = H / 2;
const R_HOST = 150;
const R_CLIENT = 280;
const R_CLIENT_ALT = 350;

const trunc = (s, n) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);
const polar = (angle, r) => [CX + r * Math.cos(angle), CY + r * Math.sin(angle)];

// One group per address (connected hosts, then refused sources), spread evenly around the broker.
function layout(data) {
  const groups = [
    ...data.hosts.map((host) => ({ kind: 'host', host, n: host.clients.length })),
    ...data.refused.map((ref) => ({ kind: 'refused', ref, n: 0 })),
  ];
  const k = groups.length;
  groups.forEach((g, i) => {
    g.mid = -Math.PI / 2 + (i * 2 * Math.PI) / k;
    g.room = (2 * Math.PI / k) * 0.9;
    g.step = g.n > 1 ? Math.min(0.3, g.room / g.n) : 0;
  });
  return groups;
}

// Where to put a client's two label lines (name, client id) relative to its dot.
function labelAnchor(angle) {
  const c = Math.cos(angle);
  if (c > 0.25) return { anchor: 'start', dx: 14, dy: 4, sub: 17 };
  if (c < -0.25) return { anchor: 'end', dx: -14, dy: 4, sub: 17 };
  // above or below the dot: keep both lines clear of it
  return Math.sin(angle) < 0
    ? { anchor: 'middle', dx: 0, dy: -30, sub: 13 }
    : { anchor: 'middle', dx: 0, dy: 26, sub: 13 };
}

function drawMap(data, { onClient, onHost }) {
  const nodes = [];
  const edges = [];
  const labels = [];

  for (const g of layout(data)) {
    const [hx, hy] = polar(g.mid, R_HOST);
    const refused = g.kind === 'refused';
    const info = refused ? g.ref : g.host;
    edges.push(svg('line', { x1: CX, y1: CY, x2: hx, y2: hy, class: refused ? 'edge refused' : 'edge host' }));

    if (!refused) {
      const crowded = g.n > 5;
      g.host.clients.forEach((c, i) => {
        const angle = g.mid + (i - (g.n - 1) / 2) * g.step;
        const radius = crowded && i % 2 ? R_CLIENT_ALT : R_CLIENT;
        const [x, y] = polar(angle, radius);
        edges.push(svg('line', { x1: hx, y1: hy, x2: x, y2: y, class: 'edge client' }));
        const a = labelAnchor(angle);
        nodes.push(svg('g', { class: 'node clickable', tabindex: 0, role: 'button',
          'aria-label': c.username, onclick: () => onClient(c.username),
          onkeydown: (e) => { if (e.key === 'Enter') onClient(c.username); } },
        svg('title', {}, [c.username, c.clientid, c.protocol,
          c.encrypted === true ? t('clients.enc.tls') : c.encrypted === false ? t('clients.enc.plain') : '',
          c.since ? ago(c.since) : ''].filter(Boolean).join(' · ')),
        svg('circle', { cx: x, cy: y, r: 10,
          class: `dot ${c.is_manager ? 'manager' : 'online'}${c.encrypted === false ? ' plain' : ''}` }),
        svg('text', { x: x + a.dx, y: y + a.dy, 'text-anchor': a.anchor, class: 'client-label' },
          trunc(c.username, crowded ? 16 : 20) + (c.is_manager ? ' ⚙' : ''))));
        if (c.clientid && !crowded) {
          labels.push(svg('text', { x: x + a.dx, y: y + a.dy + a.sub, 'text-anchor': a.anchor, class: 'sub-label' },
            trunc(c.clientid, 22)));
        }
      });
    }

    const text = trunc(info.label, 18);
    const width = Math.max(96, text.length * 8 + 28);
    nodes.push(svg('g', { class: 'node clickable', tabindex: 0, role: 'button',
      'aria-label': info.label, onclick: () => onHost(info),
      onkeydown: (e) => { if (e.key === 'Enter') onHost(info); } },
    svg('title', {}, info.alias ? `${info.alias} (${info.address})` : info.address),
    svg('rect', { x: hx - width / 2, y: hy - 19, width, height: 38, rx: 10,
      class: refused ? 'host-box refused' : 'host-box' }),
    svg('text', { x: hx, y: hy - 2, 'text-anchor': 'middle', class: 'host-label' }, text),
    svg('text', { x: hx, y: hy + 12, 'text-anchor': 'middle', class: 'host-sub' },
      refused ? t('map.attempts', { n: info.attempts }) : t('map.clients', { n: g.n }))));
  }

  const broker = svg('g', { class: 'node' },
    svg('circle', { cx: CX, cy: CY, r: 46, class: 'broker' }),
    svg('text', { x: CX, y: CY - 2, 'text-anchor': 'middle', class: 'broker-label' }, 'Mosquitto'),
    svg('text', { x: CX, y: CY + 15, 'text-anchor': 'middle', class: 'broker-sub' },
      data.broker.version || ''));

  return svg('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', class: 'netmap',
    'aria-label': t('nav.map') }, ...edges, broker, ...labels, ...nodes);
}

export function renderMap(root) {
  let timer;
  const view = h('div', { class: 'view' });
  const mapBox = h('div', { class: 'card map-card' });
  const extra = h('div');
  view.append(
    h('div', { class: 'page-head' }, h('h1', {}, t('nav.map'))),
    h('p', { class: 'muted' }, t('map.intro')),
    mapBox, extra);
  root.append(view);

  function renameHost(info) {
    const m = openModal({ title: info.alias ? `${info.alias} (${info.address})` : info.address });
    const name = h('input', { value: info.alias || '', maxLength: 64, placeholder: t('map.host.ph') });
    const err = h('div');
    const save = async (value) => {
      try {
        await api('/hosts/alias', { address: info.address, name: value });
        m.close();
        load();
      } catch (ex) { clear(err).append(errorBox(ex.message)); }
    };
    m.set(
      h('p', { class: 'muted' }, t('map.host.hint', { addr: info.address })),
      info.clientids ? h('p', { class: 'small' }, `${t('act.clientids')}: ${info.clientids.join(', ')}`) : null,
      field(t('map.host.name'), name), err,
      h('div', { class: 'actions' },
        info.alias ? h('button', { class: 'btn', type: 'button', onclick: () => save('') }, t('map.host.clear')) : null,
        h('button', { class: 'btn primary', type: 'button', onclick: () => save(name.value) }, t('common.save'))));
    name.focus();
  }

  const openClient = (username) => { location.hash = `#/clients?open=${encodeURIComponent(username)}`; };

  async function load() {
    try {
      const data = await api('/map');
      draw(data);
    } catch (err) {
      clear(mapBox).append(errorBox(err.message));
    }
  }

  function draw(data) {
    clear(mapBox);
    if (!data.hosts.length && !data.refused.length) {
      mapBox.append(drawMap(data, { onClient: openClient, onHost: renameHost }),
        h('p', { class: 'muted center' }, t('map.empty')));
    } else {
      mapBox.append(drawMap(data, { onClient: openClient, onHost: renameHost }));
    }
    mapBox.append(h('div', { class: 'legend map-legend' },
      h('span', {}, h('i', { class: 'swatch online' }), t('map.legend.client')),
      h('span', {}, h('i', { class: 'swatch manager' }), t('map.legend.manager')),
      h('span', {}, h('i', { class: 'swatch plain' }), t('map.legend.plain')),
      h('span', {}, h('i', { class: 'swatch refused' }), t('map.legend.refused')),
      h('span', { class: 'muted' }, t('map.legend.click'))));

    const rows = data.hosts.flatMap((host) => host.clients.map((c) => ({ host, c })));
    clear(extra).append(
      data.offline.length ? h('div', { class: 'card' },
        h('h3', {}, t('map.offline')),
        h('div', { class: 'chips' }, data.offline.map((o) => h('button', {
          class: `chip${o.disabled ? ' off' : ''}`, type: 'button', onclick: () => openClient(o.username),
          title: o.last_seen ? t('clients.lastseen', { v: ago(o.last_seen) }) : '',
        }, o.username + (o.disabled ? ` (${t('clients.disabled').toLowerCase()})` : ''))))) : null,
      rows.length ? h('div', { class: 'card flush scroll' },
        h('table', { class: 'table compact' },
          h('thead', {}, h('tr', {}, h('th', {}, t('act.address')), h('th', {}, t('clients.col.user')),
            h('th', {}, t('clients.f.clientid')), h('th', {}, t('clients.proto')), h('th', {}, t('clients.enc')),
            h('th', {}, t('clients.since')))),
          h('tbody', {}, rows.map(({ host, c }) => h('tr', {},
            h('td', {}, host.alias ? `${host.alias} ` : '', h('code', {}, host.address)),
            h('td', {}, c.username), h('td', {}, c.clientid || '—'),
            h('td', {}, c.protocol ? `${c.protocol} · ${c.keepalive}s` : '—'),
            h('td', {}, encryptionBadge(c)),
            h('td', { title: c.since ? fmtTime(c.since) : '' }, c.since ? ago(c.since) : '—')))))) : null,
      h('p', { class: 'muted small' }, t('map.docker.hint')));
  }

  load();
  timer = setInterval(load, 5000);
  return { dispose: () => clearInterval(timer) };
}
