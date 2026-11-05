import { Search, X } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Field, PageHeader } from '../components/ui.jsx';
import { usePolling } from '../hooks/usePolling.jsx';
import { get } from '../lib/api';
import { fmtTime, incidentLabel, SEVERITY_CLASS } from '../lib/format';

const OBJECT_TYPES = ['person', 'car', 'truck', 'bus', 'motorcycle', 'backpack', 'suitcase'];
const EMPTY = { from: '', to: '', camera: '', type: '', plate: '' };

export default function Investigations() {
  const { data: cameras } = usePolling('/api/cameras', 60000);
  const [filters, setFilters] = useState(EMPTY);
  const [applied, setApplied] = useState(null);
  const [detections, setDetections] = useState(null);
  const [incidents, setIncidents] = useState(null);
  const [cursor, setCursor] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const set = (k) => (e) => setFilters((f) => ({ ...f, [k]: e.target.value }));
  const camName = Object.fromEntries((cameras || []).map((c) => [c.id, c.name]));

  const search = async (nextCursor = null, f = filters) => {
    setBusy(true);
    setError(null);
    try {
      const dp = new URLSearchParams();
      if (f.from) dp.set('from', new Date(f.from).toISOString());
      if (f.to) dp.set('to', new Date(f.to).toISOString());
      if (f.camera) dp.set('camera', f.camera);
      if (f.type) dp.set('type', f.type);
      if (f.plate) dp.set('plate', f.plate);
      dp.set('limit', '50');
      if (nextCursor) dp.set('cursor', nextCursor);
      const dres = await get(`/api/detections?${dp}`);
      setDetections((prev) => (nextCursor ? [...(prev || []), ...dres.items] : dres.items));
      setCursor(dres.next_cursor);

      if (!nextCursor) {
        setApplied(f);
        const ip = new URLSearchParams();
        if (f.from) ip.set('from', new Date(f.from).toISOString());
        if (f.to) ip.set('to', new Date(f.to).toISOString());
        if (f.camera) ip.set('camera', f.camera);
        ip.set('limit', '50');
        setIncidents(await get(`/api/incidents?${ip}`));
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const removeFilter = (key) => {
    const next = { ...filters, [key]: '' };
    setFilters(next);
    search(null, next);
  };

  const chips = applied ? [
    applied.from && ['from', `From ${fmtTime(applied.from)}`],
    applied.to && ['to', `To ${fmtTime(applied.to)}`],
    applied.camera && ['camera', camName[applied.camera] || applied.camera],
    applied.type && ['type', `Object: ${applied.type}`],
    applied.plate && ['plate', `Plate contains ${applied.plate.toUpperCase()}`],
  ].filter(Boolean) : [];

  return (
    <>
      <PageHeader title="Investigations" subtitle="Search every detection and incident by time, camera, object or number plate" />

      <form className="panel" onSubmit={(e) => { e.preventDefault(); search(); }}>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-[repeat(5,minmax(0,1fr))_auto] gap-2.5 items-end p-3.5">
          <Field label="From" htmlFor="q-from">
            <input id="q-from" type="datetime-local" value={filters.from} onChange={set('from')} className="input" />
          </Field>
          <Field label="To" htmlFor="q-to">
            <input id="q-to" type="datetime-local" value={filters.to} onChange={set('to')} className="input" />
          </Field>
          <Field label="Camera" htmlFor="q-cam">
            <select id="q-cam" value={filters.camera} onChange={set('camera')} className="input">
              <option value="">Any camera</option>
              {(cameras || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Field>
          <Field label="Object" htmlFor="q-obj">
            <select id="q-obj" value={filters.type} onChange={set('type')} className="input">
              <option value="">Any object</option>
              {OBJECT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </Field>
          <Field label="Plate contains" htmlFor="q-plate">
            <input id="q-plate" value={filters.plate} onChange={set('plate')} placeholder="ABC123" className="input font-mono uppercase" />
          </Field>
          <button type="submit" disabled={busy} className="btn btn-primary">
            <Search size={15} /> {busy ? 'Searching…' : 'Search'}
          </button>
        </div>
        {chips.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 px-3.5 pb-3.5">
            <span className="text-xs text-muted">Active:</span>
            {chips.map(([key, label]) => (
              <span key={key} className="chip">
                {label}
                <button type="button" onClick={() => removeFilter(key)} aria-label={`Remove filter ${label}`}><X size={12} /></button>
              </span>
            ))}
            <button type="button" className="link !text-xs" onClick={() => { setFilters(EMPTY); search(null, EMPTY); }}>Clear all</button>
          </div>
        )}
      </form>

      {error && <p role="alert" className="alert-banner alert-error">{error}</p>}

      {!detections && !busy && (
        <div className="panel py-12 px-6 text-center">
          <Search size={28} className="mx-auto text-muted" />
          <p className="font-medium mt-2">Set a time range or plate and press Search</p>
          <p className="text-[13px] text-muted mt-1">Leave everything blank to see the latest detections.</p>
        </div>
      )}

      {incidents && incidents.length > 0 && (
        <section className="flex flex-col gap-2.5">
          <h2 className="section-title">Incidents in this window · {incidents.length}</h2>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(190px,1fr))] gap-3">
            {incidents.map((inc) => (
              <Link key={inc.id} to={`/incidents/${inc.id}`} className="panel p-1.5 flex flex-col gap-1.5 hover:border-line-strong">
                <span className="feed aspect-video !rounded-[5px]">
                  {inc.snapshot_url
                    ? <img src={inc.snapshot_url} alt="" className="w-full h-full object-cover" />
                    : <span className="feed-empty !text-xs">no snapshot</span>}
                </span>
                <span className="flex items-center justify-between gap-1.5 px-1 pb-1">
                  <span className={SEVERITY_CLASS[inc.severity]}>{incidentLabel(inc.incident_type)}</span>
                  <span className="font-mono text-[11px] text-muted">{fmtTime(inc.ts)}</span>
                </span>
                <span className="px-1 pb-1 text-[11.5px] text-muted truncate">{camName[inc.camera_id] || inc.camera_id}</span>
              </Link>
            ))}
          </div>
        </section>
      )}

      {detections && (
        <section className="flex flex-col gap-2.5">
          <h2 className="section-title">Detections · {detections.length}{cursor ? '+' : ''}</h2>
          <div className="panel table-wrap">
            <table className="table">
              <thead>
                <tr><th>Time</th><th>Camera</th><th>Object</th><th>Track</th><th>Zones</th><th>Plate</th><th>Confidence</th></tr>
              </thead>
              <tbody>
                {detections.map((d) => (
                  <tr key={d.id}>
                    <td className="font-mono text-[12px]">{fmtTime(d.ts)}</td>
                    <td className="text-ink-2">{camName[d.camera_id] || d.camera_id}</td>
                    <td className="font-medium">{d.object_type}</td>
                    <td className="font-mono text-muted text-[12px]">#{d.track_id}</td>
                    <td className="text-muted">{(d.zone_ids || []).join(', ') || '—'}</td>
                    <td>{d.plate_text ? <span className="plate">{d.plate_text}</span> : <span className="text-muted">—</span>}</td>
                    <td>
                      <span className="inline-flex items-center gap-2 font-mono text-[12px]">
                        <span className="meter !h-1 w-11"><i className="!bg-normal" style={{ width: `${Math.round(d.confidence * 100)}%` }} /></span>
                        {Math.round(d.confidence * 100)}%
                      </span>
                    </td>
                  </tr>
                ))}
                {detections.length === 0 && (
                  <tr><td colSpan={7} className="!py-10 text-center text-muted">No detections match these filters.</td></tr>
                )}
              </tbody>
            </table>
          </div>
          {cursor && (
            <button onClick={() => search(cursor)} disabled={busy} className="btn self-start">
              {busy ? 'Loading…' : 'Load more'}
            </button>
          )}
        </section>
      )}
    </>
  );
}
