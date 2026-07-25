import { useMemo, useState } from 'react';
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { usePolling } from '../hooks/usePolling.jsx';
import { fmtHour } from '../lib/format';

const tooltipStyle = {
  contentStyle: { background: '#161e2e', border: '1px solid #2b3548', borderRadius: 8 },
  labelStyle: { color: '#e2e8f0' },
};

export default function Analytics() {
  const [camera, setCamera] = useState('all');
  const [hours, setHours] = useState(168);
  const { data: cameras } = usePolling('/api/cameras', 60000);
  const { data: stats } = usePolling(`/api/stats/${camera}?hours=${hours}`, 60000);
  const { data: heatmap } = usePolling(camera !== 'all' ? `/api/heatmap/${camera}` : null, 300000, camera !== 'all');

  const buckets = stats?.buckets || [];
  const chartData = useMemo(
    () => buckets.map((b) => ({
      time: hours <= 48 ? fmtHour(b.bucket) : new Date(b.bucket).toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit' }),
      footfall: b.footfall,
      occupancy: Math.round((b.avg_occupancy || 0) * 10) / 10,
      queue: Math.round((b.avg_queue || 0) * 10) / 10,
      maxQueue: b.max_queue,
      incidents: b.incident_count,
      vehicles: Object.values(b.vehicles || {}).reduce((a, v) => a + v, 0),
    })),
    [buckets, hours]
  );

  const maxHeat = useMemo(
    () => Math.max(1, ...(heatmap?.grid || []).flat()),
    [heatmap]
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h1 className="text-lg font-semibold text-white">Analytics</h1>
        <div className="flex gap-2">
          <select value={camera} onChange={(e) => setCamera(e.target.value)}
                  className="bg-surface-800 border border-surface-600 rounded-md px-2 py-1.5 text-sm">
            <option value="all">All cameras</option>
            {(cameras || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <select value={hours} onChange={(e) => setHours(Number(e.target.value))}
                  className="bg-surface-800 border border-surface-600 rounded-md px-2 py-1.5 text-sm">
            <option value={24}>Last 24 hours</option>
            <option value={168}>Last 7 days</option>
            <option value={720}>Last 30 days</option>
          </select>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Panel title="Footfall">
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis dataKey="time" tick={{ fill: '#64748b', fontSize: 10 }} />
              <YAxis tick={{ fill: '#64748b', fontSize: 10 }} width={32} />
              <Tooltip {...tooltipStyle} />
              <Area dataKey="footfall" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.2} />
            </AreaChart>
          </ResponsiveContainer>
        </Panel>

        <Panel title="Vehicles">
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis dataKey="time" tick={{ fill: '#64748b', fontSize: 10 }} />
              <YAxis tick={{ fill: '#64748b', fontSize: 10 }} width={32} />
              <Tooltip {...tooltipStyle} />
              <Bar dataKey="vehicles" fill="#f59e0b" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Panel>

        <Panel title="Queue length (avg / max)">
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis dataKey="time" tick={{ fill: '#64748b', fontSize: 10 }} />
              <YAxis tick={{ fill: '#64748b', fontSize: 10 }} width={32} />
              <Tooltip {...tooltipStyle} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line dataKey="queue" name="avg" stroke="#3b82f6" dot={false} />
              <Line dataKey="maxQueue" name="max" stroke="#ef4444" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </Panel>

        <Panel title="Occupancy & incidents">
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis dataKey="time" tick={{ fill: '#64748b', fontSize: 10 }} />
              <YAxis tick={{ fill: '#64748b', fontSize: 10 }} width={32} />
              <Tooltip {...tooltipStyle} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line dataKey="occupancy" stroke="#22c55e" dot={false} />
              <Line dataKey="incidents" stroke="#ef4444" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </Panel>
      </div>

      {camera !== 'all' && (
        <Panel title="Movement heatmap (last hour snapshot)">
          {heatmap?.grid ? (
            <div className="grid gap-px w-full max-w-xl mx-auto aspect-video"
                 style={{ gridTemplateColumns: 'repeat(32, 1fr)' }}>
              {heatmap.grid.flatMap((row, y) =>
                row.map((v, x) => (
                  <div key={`${x}-${y}`} style={{
                    backgroundColor: v > 0 ? `rgba(239, 68, 68, ${Math.min(1, 0.15 + (v / maxHeat) * 0.85)})` : 'rgba(59, 130, 246, 0.05)',
                  }} />
                ))
              )}
            </div>
          ) : (
            <p className="text-sm text-slate-500 py-6 text-center">No heatmap snapshot yet for this camera.</p>
          )}
        </Panel>
      )}
    </div>
  );
}

function Panel({ title, children }) {
  return (
    <section className="bg-surface-800 border border-surface-700 rounded-lg p-4">
      <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wide mb-3">{title}</h2>
      {children}
    </section>
  );
}
