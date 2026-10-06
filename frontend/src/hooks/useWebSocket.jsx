import { useCallback, useEffect, useRef, useState } from 'react';
import { getAccessToken, refreshAccessToken } from '../lib/api';

// Single shared WebSocket for the whole app. Components register listeners
// and subscribe to camera frame streams; unsubscribed cameras only deliver
// count updates.

let socket = null;
let listeners = new Set();
let subscribed = new Set();
let reconnectTimer = null;

function scheduleReconnect(delayMs = 3000) {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, delayMs);
}

function connect() {
  const token = getAccessToken();
  if (!token) {
    scheduleReconnect();
    return;
  }
  if (socket?.readyState === WebSocket.OPEN || socket?.readyState === WebSocket.CONNECTING) {
    return;
  }

  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  socket = new WebSocket(`${proto}://${window.location.host}/api/ws?token=${token}`);

  socket.onopen = () => {
    if (subscribed.size) {
      socket.send(JSON.stringify({ action: 'set', camera_ids: [...subscribed] }));
    }
  };
  socket.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }
    listeners.forEach((fn) => fn(msg));
  };
  socket.onclose = async () => {
    socket = null;
    await refreshAccessToken().catch(() => {});
    scheduleReconnect();
  };
  socket.onerror = () => socket?.close();
}

export function resetWebSocket() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (socket) {
    socket.onclose = null;
    socket.close();
    socket = null;
  }
  connect();
}

function ensureConnected() {
  if (!socket && !reconnectTimer) connect();
}

function syncSubscriptions() {
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ action: 'set', camera_ids: [...subscribed] }));
  }
}

if (typeof window !== 'undefined') {
  window.addEventListener('isosafe:tokens-changed', resetWebSocket);
}

export function useWebSocket(onMessage) {
  const ref = useRef(onMessage);
  ref.current = onMessage;

  useEffect(() => {
    ensureConnected();
    const handler = (msg) => ref.current?.(msg);
    listeners.add(handler);
    return () => listeners.delete(handler);
  }, []);

  const subscribe = useCallback((cameraIds) => {
    cameraIds.forEach((id) => subscribed.add(id));
    syncSubscriptions();
  }, []);

  const unsubscribe = useCallback((cameraIds) => {
    cameraIds.forEach((id) => subscribed.delete(id));
    syncSubscriptions();
  }, []);

  return { subscribe, unsubscribe };
}

export function useLiveAlerts(max = 50) {
  const [alerts, setAlerts] = useState([]);
  useWebSocket((msg) => {
    if (msg.type === 'incident') {
      setAlerts((prev) => [msg, ...prev].slice(0, max));
    }
  });
  return alerts;
}
