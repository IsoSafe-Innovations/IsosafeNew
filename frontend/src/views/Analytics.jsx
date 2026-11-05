import { useMemo, useState } from 'react';
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import KpiCard from '../components/KpiCard.jsx';
import { PageHeader, Panel, Segmented } from '../components/ui.jsx';
import { usePolling } from '../hooks/usePolling.jsx';
import { CHART, CHART_TOOLTIP, fmtHour } from '../lib/format';

const axis = { tick: { fill: CHART.axis, fontSize: 10.5 }, tickLine: false };
const RANGES = [
  { value: 24, label: 'Last 24 h' },
  { value: 168, label: 'Last 7 days' },
  { value: 720, label: 'Last 30 days' },
];

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

  const totals = useMemo(() => chartData.reduce((t, d) => ({
    footfall: t.footfall + (d.footfall || 0),
    vehicles: t.vehicles + (d.vehicles || 0),
    incidents: t.incidents + (d.incidents || 0),
    peakQueue: Math.max(t.peakQueue, d.maxQueue || 0),
  }), { footfall: 0, vehicles: 0, incidents: 0, peakQueue: 0 }), [chartData]);

  const maxHeat = useMemo(() => Math.max(1, ...(heatmap?.grid || []).flat()), [heatmap]);
  const cameraName = (cameras || []).find((c) => c.id === camera)?.name;
  const rangeLabel = RANGES.find((r) => r.value === hours)?.label.toLowerCase();

  return (
    <>
      <PageHeader title="Analytics" subtitle="People, vehicles, queues and occupancy across your cameras" />

      <div className="panel p-2.5 flex flex-wrap items-center gap-2.5">
        <select value={camera} onChange={(e) => setCamera(e.target.value)} className="input sm:!w-56" aria-label="Camera">
          <option value="all">All cameras</option>
          {(cameras || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <Segmented label="Time range" value={hours} onChange={setHours} options={RANGES} />
        <span className="text-[12.5px] text-muted sm:ml-auto">{cameraName || 'All cameras'} · {rangeLabel}</span>
      </div>

      <section className="grid grid-cols-2 lg:grid-cols-4 gap-3" aria-label="Totals">
        <KpiCard label="Footfall" value={totals.footfall} note={`people counted, ${rangeLabel}`} />
        <KpiCard label="Vehicles" value={totals.vehicles} accent="text-warning" note="cars, trucks, buses, motorcycles" />
        <KpiCard label="Peak queue" value={totals.peakQueue} note="longest queue in one bucket" />
        <KpiCard label="Incidents" value={totals.incidents} note="raised by rules" />
      </section>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartPanel empty={!chartData.length} title="Footfall">
          <AreaChart data={chartData}>
            <defs>
              <linearGradient id="fillFoot" x1="0" x2="0" y1="0" y2="1">
                <stop offset="0" stopColor={CHART.accent} stopOpacity={0.25} />
                <stop offset="1" stopColor={CHART.accent} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="2 4" stroke={CHART.grid} vertical={false} />
            <XAxis dataKey="time" {...axis} axisLine={{ stroke: CHART.grid }} minTickGap={24} />
            <YAxis {...axis} axisLine={false} width={36} />
            <Tooltip {...CHART_TOOLTIP} />
            <Area dataKey="footfall" name="People" stroke={CHART.accent} strokeWidth={2} fill="url(#fillFoot)" />
          </AreaChart>
        </ChartPanel>
        <ChartPanel empty={!chartData.length} title="Vehicles">
          <BarChart data={chartData}>
            <CartesianGrid strokeDasharray="2 4" stroke={CHART.grid} vertical={false} />
            <XAxis dataKey="time" {...axis} axisLine={{ stroke: CHART.grid }} minTickGap={24} />
            <YAxis {...axis} axisLine={false} width={36} />
            <Tooltip {...CHART_TOOLTIP} />
            <Bar dataKey="vehicles" name="Vehicles" fill={CHART.warn} radius={[3, 3, 0, 0]} />
          </BarChart>
        </ChartPanel>
        <ChartPanel empty={!chartData.length} title="Queue length" legend={[['Average', CHART.info], ['Max', CHART.crit]]}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="2 4" stroke={CHART.grid} vertical={false} />
            <XAxis dataKey="time" {...axis} axisLine={{ stroke: CHART.grid }} minTickGap={24} />
            <YAxis {...axis} axisLine={false} width={36} />
            <Tooltip {...CHART_TOOLTIP} />
            <Line dataKey="queue" name="Average" stroke={CHART.info} strokeWidth={2} dot={false} />
            <Line dataKey="maxQueue" name="Max" stroke={CHART.crit} strokeWidth={1.5} strokeDasharray="4 4" dot={false} />
          </LineChart>
        </ChartPanel>
        <ChartPanel empty={!chartData.length} title="Occupancy and incidents" legend={[['Avg occupancy', CHART.ok], ['Incidents', CHART.crit]]}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="2 4" stroke={CHART.grid} vertical={false} />
            <XAxis dataKey="time" {...axis} axisLine={{ stroke: CHART.grid }} minTickGap={24} />
            <YAxis {...axis} axisLine={false} width={36} />
            <Tooltip {...CHART_TOOLTIP} />
            <Line dataKey="occupancy" name="Avg occupancy" stroke={CHART.ok} strokeWidth={2} dot={false} />
            <Line dataKey="incidents" name="Incidents" stroke={CHART.crit} strokeWidth={2} dot={false} />
          </LineChart>
        </ChartPanel>
      </div>

      <Panel title={camera === 'all' ? 'Movement heatmap' : `Movement heatmap · ${cameraName}`}
        action={camera !== 'all' && <span className="font-mono text-[11.5px] text-muted">last hour snapshot</span>}>
        {camera === 'all' ? (
          <p className="text-sm text-muted py-6 text-center">Pick a single camera above to see where people move in its view.</p>
        ) : heatmap?.grid ? (
          <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] gap-5 items-center">
            <div className="feed aspect-video grid gap-px p-px" style={{ gridTemplateColumns: `repeat(${heatmap.grid[0]?.length || 32}, 1fr)` }}>
              {heatmap.grid.flatMap((row, y) =>
                row.map((v, x) => (
                  <div key={`${x}-${y}`} style={{ backgroundColor: heatColor(v / maxHeat) }} />
                ))
              )}
            </div>
            <div className="flex flex-col gap-3">
              <p className="text-ink-2 text-[13px]">Warmer cells mean more movement passed through that part of the frame in the last hour.</p>
              <div>
                <div className="h-2 rounded bg-gradient-to-r from-[rgba(14,143,168,.35)] via-[#f5a524] to-[#dc3b36]" />
                <div className="flex justify-between font-mono text-[11.5px] text-muted mt-1"><span>low</span><span>high</span></div>
              </div>
            </div>
          </div>
        ) : (
          <p className="text-sm text-muted py-6 text-center">No heatmap snapshot yet for this camera.</p>
        )}
      </Panel>
    </>
  );
}

function heatColor(r) {
  if (r <= 0) return 'rgba(255,255,255,0.03)';
  if (r < 0.5) return `rgba(245,165,36,${0.2 + r * 1.2})`;
  return `rgba(220,59,54,${Math.min(1, 0.45 + r * 0.55)})`;
}

function ChartPanel({ title, legend, empty, children }) {
  return (
    <Panel
      title={title}
      action={legend && (
        <span className="flex gap-3.5 text-xs text-ink-2">
          {legend.map(([l, c]) => (
            <span key={l} className="flex items-center gap-1.5"><i className="inline-block w-2.5 h-[3px] rounded" style={{ background: c }} />{l}</span>
          ))}
        </span>
      )}
    >
      {empty ? (
        <div className="h-[220px] grid place-items-center text-sm text-muted">No data for this camera and time range yet.</div>
      ) : (
        <ResponsiveContainer width="100%" height={220}>{children}</ResponsiveContainer>
      )}
    </Panel>
  );
}
