export const SEVERITY_COLORS = {
  normal: 'text-normal',
  info: 'text-info',
  warning: 'text-warning',
  critical: 'text-critical',
};

export const SEVERITY_BG = {
  info: 'bg-info/15 text-info border-info/30',
  warning: 'bg-warning/15 text-warning border-warning/30',
  critical: 'bg-critical/15 text-critical border-critical/30',
};

export const SEVERITY_BORDER = {
  info: 'border-info',
  warning: 'border-warning',
  critical: 'border-critical',
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
