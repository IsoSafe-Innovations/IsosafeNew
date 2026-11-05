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
  window.dispatchEvent(new Event('isosafe:tokens-changed'));
}

export async function refreshAccessToken() {
  return tryRefresh();
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

// XHR exposes upload progress, while keeping the same JWT refresh behavior.
export async function uploadVideo(body, onProgress) {
  const send = () => new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/uploads');
    if (accessToken) xhr.setRequestHeader('Authorization', `Bearer ${accessToken}`);
    xhr.timeout = 30 * 60 * 1000;
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round(event.loaded * 100 / event.total));
    };
    xhr.onload = () => resolve(xhr);
    xhr.onerror = () => reject(new Error('Upload connection lost. Check the camera list before trying again.'));
    xhr.ontimeout = () => reject(new Error('Upload timed out. Check the camera list before trying again.'));
    xhr.send(body);
  });
  let response = await send();
  if (response.status === 401 && await tryRefresh()) {
    onProgress(0);
    response = await send();
  }
  if (response.status === 401) {
    setTokens(null, null);
    onLogout();
    throw new Error('Session expired. Sign in and try again.');
  }
  let result;
  try { result = JSON.parse(response.responseText); } catch { /* proxy error */ }
  if (response.status < 200 || response.status >= 300) {
    const detail = result?.detail;
    throw new Error(typeof detail === 'string' ? detail : Array.isArray(detail)
      ? detail[0]?.msg : response.status === 413 ? 'Video exceeds the server upload limit.' : 'The video could not be uploaded. Try again.');
  }
  if (!result?.camera_id) throw new Error('The server did not confirm the camera. Check the camera list before trying again.');
  return result;
}
