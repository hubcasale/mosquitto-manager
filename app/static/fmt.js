import { t, lang } from './i18n.js';

export function fmtTime(ts) {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleString(lang(), { dateStyle: 'short', timeStyle: 'medium' });
}

export function ago(ts) {
  if (!ts) return '—';
  const diff = Math.round(Date.now() / 1000 - ts);
  const rtf = new Intl.RelativeTimeFormat(lang(), { numeric: 'auto' });
  const abs = Math.abs(diff);
  if (abs < 60) return rtf.format(-diff, 'second');
  if (abs < 3600) return rtf.format(-Math.round(diff / 60), 'minute');
  if (abs < 86400) return rtf.format(-Math.round(diff / 3600), 'hour');
  return rtf.format(-Math.round(diff / 86400), 'day');
}

export function uptime(seconds) {
  if (seconds === null || seconds === undefined) return '—';
  const d = Math.floor(seconds / 86400);
  const hh = Math.floor((seconds % 86400) / 3600);
  const mm = Math.floor((seconds % 3600) / 60);
  if (d) return t('fmt.uptime.dh', { d, h: hh });
  if (hh) return t('fmt.uptime.hm', { h: hh, m: mm });
  return t('fmt.uptime.m', { m: mm });
}

export function bytes(n) {
  if (n === null || n === undefined) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  let v = Number(n);
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
  return `${v.toFixed(i ? 1 : 0)} ${units[i]}`;
}

export function num(n, digits = 0) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return '—';
  return Number(n).toLocaleString(lang(), { maximumFractionDigits: digits });
}
