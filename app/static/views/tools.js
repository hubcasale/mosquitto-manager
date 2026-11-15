import { h, clear, field, errorBox } from '../dom.js';
import { api } from '../api.js';
import { t } from '../i18n.js';
import { testResult } from './clients.js';

// "Test connection": opens a short MQTT session with the given credentials, exactly
// like a device would, and reports the broker's answer.
export function renderTools(root, ctx) {
  const view = h('div', { class: 'view narrow' });
  const username = h('input', { required: true, autocomplete: 'off', maxLength: 256 });
  const password = h('input', { type: 'password', autocomplete: 'off', maxLength: 256 });
  const clientid = h('input', { autocomplete: 'off', maxLength: 256, placeholder: t('test.clientid.ph') });
  const out = h('div');
  const btn = h('button', { class: 'btn primary', type: 'submit' }, t('test.run'));

  view.append(
    h('div', { class: 'page-head' }, h('h1', {}, t('nav.test'))),
    h('p', { class: 'muted' }, t('test.intro')),
    h('form', { class: 'card form', onsubmit: async (e) => {
      e.preventDefault();
      btn.disabled = true;
      try {
        clear(out).append(testResult(await api('/test-login', {
          username: username.value.trim(), password: password.value,
          clientid: clientid.value.trim() || null })));
      } catch (ex) { clear(out).append(errorBox(ex.message)); } finally { btn.disabled = false; }
    } },
    field(t('clients.f.username'), username), field(t('clients.f.password'), password),
    field(t('test.clientid'), clientid, t('test.clientid.hint')),
    h('div', { class: 'actions' }, btn), out),
    h('div', { class: 'card' },
      h('h3', {}, t('test.tips.title')),
      h('ul', { class: 'tips' }, ['1', '2', '3', '4'].map((n) => h('li', {}, t(`test.tip.${n}`))))));
  root.append(view);
  return { dispose() {} };
}
