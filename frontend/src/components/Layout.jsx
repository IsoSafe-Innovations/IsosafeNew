import {
  Bell, Bot, Camera, ChartLine, FileText, LayoutDashboard, LogOut, Menu,
  Search as SearchIcon, Settings, Shield, ShieldAlert, X,
} from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth.jsx';
import { usePolling } from '../hooks/usePolling.jsx';
import { useLiveAlerts } from '../hooks/useWebSocket.jsx';
import { DEMO_MODE, isHiddenInDemo } from '../lib/demo';
import { fmtTime, incidentLabel, SEVERITY_STRIPE } from '../lib/format';

const NAV = [
  {
    group: 'Monitor',
    items: [
      { to: '/', label: 'Dashboard', icon: LayoutDashboard },
      { to: '/cameras', label: 'Cameras', icon: Camera, badge: 'cameras' },
      { to: '/alerts', label: 'AI Alerts', icon: ShieldAlert, badge: 'alerts' },
    ],
  },
  {
    group: 'Respond',
    items: [
      { to: '/incidents', label: 'Incidents', icon: Shield, badge: 'incidents' },
      { to: '/investigations', label: 'Investigations', icon: SearchIcon },
    ],
  },
  {
    group: 'Insight',
    items: [
      { to: '/analytics', label: 'Analytics', icon: ChartLine },
      { to: '/reports', label: 'Reports', icon: FileText },
      { to: '/assistant', label: 'AI Assistant', icon: Bot },
    ],
  },
  {
    group: 'System',
    items: [{ to: '/admin', label: 'Administration', icon: Settings, minRole: 'admin' }],
  },
];

const TITLES = Object.fromEntries(NAV.flatMap((g) => g.items.map((i) => [i.to, i.label])));

function useClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return now;
}

