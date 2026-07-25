import { AlertTriangle, Camera, Car, Gauge, ShieldAlert, Users } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import CameraTile from '../components/CameraTile.jsx';
import KpiCard from '../components/KpiCard.jsx';
import { useLiveAlerts } from '../hooks/useWebSocket.jsx';
import { usePolling } from '../hooks/usePolling.jsx';
import { fmtHour, fmtTime, incidentLabel, SEVERITY_BG, trendDelta } from '../lib/format';

const MAX_LIVE_TILES = 6;

export default function Dashboard() {
  const navigate = useNavigate();
  const { data: overview } = usePolling('/api/overview', 30000);
  const { data: cameras } = usePolling('/api/cameras', 15000);
  const { data: stats } = usePolling('/api/stats/all?hours=24', 60000);
  const { data: counts } = usePolling('/api/counts', 5000);
  const { data: insights } = usePolling('/api/insights', 300000);
  const alerts = useLiveAlerts(20);
  const [expanded, setExpanded] = useState(null);

  // Activity-prioritized grid: cameras with in-frame activity get live tiles
  const sortedCameras = useMemo(() => {
    if (!cameras) return [];
    const activity = (cam) => {
      const c = counts?.[cam.id]?.in_frame || {};
      return Object.values(c).reduce((a, b) => a + b, 0);
    };
    return [...cameras]
      .filter((c) => c.enabled)
      .sort((a, b) => activity(b) - activity(a) || (b.health?.online ? 1 : 0) - (a.health?.online ? 1 : 0));
  }, [cameras, counts]);

  const activeCameras = cameras?.filter((c) => c.health?.online).length ?? 0;
  const t = overview?.today;
  const y = overview?.yesterday;

  const chartData = useMemo(
    () => (stats?.buckets || []).map((b) => ({ hour: fmtHour(b.bucket), footfall: b.footfall })),
    [stats]
  );

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        <KpiCard label="People Today" value={t?.footfall} icon={Users}
          delta={trendDelta(t?.footfall, y?.footfall)} to="/analytics" />
        <KpiCard label="Vehicles" value={t?.vehicles} icon={Car} accent="text-warning"
          delta={trendDelta(t?.vehicles, y?.vehicles)} to="/analytics" />
        <KpiCard label="Active Cameras" value={activeCameras} icon={Camera} accent="text-normal" to="/cameras" />
        <KpiCard label="Incidents" value={overview?.open_incidents} icon={ShieldAlert}
          accent="text-critical" to="/incidents" />
        <KpiCard label="Suspicious Activities" value={overview?.suspicious_today}
          icon={AlertTriangle} accent="text-warning" to="/alerts" />
        <KpiCard label="Avg Occupancy" value={t?.avg_occupancy} icon={Gauge}
          delta={trendDelta(t?.avg_occupancy, y?.avg_occupancy)} to="/analytics" />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="xl:col-span-2 space-y-4">
          <section>
            <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wide mb-2">
              Cameras <span className="text-slate-600 normal-case">· prioritized by activity</span>
            </h2>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              {sortedCameras.slice(0, MAX_LIVE_TILES).map((cam, i) => (
                <div key={cam.id} className={expanded === cam.id ? 'col-span-2 row-span-2' : ''}>
                  <CameraTile
                    camera={cam}
                    live
                    large={expanded === cam.id || i === 0}
                    onClick={() => setExpanded(expanded === cam.id ? null : cam.id)}
                  />
                </div>
              ))}
              {sortedCameras.slice(MAX_LIVE_TILES).map((cam) => (
                <CameraTile key={cam.id} camera={cam} onClick={() => navigate('/cameras')} />
              ))}
              {sortedCameras.length === 0 && (
                <p className="col-span-full text-sm text-slate-500 py-8 text-center">
                  No cameras configured yet. Add one under Cameras.
                </p>
              )}
            </div>
          </section>

          <section className="bg-surface-800 border border-surface-700 rounded-lg p-4">
            <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wide mb-3">
              Hourly Footfall (24h)
            </h2>
            <div className="h-48">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                  <XAxis dataKey="hour" tick={{ fill: '#64748b', fontSize: 11 }} />
                  <YAxis tick={{ fill: '#64748b', fontSize: 11 }} width={32} />
                  <Tooltip
                    contentStyle={{ background: '#161e2e', border: '1px solid #2b3548', borderRadius: 8 }}
                    labelStyle={{ color: '#e2e8f0' }}
                  />
                  <Bar dataKey="footfall" fill="#3b82f6" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>
        </div>

        <div className="space-y-4">
          <section className="bg-surface-800 border border-surface-700 rounded-lg p-4">
            <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wide mb-2">
              Live Alerts
            </h2>
            <div className="space-y-2 max-h-72 overflow-y-auto">
              {alerts.length === 0 && (
                <p className="text-sm text-slate-500 py-4 text-center">No alerts this session</p>
              )}
              {alerts.map((a, i) => (
                <button
                  key={i}
                  onClick={() => navigate('/incidents')}
                  className="w-full text-left p-2 rounded-md bg-surface-900 hover:bg-surface-700 border border-surface-700"
                >
                  <div className="flex items-center justify-between">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded border ${SEVERITY_BG[a.severity] || ''}`}>
                      {incidentLabel(a.incident_type)}
                    </span>
                    <span className="text-[10px] text-slate-500">{fmtTime(a.ts)}</span>
                  </div>
                  <p className="text-xs mt-1 text-slate-300">{a.description}</p>
                  <p className="text-[10px] text-slate-500 mt-0.5">{a.camera_id}</p>
                </button>
              ))}
            </div>
          </section>

          <section className="bg-surface-800 border border-surface-700 rounded-lg p-4">
            <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wide mb-2">
              AI Insights
            </h2>
            {!insights?.available && (
              <p className="text-sm text-slate-500">
                AI insights are disabled — no API key configured on this node.
              </p>
            )}
            {insights?.available && (insights.insights?.length ?? 0) === 0 && (
              <p className="text-sm text-slate-500">No insights generated yet.</p>
            )}
            <div className="space-y-2">
              {(insights?.insights || []).map((ins, i) => (
                <div key={i} className="p-2 rounded-md bg-surface-900 border border-surface-700">
                  <p className="text-xs font-semibold text-info">{ins.title}</p>
                  <p className="text-xs text-slate-400 mt-0.5">{ins.detail}</p>
                </div>
              ))}
            </div>
            {insights?.generated_at && (
              <p className="text-[10px] text-slate-600 mt-2">
                Updated {fmtTime(insights.generated_at)}
              </p>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
