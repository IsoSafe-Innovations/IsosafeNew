import { useNavigate } from 'react-router-dom';
import { useLiveAlerts } from '../hooks/useWebSocket.jsx';
import { usePolling } from '../hooks/usePolling.jsx';
import { fmtTime, incidentLabel, SEVERITY_BG } from '../lib/format';

export default function Alerts() {
  const live = useLiveAlerts(100);
  const { data: recent } = usePolling('/api/incidents?limit=50', 30000);
  const navigate = useNavigate();

  const rows = [
    ...live.map((a) => ({ ...a, live: true })),
    ...(recent || []).filter((r) => !live.some((a) => String(a.id) === String(r.id))),
  ];

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold text-white">AI Alerts</h1>
      <div className="space-y-2">
        {rows.length === 0 && (
          <p className="text-sm text-slate-500 py-10 text-center">No alerts yet.</p>
        )}
        {rows.map((a, i) => (
          <button
            key={a.id ?? `live-${i}`}
            onClick={() => a.id && navigate(`/incidents/${a.id}`)}
            className="w-full flex items-center gap-4 bg-surface-800 border border-surface-700 hover:border-surface-600 rounded-lg p-3 text-left"
          >
            {a.snapshot_url && (
              <img src={a.snapshot_url} alt="" className="w-24 h-16 object-cover rounded-md border border-surface-700" />
            )}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className={`text-[11px] px-1.5 py-0.5 rounded border ${SEVERITY_BG[a.severity] || ''}`}>
                  {a.severity}
                </span>
                <span className="text-sm font-medium text-white">{incidentLabel(a.incident_type)}</span>
                {a.live && <span className="text-[10px] text-critical font-semibold">● LIVE</span>}
              </div>
              <p className="text-sm text-slate-400 truncate mt-0.5">{a.description}</p>
            </div>
            <div className="text-right shrink-0">
              <p className="text-xs text-slate-400">{a.camera_id}</p>
              <p className="text-xs text-slate-600">{fmtTime(a.ts)}</p>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