export default function Layout({ children }) {
  const { user, logout, hasRole } = useAuth();
  const alerts = useLiveAlerts(10);
  const { data: overview } = usePolling('/api/overview', 30000);
  const { data: cameras } = usePolling('/api/cameras', 30000);
  const { data: health } = usePolling('/api/health', 30000);
  const [showNotif, setShowNotif] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const now = useClock();
  const notifRef = useRef(null);

  useEffect(() => { setNavOpen(false); setShowNotif(false); }, [location.pathname]);
  useEffect(() => {
    if (!showNotif) return undefined;
    const close = (e) => { if (!notifRef.current?.contains(e.target)) setShowNotif(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [showNotif]);

  const enabledCams = (cameras || []).filter((c) => c.enabled);
  const online = enabledCams.filter((c) => c.health?.online).length;
  const openIncidents = overview?.open_incidents ?? 0;
  const criticalLive = alerts.filter((a) => a.severity === 'critical').length;
  const badges = {
    cameras: cameras ? { text: `${online}/${enabledCams.length}`, tone: 'neutral' } : null,
    alerts: alerts.length ? { text: alerts.length, tone: 'crit' } : null,
    incidents: openIncidents ? { text: openIncidents, tone: 'crit' } : null,
  };
  const agent = health?.agent;
  const section = '/' + (location.pathname.split('/')[1] || '');
  const title = TITLES[section] || 'Iso Safe';
  const systemOk = health?.status === 'ok';

  return (
    <div className="min-h-full lg:grid lg:grid-cols-[232px_minmax(0,1fr)]">
      {navOpen && <div className="fixed inset-0 bg-ink/30 z-40 lg:hidden" onClick={() => setNavOpen(false)} />}
      <aside
        aria-label="Primary"
        className={`fixed lg:sticky top-0 left-0 z-50 h-screen w-[248px] lg:w-auto bg-accent text-white flex flex-col transition-transform lg:translate-x-0 ${
          navOpen ? 'translate-x-0 shadow-2xl' : '-translate-x-full'
        }`}
      >
        <div className="flex items-center gap-3 px-[18px] pt-5 pb-5 border-b border-white/10">
          <img src="/logo-mark-light.png" alt="" className="h-10 w-auto shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="font-display font-bold text-[17px] leading-tight tracking-[0.04em] uppercase">Iso Safe</div>
            <div className="text-[10.5px] text-white/60 tracking-[0.14em] uppercase">Innovations</div>
          </div>
          <button className="icon-btn !text-white/70 hover:!bg-white/10 hover:!text-white lg:hidden" onClick={() => setNavOpen(false)} aria-label="Close navigation">
            <X size={18} />
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto px-2.5 py-4 flex flex-col gap-3.5">
          {NAV.map(({ group, items }) => {
            const visible = items.filter((n) => (!n.minRole || hasRole(n.minRole)) && !isHiddenInDemo(n.to));
            if (!visible.length) return null;
            return (
              <div key={group} className="flex flex-col gap-0.5">
                <div className="text-[10.5px] uppercase tracking-[0.12em] text-white/45 px-2.5 pb-1">{group}</div>
                {visible.map(({ to, label, icon: Icon, badge }) => {
                  const b = badge && badges[badge];
                  return (
                    <NavLink
                      key={to} to={to} end={to === '/'}
                      className={({ isActive }) =>
                        `relative flex items-center gap-2.5 px-2.5 py-[7px] rounded-md text-[13.5px] transition-colors ${
                          isActive
                            ? 'bg-white text-accent font-medium shadow-sm'
                            : 'text-white/75 hover:bg-white/10 hover:text-white'
                        }`
                      }
                    >
                      <Icon size={16} />
                      {label}
                      {b && (
                        <span className={`ml-auto font-mono text-[11px] px-1.5 rounded-full ${
                          b.tone === 'crit' ? 'bg-critical text-white' : 'bg-white/15 text-white'
                        }`}>
                          {b.text}
                        </span>
                      )}
                    </NavLink>
                  );
                })}
              </div>
            );
          })}
        </nav>

        <div className="border-t border-white/10 p-3 flex flex-col gap-3">
          {agent ? (
            <div className="text-xs grid gap-1.5">
              <div className="flex justify-between">
                <span className="flex items-center gap-2"><span className={`dot ${agent.online ? '!bg-[#6ee7a4]' : 'dot-crit'}`} />Edge agent</span>
                <span className="font-mono text-white/60">
                  {agent.agent_version || '—'}{agent.last_seen_ago != null ? ` · ${agent.last_seen_ago}s` : ''}
                </span>
              </div>
              {agent.cpu != null && (
                <>
                  <div className="flex justify-between text-white/60"><span>CPU</span><span className="font-mono">{agent.cpu}%</span></div>
                  <div className="meter !h-1 !bg-white/15"><i className="!bg-white" style={{ width: `${Math.min(100, agent.cpu)}%` }} /></div>
                </>
              )}
            </div>
          ) : (
            <div className="text-xs flex items-center gap-2 text-white/80">
              <span className={`dot ${health ? (systemOk ? '!bg-[#6ee7a4]' : 'dot-crit') : 'dot-off'}`} />
              {health ? (systemOk ? 'All services healthy' : 'Service degraded') : 'Checking services…'}
            </div>
          )}
          <div className="flex items-center gap-2.5">
            <span className="avatar !bg-white/15 !text-white">{(user.email || '?').slice(0, 2)}</span>
            <div className="min-w-0 flex-1">
              <p className="text-[13px] truncate">{user.email}</p>
              <p className="text-[11.5px] text-white/60 capitalize">{user.role}</p>
            </div>
            <button onClick={logout} title="Sign out" aria-label="Sign out" className="icon-btn !text-white/70 hover:!bg-white/10 hover:!text-white">
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>

      <div className="min-w-0 flex flex-col">
        <header className="sticky top-0 z-30 flex items-center gap-3.5 h-14 px-4 lg:px-6 bg-panel/90 backdrop-blur border-b border-line">
          <button className="icon-btn lg:hidden" onClick={() => setNavOpen(true)} aria-label="Open navigation">
            <Menu size={18} />
          </button>
          <img src="/logo-mark-green.png" alt="Iso Safe" className="h-7 w-auto lg:hidden" />
          <div className="text-[13px] text-muted whitespace-nowrap hidden sm:block">
            Iso Safe &nbsp;/&nbsp; <span className="text-ink font-medium">{title}</span>
          </div>
          {!DEMO_MODE && (
            <button
              onClick={() => navigate('/investigations')}
              className="hidden md:flex flex-1 max-w-[420px] items-center gap-2 h-[34px] px-2.5 border border-line rounded-[7px] bg-raised text-muted text-[13px] hover:border-[#b8c3d1]"
            >
              <SearchIcon size={15} /> Search detections, plates, incidents…
            </button>
          )}
          <div className="ml-auto flex items-center gap-3">
            <span className="hidden xl:flex items-center gap-2 text-[12.5px] px-2.5 py-[5px] rounded-full border border-line bg-panel whitespace-nowrap">
              <span className={`dot ${criticalLive ? 'dot-crit' : 'dot-ring'}`} />
              {criticalLive ? `${criticalLive} critical · ` : ''}
              {cameras ? `${online} of ${enabledCams.length} cameras online` : 'Connecting…'}
            </span>
            <span className="hidden sm:block font-mono text-[12.5px] text-ink-2 whitespace-nowrap">
              {now.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })} ·{' '}
              {now.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}
            </span>
            <div className="relative" ref={notifRef}>
              <button
                onClick={() => setShowNotif((v) => !v)}
                className="icon-btn" aria-expanded={showNotif}
                aria-label={alerts.length ? `Notifications, ${alerts.length} new` : 'Notifications'}
              >
                <Bell size={18} />
                {alerts.length > 0 && (
                  <span className="absolute top-1 right-1 min-w-[15px] h-[15px] px-[3px] rounded-full bg-critical text-white text-[9.5px] font-semibold grid place-items-center">
                    {alerts.length}
                  </span>
                )}
              </button>
              {showNotif && (
                <div className="absolute right-0 mt-2 w-80 panel !shadow-xl max-h-96 overflow-y-auto">
                  <div className="flex items-center justify-between px-3.5 py-2.5 border-b border-line">
                    <span className="text-sm font-medium">Live alerts</span>
                    <button className="link" onClick={() => navigate('/alerts')}>Open triage</button>
                  </div>
                  {alerts.length === 0 && <p className="text-sm text-muted p-4">No alerts since you opened Iso Safe.</p>}
                  {alerts.map((a, i) => (
                    <button
                      key={a.id ?? i}
                      onClick={() => navigate(a.id ? `/incidents/${a.id}` : '/alerts')}
                      className="w-full text-left grid grid-cols-[3px_1fr] gap-3 px-3.5 py-2.5 border-b border-line last:border-0 hover:bg-raised"
                    >
                      <span className={`rounded ${SEVERITY_STRIPE[a.severity] || 'bg-muted'}`} />
                      <span className="min-w-0">
                        <span className="flex justify-between gap-2 text-[13px] font-medium">
                          {incidentLabel(a.incident_type)}
                          <span className="font-mono text-[11px] text-muted font-normal">{fmtTime(a.ts)}</span>
                        </span>
                        <span className="block text-xs text-ink-2 truncate">{a.description}</span>
                        <span className="block text-[11px] text-muted">{a.camera_id}</span>
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </header>

        <main className="flex-1 px-4 lg:px-6 pt-[22px] pb-10 w-full max-w-[1640px] flex flex-col gap-[18px]">
          {children}
        </main>
      </div>
    </div>
  );
}
