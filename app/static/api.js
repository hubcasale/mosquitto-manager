import { t } from './i18n.js';

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

let onAuthLost = () => {};
export function setAuthLostHandler(fn) { onAuthLost = fn; }

function formatDetail(detail) {
  if (!detail) return '';
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ');
  }
  return JSON.stringify(detail);
}

// GET when `body` is undefined, otherwise POST with a JSON body.
export async function api(path, body) {
  const opts = {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'X-Requested-With': 'mosquitto-manager' },
    credentials: 'same-origin',
  };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(`api${path}`, opts);
  } catch {
    throw new ApiError(t('err.network'), 0);
  }
  let data = null;
  try { data = await res.json(); } catch { /* empty or non-JSON body */ }
  if (res.status === 401 && path !== '/login') {
    onAuthLost();
    throw new ApiError(t('err.auth'), 401);
  }
  if (!res.ok) throw new ApiError(formatDetail(data && data.detail) || res.statusText, res.status);
  return data;
}
