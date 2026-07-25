import { X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth.jsx';
import { usePolling } from '../hooks/usePolling.jsx';
import { get, patch } from '../lib/api';
import { fmtTime, incidentLabel, SEVERITY_BG, STATUS_LABELS } from '../lib/format';

const STATUSES = ['open', 'investigating', 'resolved', 'closed'];

export default function Incidents() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { hasRole } = useAuth();
  const canManage = hasRole('operator');

  const [filters, setFilters] = useState({ status: '', severity: '', camera: '' });
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

  useEffect(() => {
    if (id) {
      get(`/api/incidents/${id}`).then((d) => { setDetail(d); setNotes(d.resolution_notes || ''); }).catch(() => {});
    } else {
      setDetail(null);
    }
  }, [id]);

  const update = async (incidentId, body) => {
    const updated = await patch(`/api/incidents/${incidentId}`, body);
    setDetail(updated);
    refresh();
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h1 className="text-lg font-semibold text-white">Incidents</h1>
        <div className="flex gap-2">
          <select
            value={filters.status}
            onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}
            className="bg-surface-800 border border-surface-600 rounded-md px-2 py-1.5 text-sm"
          >
            <option value="">All statuses</option>
            {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
          </select>
          <select
            value={filters.severity}
            onChange={(e) => setFilters((f) => ({ ...f, severity: e.target.value }))}
            className="bg-surface-800 border border-surface-600 rounded-md px-2 py-1.5 text-sm"
          >
            <option value="">All severities</option>
            {['info', 'warning', 'critical'].map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select
            value={filters.camera}
            onChange={(e) => setFilters((f) => ({ ...f, camera: e.target.value }))}
            className="bg-surface-800 border border-surface-600 rounded-md px-2 py-1.5 text-sm"
          >
            <option value="">All cameras</option>
            {(cameras || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
      </div>

      <div className="bg-surface-800 border border-surface-700 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-slate-500 border-b border-surface-700">
              <th className="p-3">Time</th>
              <th className="p-3">Type</th>
              <th className="p-3">Severity</th>
              <th className="p-3">Camera</th>
              <th className="p-3">Status</th>
              <th className="p-3">Assigned</th>
            </tr>
          </thead>
          <tbody>
            {(incidents || []).map((inc) => (
              <tr
                key={inc.id}
                onClick={() => navigate(`/incidents/${inc.id}`)}
                className="border-b border-surface-700/50 hover:bg-surface-700/40 cursor-pointer"
              >
                <td className="p-3 text-slate-400 whitespace-nowrap">{fmtTime(inc.ts)}</td>
                <td className="p-3 text-white">{incidentLabel(inc.incident_type)}</td>
                <td className="p-3">
                  <span className={`text-[11px] px-1.5 py-0.5 rounded border ${SEVERITY_BG[inc.severity] || ''}`}>
                    {inc.severity}
                  </span>
                </td>
                <td className="p-3 text-slate-400">{inc.camera_id}</td>
                <td className="p-3 text-slate-300">{STATUS_LABELS[inc.status]}</td>
                <td className="p-3 text-slate-400">{inc.assigned_to || '—'}</td>
              </tr>
            ))}
            {(incidents || []).length === 0 && (
              <tr><td colSpan={6} className="p-8 text-center text-slate-500">No incidents match the filters.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {detail && (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4"
             onClick={() => navigate('/incidents')}>
          <div className="bg-surface-800 border border-surface-600 rounded-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto p-5"
               onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <span className={`text-[11px] px-1.5 py-0.5 rounded border ${SEVERITY_BG[detail.severity] || ''}`}>
                    {detail.severity}
                  </span>
                  <h2 className="text-lg font-semibold text-white">
                    #{detail.id} · {incidentLabel(detail.incident_type)}
                  </h2>
                </div>
                <p className="text-sm text-slate-400 mt-1">{detail.description}</p>
                <p className="text-xs text-slate-500 mt-1">
                  {detail.camera_id} · {fmtTime(detail.ts)}
                  {detail.resolved_at && ` · resolved ${fmtTime(detail.resolved_at)}`}
                </p>
              </div>
              <button onClick={() => navigate('/incidents')} className="text-slate-500 hover:text-white">
                <X size={20} />
              </button>
            </div>

            {detail.snapshot_url && (
              <img src={detail.snapshot_url} alt="Incident snapshot"
                   className="mt-4 rounded-lg border border-surface-700 w-full" />
            )}

            {canManage && (
              <div className="mt-4 grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-slate-500 block mb-1">Status</label>
                  <select
                    value={detail.status}
                    onChange={(e) => update(detail.id, { status: e.target.value })}
                    className="w-full bg-surface-900 border border-surface-600 rounded-md px-2 py-1.5 text-sm"
                  >
                    {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
                  </select>
                </div>
                <div>
                  <label className="text-xs text-slate-500 block mb-1">Assign to</label>
                  <select
                    value={detail.assigned_to || ''}
                    onChange={(e) => update(detail.id, { assigned_to: e.target.value })}
                    className="w-full bg-surface-900 border border-surface-600 rounded-md px-2 py-1.5 text-sm"
                  >
                    <option value="">Unassigned</option>
                    {(users || []).map((u) => <option key={u.id} value={u.email}>{u.email}</option>)}
                  </select>
                </div>
                <div className="col-span-2">
                  <label className="text-xs text-slate-500 block mb-1">Notes</label>
                  <textarea
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    onBlur={() => notes !== (detail.resolution_notes || '') && update(detail.id, { resolution_notes: notes })}
                    rows={3}
                    className="w-full bg-surface-900 border border-surface-600 rounded-md px-2 py-1.5 text-sm"
                    placeholder="Investigation notes…"
                  />
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
