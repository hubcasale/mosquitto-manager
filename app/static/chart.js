import { h, svg } from './dom.js';
import { t } from './i18n.js';

// Minimal line chart: series = [{ label, cls, values: [number|null] }], times = [epoch].
export function lineChart(times, series, { height = 90 } = {}) {
  const width = 400;
  const pad = 4;
  const all = series.flatMap((s) => s.values).filter((v) => typeof v === 'number');
  if (times.length < 2 || !all.length) {
    return h('div', { class: 'chart-empty' }, t('dash.collecting'));
  }
  const max = Math.max(1, ...all);
  const x = (i) => pad + (i / (times.length - 1)) * (width - 2 * pad);
  const y = (v) => height - pad - (v / max) * (height - 2 * pad);

  const lines = series.map((s) => {
    const pts = s.values
      .map((v, i) => (typeof v === 'number' ? `${x(i).toFixed(1)},${y(v).toFixed(1)}` : null))
      .filter(Boolean)
      .join(' ');
    return svg('polyline', { points: pts, class: `line ${s.cls}`, fill: 'none' });
  });

  const chart = svg('svg', { viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: 'none',
    role: 'img', 'aria-label': series.map((s) => s.label).join(' / ') },
    svg('line', { x1: pad, x2: width - pad, y1: height - pad, y2: height - pad, class: 'axis' }),
    ...lines);

  const legend = h('div', { class: 'legend' },
    series.map((s) => h('span', {}, h('i', { class: `swatch ${s.cls}` }), s.label)),
    h('span', { class: 'muted' }, `max ${Number.isInteger(max) ? max : max.toFixed(1)}`));
  return h('div', { class: 'chart' }, chart, legend);
}
