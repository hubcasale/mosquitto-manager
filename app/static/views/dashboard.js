import { h, clear } from '../dom.js';
import { t } from '../i18n.js';
import { fmtTime, uptime, num } from '../fmt.js';
import { lineChart } from '../chart.js';
import { eventLine } from './activity.js';

function stat(label, value, sub, tone) {
  return h('div', { class: `card stat${tone ? ` ${tone}` : ''}` },
    h('div', { class: 'stat-label' }, label),
    h('div', { class: 'stat-value' }, value),
    sub ? h('div', { class: 'stat-sub' }, sub) : null);
}

function alerts(s) {
  const out = [];
  if (!s.broker.connected) {
    out.push(h('div', { class: 'notice error' },
      h('strong', {}, t('dash.offline')), ' ',
      `${s.broker.host}:${s.broker.port}`, s.broker.error ? ` — ${s.broker.error}` : ''));
    return out;
  }
  if (s.dynsec.state === 'no_response') {
    out.push(h('div', { class: 'notice error' },
      h('strong', {}, t('dash.dynsec.title')), ' ', t('dash.dynsec.body')));
  }
  if (!s.broker.has_sys) {
    out.push(h('div', { class: 'notice warn' }, t('dash.nosys')));
  }
  if (!s.log_feed) {
    out.push(h('div', { class: 'notice info' },
      h('strong', {}, t('dash.nolog.title')), ' ', t('dash.nolog.body'),
      h('code', {}, ' log_dest topic')));
  }
  if (s.failed_logins_24h > 0) {
    out.push(h('div', { class: 'notice warn' },
      t('dash.failed', { n: s.failed_logins_24h }), ' ',
      h('a', { href: '#/activity?kind=auth_failed' }, t('dash.failed.link'))));
  }
  return out;
}

function haCard(ha) {
  if (!ha || !ha.enabled) {
    return h('div', { class: 'card' }, h('h3', {}, t('ha.title')),
      h('p', { class: 'muted' }, t('ha.off')), h('p', { class: 'muted small' }, t('ha.off.hint'), h('code', {}, ' HA_DISCOVERY=true')));
  }
  if (ha.state === 'ok') {
    return h('div', { class: 'card' }, h('h3', {}, t('ha.title')),
      h('p', {}, h('span', { class: 'badge ok' }, h('i', { class: 'dot' }), t('ha.ok')), ' ',
        t('ha.ok.detail', { n: ha.entities, p: ha.prefix })));
  }
  return h('div', { class: `notice ${ha.state === 'error' ? 'error' : 'info'}` },
    h('strong', {}, t('ha.title')), ' ',
    ha.state === 'error' ? t('ha.error', { e: ha.error || '' }) : t('ha.starting'));
}

export function renderDashboard(root, ctx) {
  const view = h('div', { class: 'view' });
  root.append(view);

  function paint(s) {
    if (!s) return;
    const b = s.broker;
    const hist = s.history || [];
    const times = hist.map((p) => p.t);
    clear(view).append(
      h('div', { class: 'page-head' },
        h('h1', {}, t('nav.dashboard')),
        h('p', { class: 'muted' }, `${b.host}:${b.port}`)),
      ...alerts(s),
      h('div', { class: 'grid stats' },
        stat(t('dash.broker'), b.version || '—',
          t('dash.uptime', { v: uptime(b.uptime) }), b.connected ? 'ok' : 'bad'),
        stat(t('dash.connected'), num(b.clients_connected),
          t('dash.total', { n: num(b.clients_total) })),
        stat(t('dash.subs'), num(b.subscriptions), t('dash.retained', { n: num(b.retained) })),
        stat(t('dash.rate'), `${num(b.msg_rate_in, 1)} / ${num(b.msg_rate_out, 1)}`,
          t('dash.rate.sub')),
        stat(t('dash.enc'), num(s.encryption.tls), t('dash.enc.sub', {
          plain: num(s.encryption.plain), unknown: num(s.encryption.unknown) }),
        s.encryption.plain > 0 ? 'warn' : ''),
        stat(t('dash.failedlogins'), num(s.failed_logins_24h), t('dash.24h'),
          s.failed_logins_24h > 0 ? 'warn' : '')),
      h('div', { class: 'grid two' },
        h('div', { class: 'card' },
          h('h3', {}, t('dash.chart.clients')),
          lineChart(times, [{ label: t('dash.connected'), cls: 's0',
            values: hist.map((p) => p.connected) }])),
        h('div', { class: 'card' },
          h('h3', {}, t('dash.chart.msgs')),
          lineChart(times, [
            { label: t('dash.in'), cls: 's0', values: hist.map((p) => p.in) },
            { label: t('dash.out'), cls: 's1', values: hist.map((p) => p.out) }]))),
      haCard(s.ha),
      h('div', { class: 'card' },
        h('div', { class: 'card-head' },
          h('h3', {}, t('dash.recent')),
          h('a', { href: '#/activity' }, t('dash.all'))),
        s.events.length
          ? h('ul', { class: 'events' }, s.events.map((e) => eventLine(e)))
          : h('p', { class: 'muted' }, t('dash.noevents'))),
      h('p', { class: 'muted small' }, t('dash.updated', { v: fmtTime(Date.now() / 1000) })));
  }

  paint(ctx.status);
  const unsub = ctx.subscribe(paint);
  return { dispose: unsub };
}
