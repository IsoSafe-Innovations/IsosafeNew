// API client with JWT injection and automatic refresh on 401.

let accessToken = localStorage.getItem('isosafe_access') || null;
let refreshToken = localStorage.getItem('isosafe_refresh') || null;
let onLogout = () => {};

export function setTokens(access, refresh) {
  accessToken = access;
  refreshToken = refresh;
  if (access) localStorage.setItem('isosafe_access', access);
  else localStorage.removeItem('isosafe_access');
  if (refresh) localStorage.setItem('isosafe_refresh', refresh);
  else localStorage.removeItem('isosafe_refresh');
}

export function getAccessToken() {
  return accessToken;
}

export function setLogoutHandler(fn) {
  onLogout = fn;
}

async function tryRefresh() {
  if (!refreshToken) return false;
  const res = await fetch('/api/auth/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!res.ok) return false;
  const data = await res.json();
  setTokens(data.access_token, data.refresh_token);
  return true;
}

export async function api(path, options = {}) {
  const isAuthRoute = path.startsWith('/api/auth/login') || path.startsWith('/api/auth/refresh');
  const doFetch = () =>
    fetch(path, {
      ...options,
      headers: {
        ...(options.body && !(options.body instanceof FormData)
          ? { 'Content-Type': 'application/json' }
          : {}),
        ...(!isAuthRoute && accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        ...(options.headers || {}),
      },
    });

  let res = await doFetch();
  if (!isAuthRoute && res.status === 401 && (await tryRefresh())) {
    res = await doFetch();
  }
  if (res.status === 401) {
    if (!isAuthRoute) {
      setTokens(null, null);
      onLogout();
      throw new Error('Session expired');
    }
    let detail = 'Invalid credentials';
    try {
      const body = await res.json();
      detail = body.detail || detail;
      if (Array.isArray(detail)) detail = detail[0]?.msg || 'Invalid credentials';
    } catch { /* not json */ }
    throw new Error(typeof detail === 'string' ? detail : 'Invalid credentials');
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch { /* not json */ }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) return res.json();
  return res;
}

export const get = (path) => api(path);
export const post = (path, body) =>
  api(path, { method: 'POST', body: body instanceof FormData ? body : JSON.stringify(body) });
export const patch = (path, body) =>
  api(path, { method: 'PATCH', body: JSON.stringify(body) });
export const del = (path) => api(path, { method: 'DELETE' });
