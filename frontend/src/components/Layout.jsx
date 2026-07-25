import {
  Bell, Bot, Camera, ChartLine, FileText, LayoutDashboard, LogOut,
  Search as SearchIcon, Settings, Shield, ShieldAlert, SlidersHorizontal,
} from 'lucide-react';
import { useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth.jsx';
import { useLiveAlerts } from '../hooks/useWebSocket.jsx';
import { SEVERITY_BG } from '../lib/format';

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/cameras', label: 'Cameras', icon: Camera },
  { to: '/alerts', label: 'AI Alerts', icon: ShieldAlert },
  { to: '/incidents', label: 'Incidents', icon: Shield },
  { to: '/analytics', label: 'Analytics', icon: ChartLine },
  { to: '/reports', label: 'Reports', icon: FileText },
  { to: '/investigations', label: 'Investigations', icon: SearchIcon },
  { to: '/assistant', label: 'AI Assistant', icon: Bot },
  { to: '/admin', label: 'Administration', icon: Settings, minRole: 'admin' },
];

export default function Layout({ children }) {
  const { user, logout, hasRole } = useAuth();
  const alerts = useLiveAlerts(10);
  const [showNotif, setShowNotif] = useState(false);
  const navigate = useNavigate();

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-surface-700 bg-surface-900 sticky top-0 z-40">
        <div className="flex items-center gap-1 px-4 h-14">
          <div className="flex items-center gap-2 pr-6">
            <Shield className="text-info" size={22} />
            <span className="font-bold text-lg tracking-tight text-white">Iso&nbsp;Safe</span>
          </div>

          <nav className="flex items-center gap-1 overflow-x-auto flex-1">
            {NAV.filter((n) => !n.minRole || hasRole(n.minRole)).map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                className={({ isActive }) =>
                  `flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm whitespace-nowrap transition-colors ${
                    isActive
                      ? 'bg-surface-700 text-white'
                      : 'text-slate-400 hover:text-white hover:bg-surface-800'
                  }`
                }
              >
                <Icon size={15} />
                {label}
              </NavLink>
            ))}
          </nav>

          <div className="flex items-center gap-3 pl-4">
            <button
              onClick={() => navigate('/investigations')}
              title="Forensic search"
              className="text-slate-400 hover:text-white"
            >
              <SlidersHorizontal size={18} />
            </button>
            <div className="relative">
              <button
                onClick={() => setShowNotif((v) => !v)}
                className="text-slate-400 hover:text-white relative"
                title="Notifications"
              >
                <Bell size={18} />
                {alerts.length > 0 && (
                  <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-critical" />
                )}
              </button>
              {showNotif && (
                <div className="absolute right-0 mt-2 w-80 bg-surface-800 border border-surface-600 rounded-lg shadow-xl p-2 max-h-96 overflow-y-auto">
                  {alerts.length === 0 && (
                    <p className="text-sm text-slate-500 p-3">No recent alerts</p>
                  )}
                  {alerts.map((a, i) => (
                    <button
                      key={i}
                      onClick={() => { setShowNotif(false); navigate('/incidents'); }}
                      className="w-full text-left p-2 rounded hover:bg-surface-700"
                    >
                      <span className={`text-xs px-1.5 py-0.5 rounded border ${SEVERITY_BG[a.severity] || ''}`}>
                        {a.severity}
                      </span>
                      <p className="text-sm mt-1">{a.description}</p>
                      <p className="text-xs text-slate-500">{a.camera_id}</p>
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div className="flex items-center gap-2 border-l border-surface-700 pl-3">
              <div className="text-right">
                <p className="text-sm text-white leading-tight">{user.email}</p>
                <p className="text-xs text-slate-500 capitalize leading-tight">{user.role}</p>
              </div>
              <button onClick={logout} title="Sign out" className="text-slate-400 hover:text-critical">
                <LogOut size={17} />
              </button>
            </div>
          </div>
        </div>
      </header>

      <main className="flex-1 p-4 max-w-[1800px] w-full mx-auto">{children}</main>
    </div>
  );
}
