// Tiny DOM helpers. Text is always inserted as text nodes (never innerHTML),
// so data coming from the broker cannot inject markup.
import { t } from './i18n.js';

const SVG_NS = 'http://www.w3.org/2000/svg';

function applyProps(el, props) {
  for (const [k, v] of Object.entries(props || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (el instanceof SVGElement) el.setAttribute(k, v);
    else if (k === 'class') el.className = v;
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (k in el && k !== 'list' && k !== 'form') el[k] = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
}

function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export function h(tag, props, ...children) {
  const el = document.createElement(tag);
  applyProps(el, props);
  append(el, children);
  return el;
}

export function svg(tag, props, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  applyProps(el, props);
  append(el, children);
  return el;
}

export function clear(el) {
  el.replaceChildren();
  return el;
}

// ---------------------------------------------------------------- toast
let toastBox;
export function toast(message, kind = 'ok') {
  if (!toastBox) {
    toastBox = h('div', { class: 'toasts', role: 'status', 'aria-live': 'polite' });
    document.body.append(toastBox);
  }
  const el = h('div', { class: `toast ${kind}` }, message);
  toastBox.append(el);
  setTimeout(() => el.remove(), kind === 'error' ? 7000 : 3500);
}

// ---------------------------------------------------------------- modal
export function openModal({ title, wide = false, onClose } = {}) {
  const body = h('div', { class: 'modal-body' });
  const dlg = h('dialog', { class: `modal${wide ? ' wide' : ''}` },
    h('div', { class: 'modal-head' },
      h('h2', {}, title || ''),
      h('button', { class: 'icon-btn', type: 'button', 'aria-label': t('common.close'),
        onclick: () => dlg.close() }, '×')),
    body);
  dlg.addEventListener('close', () => { dlg.remove(); onClose && onClose(); });
  dlg.addEventListener('click', (e) => { if (e.target === dlg) dlg.close(); });
  document.body.append(dlg);
  dlg.showModal();
  return {
    el: dlg,
    body,
    set(...nodes) { body.replaceChildren(); append(body, nodes); },
    setTitle(text) { dlg.querySelector('h2').textContent = text; },
    close() { dlg.close(); },
  };
}

export function confirmDialog({ title, message, confirmLabel, danger = false }) {
  return new Promise((resolve) => {
    let answer = false;
    const m = openModal({ title, onClose: () => resolve(answer) });
    m.set(
      h('p', {}, message),
      h('div', { class: 'actions' },
        h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, t('common.cancel')),
        h('button', { class: `btn ${danger ? 'danger' : 'primary'}`, type: 'button',
          onclick: () => { answer = true; m.close(); } }, confirmLabel || t('common.confirm'))));
  });
}

// ---------------------------------------------------------------- misc
export function randomPassword(length = 20) {
  const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789';
  const bytes = new Uint8Array(length);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => alphabet[b % alphabet.length]).join('');
}

export function field(label, input, hint) {
  return h('label', { class: 'field' },
    h('span', { class: 'field-label' }, label), input,
    hint ? h('span', { class: 'hint' }, hint) : null);
}

export function errorBox(message) {
  return h('div', { class: 'notice error', role: 'alert' }, message);
}

export function busy(button, fn) {
  return async (...args) => {
    button.disabled = true;
    try { return await fn(...args); } finally { button.disabled = false; }
  };
}
