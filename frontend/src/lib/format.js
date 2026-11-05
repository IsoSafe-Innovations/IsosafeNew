// Severity → component classes from index.css.
export const SEVERITY_CLASS = {
  info: 'sev sev-info',
  warning: 'sev sev-warning',
  critical: 'sev sev-critical',
};

// Severity → Tailwind background for stripes and dots.
export const SEVERITY_STRIPE = {
  info: 'bg-info',
  warning: 'bg-warning',
  critical: 'bg-critical',
};

// Hex values for SVG/recharts, mirroring the tokens in index.css.
export const CHART = {
  accent: '#0b6b3a',   // brand green, one step lighter so bars read on white
  crit: '#dc3b36',
  warn: '#c77700',
  info: '#0e8fa8',
  ok: '#1f9d5c',
  grid: '#e3e8ef',
  axis: '#6b7789',
  panel: '#ffffff',
  ink: '#111827',
};

export const CHART_TOOLTIP = {
  contentStyle: {
    background: '#ffffff', border: '1px solid #cfd7e2', borderRadius: 8,
    boxShadow: '0 4px 14px rgba(16,24,40,.08)', fontSize: 12,
  },
  labelStyle: { color: '#111827', fontWeight: 500 },
  cursor: { fill: 'rgba(2,68,32,.06)' },
};

export const STATUS_LABELS = {
  open: 'Open',
  investigating: 'Investigating',
  resolved: 'Resolved',
  closed: 'Closed',
};

export function fmtTime(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

export function fmtHour(iso) {
  return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

export function fmtNumber(n) {
  if (n == null) return '—';
  return new Intl.NumberFormat().format(n);
}

export function trendDelta(today, yesterday) {
  if (!yesterday) return null;
  return Math.round(((today - yesterday) / yesterday) * 100);
}

export function incidentLabel(type) {
  return (type || '').replaceAll('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

// Compact age such as "4m", "2h 5m", "3d".
export function fmtAge(iso, now = Date.now()) {
  if (!iso) return '—';
  const mins = Math.max(0, Math.floor((now - new Date(iso).getTime()) / 60000));
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60);
  if (h < 24) return mins % 60 ? `${h}h ${mins % 60}m` : `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

export function minutesSince(iso, now = Date.now()) {
  return iso ? (now - new Date(iso).getTime()) / 60000 : 0;
}

export function initials(email) {
  if (!email) return '?';
  const local = email.split('@')[0];
  const parts = local.split(/[._-]+/).filter(Boolean);
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : local.slice(0, 2)).toUpperCase();
}
