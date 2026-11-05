import { CheckCircle2, ExternalLink, Search, XCircle } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { PageHeader, Segmented } from '../components/ui.jsx';
import { useAuth } from '../hooks/useAuth.jsx';
import { useLiveAlerts } from '../hooks/useWebSocket.jsx';
import { usePolling } from '../hooks/usePolling.jsx';
import { patch } from '../lib/api';
import {
  fmtAge, fmtTime, incidentLabel, SEVERITY_CLASS, SEVERITY_STRIPE, STATUS_LABELS,
} from '../lib/format';

// Alerts are incidents raised by camera rules. This page is a triage inbox:
// live alerts from this session first, then the most recent stored ones.
export default function Alerts() {
  const live = useLiveAlerts(100);
  const { data: recent, refresh } = usePolling('/api/incidents?limit=50', 30000);
  const { data: cameras } = usePolling('/api/cameras', 60000);
  const { hasRole } = useAuth();
  const canManage = hasRole('operator');
  const navigate = useNavigate();
  const [severity, setSeverity] = useState('all');
  const [camera, setCamera] = useState('');
  const [selectedKey, setSelectedKey] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const camName = useMemo(
    () => Object.fromEntries((cameras || []).map((c) => [c.id, c.name])),
    [cameras]
  );

  const rows = useMemo(() => {
    const liveRows = live.map((a, i) => ({ ...a, live: true, key: a.id != null ? `id-${a.id}` : `live-${i}` }));
    const stored = (recent || [])
      .filter((r) => !live.some((a) => String(a.id) === String(r.id)))
      .map((r) => ({ ...r, key: `id-${r.id}` }));
    return [...liveRows, ...stored];
  }, [live, recent]);

  const counts = { all: rows.length, critical: 0, warning: 0, info: 0 };
  rows.forEach((r) => { if (counts[r.severity] != null) counts[r.severity] += 1; });

  const visible = rows.filter((r) =>
    (severity === 'all' || r.severity === severity) && (!camera || r.camera_id === camera));
  const selected = visible.find((r) => r.key === selectedKey) || visible[0] || null;
  const liveVisible = visible.filter((r) => r.live);
  const storedVisible = visible.filter((r) => !r.live);

  const setStatus = async (status, extra = {}) => {
    if (!selected?.id) return;
    setBusy(true);
    setError(null);
    try {
      await patch(`/api/incidents/${selected.id}`, { status, ...extra });
      refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const status = selected && (recent || []).find((r) => String(r.id) === String(selected.id))?.status;

  return (
    <>
      <PageHeader title="AI alerts" subtitle="Triage what your camera rules flagged. Open an incident for anything that needs a response.">
        <span className="flex items-center gap-2 text-[12.5px] px-2.5 py-[5px] rounded-full border border-line bg-panel">
          <span className="dot dot-ring" />Live updates on
        </span>
      </PageHeader>

      <div className="flex flex-wrap items-center gap-2.5">
        <Segmented
          label="Filter by severity" value={severity} onChange={setSeverity}
          options={[
            { value: 'all', label: 'All', count: counts.all },
            { value: 'critical', label: 'Critical', count: counts.critical, dot: 'dot-crit' },
            { value: 'warning', label: 'Warning', count: counts.warning, dot: 'dot-warn' },
            { value: 'info', label: 'Info', count: counts.info, dot: 'dot-info' },
          ]}
        />
        <select value={camera} onChange={(e) => setCamera(e.target.value)} className="input sm:!w-52" aria-label="Filter by camera">
          <option value="">All cameras</option>
          {(cameras || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_440px] gap-4 items-start">
        <section className="panel overflow-hidden" aria-label="Alert list">
          {visible.length === 0 && <p className="text-sm text-muted py-12 text-center">No alerts match. New ones appear here as they happen.</p>}
          <Group title="Live this session" rows={liveVisible} selected={selected} onSelect={setSelectedKey} camName={camName} />
          <Group title="Recent" rows={storedVisible} selected={selected} onSelect={setSelectedKey} camName={camName} />
        </section>

        {selected && (
          <aside className="panel detail-pane" aria-label="Alert detail">
            <div className="p-4 border-b border-line flex flex-col gap-2">
              <div className="flex items-center gap-2">
                <span className={SEVERITY_CLASS[selected.severity]}>{selected.severity}</span>
                {selected.id != null && <span className="font-mono text-xs text-muted">#{selected.id}</span>}
                {status && <span className="tag ml-auto">{STATUS_LABELS[status]}</span>}
              </div>
              <h3 className="text-lg font-semibold">{incidentLabel(selected.incident_type)}</h3>
              <p className="text-[13px] text-ink-2">{selected.description}</p>
            </div>
            <div className="scroll">
              <div className="pane-section">
                <div className="feed aspect-video">
                  {selected.snapshot_url
                    ? <img src={selected.snapshot_url} alt="Alert snapshot" className="w-full h-full object-cover" />
                    : <div className="feed-empty">No snapshot for this alert</div>}
                </div>
              </div>
              <div className="pane-section">
                <dl className="kv">
                  <div><dt>Camera</dt><dd>{camName[selected.camera_id] || selected.camera_id}</dd></div>
                  <div><dt>Time</dt><dd className="font-mono text-[12.5px]">{fmtTime(selected.ts)}</dd></div>
                  <div><dt>Rule</dt><dd className="font-mono text-[12px]">{selected.incident_type}</dd></div>
                  <div><dt>Age</dt><dd className="font-mono">{fmtAge(selected.ts)}</dd></div>
                </dl>
              </div>
              <div className="pane-section !flex-row flex-wrap !gap-2">
                {selected.id != null && (
                  <button className="btn btn-primary" onClick={() => navigate(`/incidents/${selected.id}`)}>
                    <ExternalLink size={15} />Open incident
                  </button>
                )}
                {canManage && selected.id != null && (
                  <>
                    <button className="btn" disabled={busy || status === 'investigating'} onClick={() => setStatus('investigating')}>
                      <CheckCircle2 size={15} />Acknowledge
                    </button>
                    <button className="btn btn-ghost" disabled={busy || status === 'closed'}
                      onClick={() => setStatus('closed', { resolution_notes: 'Closed from alerts as a false alarm.' })}>
                      <XCircle size={15} />Close as false alarm
                    </button>
                  </>
                )}
                <button className="btn btn-ghost" onClick={() => navigate('/investigations')}>
                  <Search size={15} />Search around this time
                </button>
                {error && <p role="alert" className="w-full text-sm text-critical">{error}</p>}
              </div>
            </div>
          </aside>
        )}
      </div>
    </>
  );
}

function Group({ title, rows, selected, onSelect, camName }) {
  if (!rows.length) return null;
  return (
    <>
      <div className="text-[11px] uppercase tracking-[0.1em] text-muted px-4 pt-3.5 pb-1.5">{title}</div>
      {rows.map((a) => (
        <button
          key={a.key}
          onClick={() => onSelect(a.key)}
          aria-current={selected?.key === a.key}
          className={`w-full grid grid-cols-[3px_96px_1fr] sm:grid-cols-[3px_120px_1fr_auto] gap-3.5 items-center py-2.5 pr-4 border-t border-line text-left ${
            selected?.key === a.key ? 'bg-accent/[0.07]' : 'hover:bg-raised'
          }`}
        >
          <span className={`self-stretch ${SEVERITY_STRIPE[a.severity] || 'bg-muted'}`} />
          <span className="feed aspect-video !rounded-[5px]">
            {a.snapshot_url ? <img src={a.snapshot_url} alt="" className="w-full h-full object-cover" /> : <span className="feed-empty !text-[10.5px]">no snapshot</span>}
          </span>
          <span className="min-w-0">
            <span className="flex items-center gap-2 flex-wrap">
              {a.live && <span className="w-[7px] h-[7px] rounded-full bg-accent" aria-label="New" />}
              <span className="font-medium text-[13.5px]">{incidentLabel(a.incident_type)}</span>
              <span className={SEVERITY_CLASS[a.severity]}>{a.severity}</span>
            </span>
            <span className="block text-[12.5px] text-ink-2 mt-0.5 truncate">{a.description}</span>
          </span>
          <span className="hidden sm:block text-right text-xs text-muted">
            <span className="block text-ink-2">{camName[a.camera_id] || a.camera_id}</span>
            <span className="font-mono">{fmtTime(a.ts)}</span>
          </span>
        </button>
      ))}
    </>
  );
}
