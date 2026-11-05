import { X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Field, PageHeader } from '../components/ui.jsx';
import { useAuth } from '../hooks/useAuth.jsx';
import { usePolling } from '../hooks/usePolling.jsx';
import { get, patch } from '../lib/api';
import {
  fmtAge, fmtTime, incidentLabel, initials, minutesSince, SEVERITY_CLASS, SEVERITY_STRIPE, STATUS_LABELS,
} from '../lib/format';

const STATUSES = ['open', 'investigating', 'resolved', 'closed'];
const STATUS_DOT = { open: 'dot-crit', investigating: 'dot-warn', resolved: '', closed: 'dot-off' };
const RESPONSE_TARGET_MIN = 30;

export default function Incidents() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { hasRole } = useAuth();
  const canManage = hasRole('operator');

  const [tab, setTab] = useState('open');
  const [filters, setFilters] = useState({ severity: '', camera: '' });
  const query = useMemo(() => {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([k, v]) => v && params.set(k, v));
    params.set('limit', '200');
    return `/api/incidents?${params}`;
  }, [filters]);

  const { data: incidents, refresh } = usePolling(query, 20000);
  const { data: cameras } = usePolling('/api/cameras', 60000);
  const { data: users } = usePolling('/api/users', 120000, hasRole('admin'));
  const [detail, setDetail] = useState(null);
  const [notes, setNotes] = useState('');
  const [error, setError] = useState(null);

  const camName = useMemo(() => Object.fromEntries((cameras || []).map((c) => [c.id, c.name])), [cameras]);
  const counts = useMemo(() => {
    const c = { all: 0, open: 0, investigating: 0, resolved: 0, closed: 0 };
    (incidents || []).forEach((i) => { c.all += 1; if (c[i.status] != null) c[i.status] += 1; });
    return c;
  }, [incidents]);
  const rows = (incidents || []).filter((i) => tab === 'all' || i.status === tab);

  useEffect(() => {
    if (id) {
      get(`/api/incidents/${id}`).then((d) => { setDetail(d); setNotes(d.resolution_notes || ''); }).catch(() => setDetail(null));
    } else {
      setDetail(null);
    }
  }, [id]);

  const update = async (incidentId, body) => {
    setError(null);
    try {
      const updated = await patch(`/api/incidents/${incidentId}`, body);
      setDetail(updated);
      refresh();
    } catch (e) {
      setError(e.message);
    }
  };

  const isLate = (i) => (i.status === 'open' || i.status === 'investigating')
    && i.severity === 'critical' && minutesSince(i.ts) > RESPONSE_TARGET_MIN;

  return (
    <>
      <PageHeader title="Incidents" subtitle={`Response target: pick up critical incidents within ${RESPONSE_TARGET_MIN} minutes`}>
        <select value={filters.severity} onChange={(e) => setFilters((f) => ({ ...f, severity: e.target.value }))}
          className="input !w-40" aria-label="Filter by severity">
          <option value="">All severities</option>
          {['critical', 'warning', 'info'].map((s) => <option key={s} value={s}>{s[0].toUpperCase() + s.slice(1)}</option>)}
        </select>
        <select value={filters.camera} onChange={(e) => setFilters((f) => ({ ...f, camera: e.target.value }))}
          className="input !w-48" aria-label="Filter by camera">
          <option value="">All cameras</option>
          {(cameras || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </PageHeader>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2.5" role="tablist" aria-label="Incident status">
        {[['all', 'All'], ...STATUSES.map((s) => [s, STATUS_LABELS[s]])].map(([k, l]) => (
          <button
            key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
            className={`text-left px-3.5 py-3 rounded-[10px] border shadow-[var(--shadow)] transition-colors ${
              tab === k ? 'border-accent bg-gradient-to-b from-accent/[0.08] to-panel' : 'border-line bg-panel hover:border-line-strong'
            }`}
          >
            <span className="flex items-center gap-1.5 text-[12.5px] text-ink-2">
              {k !== 'all' && <span className={`dot ${STATUS_DOT[k]}`} />}{l}
            </span>
            <span className="block font-display font-semibold text-2xl tabular-nums">{counts[k]}</span>
          </button>
        ))}
      </div>

      <div className={`grid gap-4 items-start ${detail ? 'xl:grid-cols-[minmax(0,1fr)_420px]' : ''}`}>
        <section className="panel table-wrap">
          <table className="table table-click">
            <thead>
              <tr>
                <th className="!p-0 w-[3px]" aria-label="Severity" />
                <th>ID</th><th>Incident</th><th>Camera</th><th>Opened</th><th>Age</th><th>Assignee</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((inc) => (
                <tr
                  key={inc.id} tabIndex={0}
                  className={String(inc.id) === String(id) ? 'is-selected' : ''}
                  onClick={() => navigate(`/incidents/${inc.id}`)}
                  onKeyDown={(e) => e.key === 'Enter' && navigate(`/incidents/${inc.id}`)}
                >
                  <td className="!p-0"><span className={`block w-[3px] h-[40px] ${SEVERITY_STRIPE[inc.severity] || ''}`} /></td>
                  <td className="font-mono text-muted text-[12px]">#{inc.id}</td>
                  <td>
                    <span className="flex items-center gap-2">
                      <span className={SEVERITY_CLASS[inc.severity]}>{inc.severity}</span>
                      <span className="font-medium">{incidentLabel(inc.incident_type)}</span>
                    </span>
                  </td>
                  <td className="text-ink-2">{camName[inc.camera_id] || inc.camera_id}</td>
                  <td className="font-mono text-muted text-[12px]">{fmtTime(inc.ts)}</td>
                  <td className={`font-mono text-[12px] ${isLate(inc) ? 'text-warning font-medium' : 'text-ink-2'}`}>
                    {inc.status === 'resolved' || inc.status === 'closed' ? '—' : fmtAge(inc.ts)}
                  </td>
                  <td>
                    {inc.assigned_to ? (
                      <span className="inline-flex items-center gap-2"><span className="avatar avatar-sm">{initials(inc.assigned_to)}</span>{inc.assigned_to}</span>
                    ) : <span className="text-muted">Unassigned</span>}
                  </td>
                </tr>
              ))}
              {incidents && rows.length === 0 && (
                <tr><td colSpan={7} className="!py-10 text-center text-muted">No incidents in this view.</td></tr>
              )}
            </tbody>
          </table>
        </section>

        {detail && (
          <aside className="panel detail-pane" aria-label="Incident detail">
            <div className="p-4 border-b border-line flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-2">
                  <span className={SEVERITY_CLASS[detail.severity]}>{detail.severity}</span>
                  <span className="font-mono text-xs text-muted">#{detail.id}</span>
                </span>
                <button onClick={() => navigate('/incidents')} className="icon-btn" aria-label="Close incident"><X size={18} /></button>
              </div>
              <h3 className="text-lg font-semibold">{incidentLabel(detail.incident_type)}</h3>
              <p className="text-[13px] text-ink-2">{detail.description}</p>
              <p className="font-mono text-[11.5px] text-muted">{camName[detail.camera_id] || detail.camera_id} · {fmtTime(detail.ts)}</p>
            </div>
            <div className="scroll">
              {detail.snapshot_url && (
                <div className="pane-section">
                  <div className="feed"><img src={detail.snapshot_url} alt="Incident snapshot" className="w-full" /></div>
                </div>
              )}
              {canManage ? (
                <div className="pane-section">
                  <div className="grid grid-cols-2 gap-2.5">
                    <Field label="Status" htmlFor="inc-status">
                      <select id="inc-status" value={detail.status} onChange={(e) => update(detail.id, { status: e.target.value })} className="input">
                        {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
                      </select>
                    </Field>
                    <Field label="Assignee" htmlFor="inc-assign">
                      <select id="inc-assign" value={detail.assigned_to || ''} onChange={(e) => update(detail.id, { assigned_to: e.target.value })} className="input">
                        <option value="">Unassigned</option>
                        {detail.assigned_to && !(users || []).some((u) => u.email === detail.assigned_to) && (
                          <option value={detail.assigned_to}>{detail.assigned_to}</option>
                        )}
                        {(users || []).map((u) => <option key={u.id} value={u.email}>{u.email}</option>)}
                      </select>
                    </Field>
                  </div>
                  <Field label="Notes" htmlFor="inc-notes">
                    <textarea
                      id="inc-notes" value={notes} rows={3}
                      onChange={(e) => setNotes(e.target.value)}
                      onBlur={() => notes !== (detail.resolution_notes || '') && update(detail.id, { resolution_notes: notes })}
                      className="input" placeholder="What did you find? Notes save when you leave the field."
                    />
                  </Field>
                  {error && <p role="alert" className="text-sm text-critical">{error}</p>}
                </div>
              ) : (
                <div className="pane-section">
                  <dl className="kv">
                    <div><dt>Status</dt><dd>{STATUS_LABELS[detail.status]}</dd></div>
                    <div><dt>Assignee</dt><dd>{detail.assigned_to || 'Unassigned'}</dd></div>
                  </dl>
                  {detail.resolution_notes && <p className="text-[13px] text-ink-2">{detail.resolution_notes}</p>}
                </div>
              )}
              <div className="pane-section">
                <h2 className="section-title">Timeline</h2>
                <ol className="flex flex-col">
                  <TimelineItem tone="crit" title={`Raised by ${incidentLabel(detail.incident_type).toLowerCase()} rule`} when={fmtTime(detail.ts)} />
                  {detail.assigned_to && <TimelineItem tone="accent" title={`Assigned to ${detail.assigned_to}`} />}
                  {detail.resolved_at
                    ? <TimelineItem tone="ok" title={`${STATUS_LABELS[detail.status]}`} when={fmtTime(detail.resolved_at)} last />
                    : <TimelineItem title={`Currently ${STATUS_LABELS[detail.status].toLowerCase()}`} when={`${fmtAge(detail.ts)} since raised`} last />}
                </ol>
              </div>
            </div>
          </aside>
        )}
      </div>
    </>
  );
}

function TimelineItem({ title, when, tone, last = false }) {
  const ring = { crit: 'border-critical', accent: 'border-accent', ok: 'border-normal' }[tone] || 'border-line-strong';
  return (
    <li className={`relative grid grid-cols-[14px_1fr] gap-2.5 ${last ? '' : 'pb-3.5'}`}>
      {!last && <span className="absolute left-[6px] top-[16px] bottom-0 w-px bg-line" />}
      <span className={`w-[13px] h-[13px] rounded-full border-2 bg-panel mt-[3px] ${ring}`} />
      <span>
        <span className="block text-[13px] font-medium">{title}</span>
        {when && <span className="block text-xs text-muted">{when}</span>}
      </span>
    </li>
  );
}
