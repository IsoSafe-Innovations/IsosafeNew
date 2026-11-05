import {
  AlertTriangle, Camera, Car, ChevronRight, Gauge, ShieldAlert, Sparkles, Users,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import CameraTile from '../components/CameraTile.jsx';
import KpiCard from '../components/KpiCard.jsx';
import { PageHeader, Panel } from '../components/ui.jsx';
import { useLiveAlerts } from '../hooks/useWebSocket.jsx';
import { usePolling } from '../hooks/usePolling.jsx';
import {
  CHART, CHART_TOOLTIP, fmtHour, fmtTime, incidentLabel, SEVERITY_STRIPE, trendDelta,
} from '../lib/format';

const MAX_LIVE_TILES = 6;
const SEV_VAR = { critical: 'var(--crit)', warning: 'var(--warn)', info: 'var(--info)' };

export default function Dashboard() {
  const navigate = useNavigate();
  const { data: overview } = usePolling('/api/overview', 30000);
  const { data: cameras } = usePolling('/api/cameras', 15000);
  const { data: stats } = usePolling('/api/stats/all?hours=24', 60000);
  const { data: counts } = usePolling('/api/counts', 5000);
  const { data: insights } = usePolling('/api/insights', 300000);
  const { data: recent } = usePolling('/api/incidents?limit=200', 60000);
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

  const enabled = (cameras || []).filter((c) => c.enabled);
  const activeCameras = enabled.filter((c) => c.health?.online).length;
  const offline = enabled.filter((c) => !c.health?.online && !c.is_upload);
  const t = overview?.today;
  const y = overview?.yesterday;

  const chartData = useMemo(
    () => (stats?.buckets || []).map((b) => ({ hour: fmtHour(b.bucket), footfall: b.footfall })),
    [stats]
  );

  // Last 24 h incident mix, for the breakdown bars.
  const byType = useMemo(() => {
    const since = Date.now() - 24 * 3600 * 1000;
    const map = {};
    (recent || []).forEach((i) => {
      if (new Date(i.ts).getTime() < since) return;
      const k = i.incident_type;
      map[k] = map[k] || { n: 0, severity: i.severity };
      map[k].n += 1;
      if (i.severity === 'critical') map[k].severity = 'critical';
    });
    return Object.entries(map).sort((a, b) => b[1].n - a[1].n).slice(0, 6);
  }, [recent]);
  const maxType = Math.max(1, ...byType.map(([, v]) => v.n));

  const criticalOpen = (recent || []).filter((i) => i.severity === 'critical' && i.status === 'open');
  const oldestCritical = criticalOpen.length
    ? criticalOpen.reduce((a, b) => (new Date(a.ts) < new Date(b.ts) ? a : b))
    : null;

  const today = new Date().toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' });

  return (
    <>
      <PageHeader title="Operations overview" subtitle={today}>
        <Link to="/cameras" className="btn"><Camera size={15} />Open video wall</Link>
      </PageHeader>

      <section aria-label="Current situation"
        className="panel !rounded-[10px] overflow-hidden grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-[1.4fr_1fr_1fr_1fr] divide-y sm:divide-y-0 divide-line">
        {criticalOpen.length ? (
          <div className="sm:col-span-2 xl:col-span-1 flex items-center justify-between gap-4 px-[18px] py-3.5 bg-gradient-to-r from-critical/10 to-critical/[0.02]">
            <div>
              <p className="text-[11.5px] uppercase tracking-[0.08em] text-critical font-medium">Needs attention</p>
              <p className="font-display font-semibold text-xl">
                {criticalOpen.length} critical incident{criticalOpen.length === 1 ? '' : 's'} open
              </p>
              {oldestCritical && (
                <p className="text-[12.5px] text-muted">
                  Oldest: {incidentLabel(oldestCritical.incident_type)} · {oldestCritical.camera_id} · {fmtTime(oldestCritical.ts)}
                </p>
              )}
            </div>
            <Link to="/alerts" className="btn btn-danger">Review now <ChevronRight size={15} /></Link>
          </div>
        ) : (
          <div className="sm:col-span-2 xl:col-span-1 flex items-center gap-3 px-[18px] py-3.5 bg-gradient-to-r from-normal/10 to-normal/[0.02]">
            <span className="dot dot-ring" />
            <div>
              <p className="text-[11.5px] uppercase tracking-[0.08em] text-normal font-medium">All clear</p>
              <p className="font-display font-semibold text-xl">No open critical incidents</p>
            </div>
          </div>
        )}
        <Cell label="Open incidents" value={overview?.open_incidents ?? '—'} note="across all cameras" />
        <Cell
          label="Cameras online"
          value={<>{activeCameras} <span className="text-muted text-[15px]">/ {enabled.length}</span></>}
          note={offline.length ? `${offline[0].name}${offline.length > 1 ? ` +${offline.length - 1} more` : ''} offline` : 'All streams healthy'}
          noteClass={offline.length ? 'text-critical' : 'text-muted'}
        />
        <Cell label="Suspicious today" value={overview?.suspicious_today ?? '—'} note="rule-triggered activity" />
      </section>

      <section aria-label="Key figures" className="grid grid-cols-2 md:grid-cols-3 2xl:grid-cols-6 gap-3">
        <KpiCard label="People today" value={t?.footfall} icon={Users}
          delta={trendDelta(t?.footfall, y?.footfall)} to="/analytics" />
        <KpiCard label="Vehicles" value={t?.vehicles} icon={Car} accent="text-warning"
          delta={trendDelta(t?.vehicles, y?.vehicles)} to="/analytics" />
        <KpiCard label="Active cameras" value={activeCameras} icon={Camera} accent="text-normal" to="/cameras"
          note={`${enabled.length - activeCameras} not streaming`} />
        <KpiCard label="Open incidents" value={overview?.open_incidents} icon={ShieldAlert}
          accent="text-critical" to="/incidents" note="needs a response" />
        <KpiCard label="Suspicious activity" value={overview?.suspicious_today}
          icon={AlertTriangle} accent="text-warning" to="/alerts" note="today" />
        <KpiCard label="Avg occupancy" value={t?.avg_occupancy} icon={Gauge}
          delta={trendDelta(t?.avg_occupancy, y?.avg_occupancy)} to="/analytics" />
      </section>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)] gap-4 items-start">
        <div className="flex flex-col gap-4 min-w-0">
          <Panel
            title={<>Live cameras <span className="text-muted normal-case tracking-normal font-normal font-sans">· sorted by activity</span></>}
            action={<Link to="/cameras" className="link">All {enabled.length} cameras <ChevronRight size={14} /></Link>}
          >
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2.5">
              {sortedCameras.slice(0, MAX_LIVE_TILES).map((cam, i) => (
                <div key={cam.id} className={expanded === cam.id || (expanded == null && i === 0) ? 'sm:col-span-2 sm:row-span-2' : ''}>
                  <CameraTile
                    camera={cam}
                    live
                    large={expanded === cam.id || (expanded == null && i === 0)}
                    onClick={() => setExpanded(expanded === cam.id ? null : cam.id)}
                  />
                </div>
              ))}
              {sortedCameras.slice(MAX_LIVE_TILES).map((cam) => (
                <CameraTile key={cam.id} camera={cam} onClick={() => navigate('/cameras')} />
              ))}
              {sortedCameras.length === 0 && (
                <p className="col-span-full text-sm text-muted py-8 text-center">
                  No cameras yet. Add one on the <Link to="/cameras" className="link !text-sm">Cameras</Link> page.
                </p>
              )}
            </div>
          </Panel>

          <Panel title="Footfall by hour · last 24 h">
            <div className="h-52">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData}>
                  <CartesianGrid strokeDasharray="2 4" stroke={CHART.grid} vertical={false} />
                  <XAxis dataKey="hour" tick={{ fill: CHART.axis, fontSize: 11 }} tickLine={false} axisLine={{ stroke: CHART.grid }} />
                  <YAxis tick={{ fill: CHART.axis, fontSize: 11 }} width={36} tickLine={false} axisLine={false} />
                  <Tooltip {...CHART_TOOLTIP} />
                  <Bar dataKey="footfall" name="People" fill={CHART.accent} radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Panel>
        </div>

        <div className="flex flex-col gap-4 min-w-0">
          <Panel
            title="Live alerts"
            action={<Link to="/alerts" className="link">Open triage <ChevronRight size={14} /></Link>}
            bodyClassName="pt-3"
          >
            <div className="max-h-80 overflow-y-auto">
              {alerts.length === 0 && (
                <p className="text-sm text-muted px-4 pb-5 pt-2">No alerts since you opened Iso Safe. New ones appear here instantly.</p>
              )}
              {alerts.map((a, i) => (
                <button
                  key={a.id ?? i}
                  onClick={() => navigate(a.id ? `/incidents/${a.id}` : '/incidents')}
                  className="w-full text-left grid grid-cols-[3px_1fr_auto] gap-3 px-4 py-2.5 border-t border-line hover:bg-raised"
                >
                  <span className={`rounded ${SEVERITY_STRIPE[a.severity] || 'bg-muted'}`} />
                  <span className="min-w-0">
                    <span className="block text-[13.5px] font-medium">{incidentLabel(a.incident_type)}</span>
                    <span className="block text-xs text-muted truncate">{a.camera_id} · {a.description}</span>
                  </span>
                  <time className="font-mono text-[11.5px] text-muted">{fmtTime(a.ts)}</time>
                </button>
              ))}
            </div>
          </Panel>

          <Panel
            title="AI insights"
            action={insights?.generated_at && <span className="font-mono text-[11.5px] text-muted">updated {fmtTime(insights.generated_at)}</span>}
          >
            {!insights?.available && (
              <p className="text-sm text-muted">AI insights are off because no API key is configured on this node.</p>
            )}
            {insights?.available && (insights.insights?.length ?? 0) === 0 && (
              <p className="text-sm text-muted">No insights generated yet.</p>
            )}
            <div className="flex flex-col">
              {(insights?.insights || []).map((ins, i) => (
                <div key={i} className="grid grid-cols-[26px_1fr] gap-2.5 py-2.5 border-t border-line first:border-0 first:pt-0">
                  <span className="w-[26px] h-[26px] rounded-md grid place-items-center bg-accent/10 text-accent"><Sparkles size={14} /></span>
                  <div>
                    <p className="text-[13.5px] font-medium">{ins.title}</p>
                    <p className="text-[12.5px] text-ink-2 mt-0.5">{ins.detail}</p>
                  </div>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Incidents · last 24 h by type">
            {byType.length === 0 && <p className="text-sm text-muted">No incidents in the last 24 hours.</p>}
            <div className="flex flex-col gap-2.5">
              {byType.map(([type, v]) => (
                <div key={type} className="grid grid-cols-[1fr_auto] gap-x-2.5 gap-y-1 text-[12.5px]">
                  <span>{incidentLabel(type)}</span>
                  <span className="font-mono">{v.n}</span>
                  <span className="col-span-2 meter">
                    <i style={{ width: `${(v.n / maxType) * 100}%`, background: SEV_VAR[v.severity] }} />
                  </span>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>
    </>
  );
}

function Cell({ label, value, note, noteClass = 'text-muted' }) {
  return (
    <div className="px-[18px] py-3.5 flex flex-col gap-1 justify-center sm:border-l border-line first:border-0">
      <span className="text-[11.5px] uppercase tracking-[0.08em] text-muted">{label}</span>
      <span className="font-display font-semibold text-xl tabular-nums">{value}</span>
      <span className={`text-xs ${noteClass}`}>{note}</span>
    </div>
  );
}
