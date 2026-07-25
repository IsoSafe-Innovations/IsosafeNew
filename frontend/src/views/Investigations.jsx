import { Search } from 'lucide-react';
import { useState } from 'react';
import { usePolling } from '../hooks/usePolling.jsx';
import { get } from '../lib/api';
import { fmtTime, incidentLabel, SEVERITY_BG } from '../lib/format';

const OBJECT_TYPES = ['person', 'car', 'truck', 'bus', 'motorcycle', 'backpack', 'suitcase'];

export default function Investigations() {
  const { data: cameras } = usePolling('/api/cameras', 60000);
  const [filters, setFilters] = useState({
    from: '', to: '', camera: '', type: '', plate: '', incident_type: '',
  });
  const [detections, setDetections] = useState(null);
  const [incidents, setIncidents] = useState(null);
  const [cursor, setCursor] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const set = (k) => (e) => setFilters((f) => ({ ...f, [k]: e.target.value }));

  const search = async (nextCursor = null) => {
    setBusy(true);
    setError(null);
    try {
      const dp = new URLSearchParams();
      if (filters.from) dp.set('from', new Date(filters.from).toISOString());
      if (filters.to) dp.set('to', new Date(filters.to).toISOString());
      if (filters.camera) dp.set('camera', filters.camera);
      if (filters.type) dp.set('type', filters.type);
      if (filters.plate) dp.set('plate', filters.plate);
      dp.set('limit', '50');
      if (nextCursor) dp.set('cursor', nextCursor);
      const dres = await get(`/api/detections?${dp}`);
      setDetections((prev) => (nextCursor ? [...(prev || []), ...dres.items] : dres.items));
      setCursor(dres.next_cursor);

      if (!nextCursor) {
        const ip = new URLSearchParams();
        if (filters.from) ip.set('from', new Date(filters.from).toISOString());
        if (filters.to) ip.set('to', new Date(filters.to).toISOString());
        if (filters.camera) ip.set('camera', filters.camera);
        if (filters.incident_type) ip.set('incident_type', filters.incident_type);
        ip.set('limit', '50');
        setIncidents(await get(`/api/incidents?${ip}`));
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold text-white">Investigations</h1>

      <div className="bg-surface-800 border border-surface-700 rounded-lg p-4 grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3 items-end">
        <Field label="From">
          <input type="datetime-local" value={filters.from} onChange={set('from')} className="inv-input" />
        </Field>
        <Field label="To">
          <input type="datetime-local" value={filters.to} onChange={set('to')} className="inv-input" />
        </Field>
        <Field label="Camera">
          <select value={filters.camera} onChange={set('camera')} className="inv-input">
            <option value="">Any</option>
            {(cameras || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </Field>
        <Field label="Object type">
          <select value={filters.type} onChange={set('type')} className="inv-input">
            <option value="">Any</option>
            {OBJECT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </Field>
        <Field label="Plate text">
          <input value={filters.plate} onChange={set('plate')} placeholder="ABC123" className="inv-input" />
        </Field>
        <button
          onClick={() => search()}
          disabled={busy}
          className="flex items-center justify-center gap-1.5 bg-info hover:bg-info/80 disabled:opacity-50 text-white rounded-md py-2 text-sm"
        >
          <Search size={15} /> {busy ? 'Searching…' : 'Search'}
        </button>
      </div>

      {error && <p className="text-sm text-critical">{error}</p>}

      {incidents && incidents.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wide mb-2">
            Matching incidents ({incidents.length})
          </h2>
          <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3">
            {incidents.map((inc) => (
              <div key={inc.id} className="bg-surface-800 border border-surface-700 rounded-lg overflow-hidden">
                {inc.snapshot_url ? (
                  <img src={inc.snapshot_url} alt="" className="w-full aspect-video object-cover" />
                ) : (
                  <div className="w-full aspect-video bg-surface-900 flex items-center justify-center text-slate-600 text-xs">no snapshot</div>
                )}
                <div className="p-2">
                  <span className={`text-[10px] px-1.5 py-0.5 rounded border ${SEVERITY_BG[inc.severity] || ''}`}>
                    {incidentLabel(inc.incident_type)}
                  </span>
                  <p className="text-[11px] text-slate-500 mt-1">{inc.camera_id} · {fmtTime(inc.ts)}</p>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {detections && (
        <section>
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wide mb-2">
            Detections ({detections.length}{cursor ? '+' : ''})
          </h2>
          <div className="bg-surface-800 border border-surface-700 rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase text-slate-500 border-b border-surface-700">
                  <th className="p-2.5">Time</th>
                  <th className="p-2.5">Camera</th>
                  <th className="p-2.5">Object</th>
                  <th className="p-2.5">Track</th>
                  <th className="p-2.5">Zones</th>
                  <th className="p-2.5">Plate</th>
                  <th className="p-2.5">Conf</th>
                </tr>
              </thead>
              <tbody>
                {detections.map((d) => (
                  <tr key={d.id} className="border-b border-surface-700/40">
                    <td className="p-2.5 text-slate-400 whitespace-nowrap">{fmtTime(d.ts)}</td>
                    <td className="p-2.5 text-slate-300">{d.camera_id}</td>
                    <td className="p-2.5 text-white">{d.object_type}</td>
                    <td className="p-2.5 text-slate-500">#{d.track_id}</td>
                    <td className="p-2.5 text-slate-500">{(d.zone_ids || []).join(', ') || '—'}</td>
                    <td className="p-2.5 font-mono text-warning">{d.plate_text || '—'}</td>
                    <td className="p-2.5 text-slate-500">{Math.round(d.confidence * 100)}%</td>
                  </tr>
                ))}
                {detections.length === 0 && (
                  <tr><td colSpan={7} className="p-6 text-center text-slate-500">No detections match.</td></tr>
                )}
              </tbody>
            </table>
          </div>
          {cursor && (
            <button onClick={() => search(cursor)} disabled={busy}
                    className="mt-2 text-sm px-4 py-1.5 rounded-md bg-surface-700 hover:bg-surface-600 disabled:opacity-50">
              Load more
            </button>
          )}
        </section>
      )}

      <style>{`.inv-input { width: 100%; background: #0f1522; border: 1px solid #2b3548; border-radius: 6px; padding: 6px 8px; font-size: 13px; color-scheme: dark; }`}</style>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div>
      <label className="text-xs text-slate-500 block mb-1">{label}</label>
      {children}
    </div>
  );
}
