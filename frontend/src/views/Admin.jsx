import { Camera, Cpu, Database, Plus, Server, Trash2, Upload, Zap } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Field, PageHeader } from '../components/ui.jsx';
import { useAuth } from '../hooks/useAuth.jsx';
import { usePolling } from '../hooks/usePolling.jsx';
import { del, patch, post } from '../lib/api';
import { DEMO_MODE } from '../lib/demo';
import { fmtTime, initials } from '../lib/format';

const ROLES = ['viewer', 'operator', 'admin'];
const ROLE_HELP = {
  viewer: 'sees dashboards and video',
  operator: 'also manages incidents and uploads',
  admin: 'also manages cameras and users',
};

export default function Admin() {
  const { hasRole } = useAuth();
  const [tab, setTab] = useState('health');

  if (!hasRole('admin')) {
    return <p className="panel text-sm text-muted mt-10 p-8 text-center">Administration needs the admin role. Ask an admin to change your role.</p>;
  }

  const tabs = [['health', 'System health'], ['users', 'Users and roles'], ...(!DEMO_MODE ? [['upload', 'Footage upload']] : [])];

  return (
    <>
      <PageHeader title="Administration" subtitle="System health, users and footage" />
      <div className="tabs" role="tablist">
        {tabs.map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>
      {tab === 'health' && <HealthPanel />}
      {tab === 'users' && <UsersPanel />}
      {tab === 'upload' && !DEMO_MODE && <UploadPanel />}
    </>
  );
}

function UsersPanel() {
  const { data: users, refresh } = usePolling('/api/users', 60000);
  const [form, setForm] = useState({ email: '', password: '', role: 'viewer' });
  const [error, setError] = useState(null);

  const create = async (e) => {
    e.preventDefault();
    setError(null);
    try {
      await post('/api/users', form);
      setForm({ email: '', password: '', role: 'viewer' });
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  const changeRole = async (id, role) => {
    await patch(`/api/users/${id}`, { role });
    refresh();
  };

  const remove = async (id, email) => {
    if (!window.confirm(`Delete user ${email}?`)) return;
    await del(`/api/users/${id}`);
    refresh();
  };

  return (
    <>
      <form className="panel" onSubmit={create}>
        <div className="panel-h"><h2 className="section-title">Add a user</h2></div>
        <div className="panel-b grid grid-cols-1 md:grid-cols-[2fr_1.4fr_1fr_auto] gap-2.5 items-end">
          <Field label="Email" htmlFor="u-email">
            <input id="u-email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })}
              placeholder="name@company.com" type="email" className="input" />
          </Field>
          <Field label="Temporary password" htmlFor="u-pass">
            <input id="u-pass" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })}
              placeholder="At least 8 characters" type="password" autoComplete="new-password" className="input" />
          </Field>
          <Field label="Role" htmlFor="u-role">
            <select id="u-role" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} className="input">
              {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </Field>
          <button type="submit" disabled={!form.email || form.password.length < 8} className="btn btn-primary">
            <Plus size={14} /> Add user
          </button>
        </div>
        <div className="px-4 pb-4 flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-muted">
          {ROLES.map((r) => <span key={r}><span className={`role role-${r}`}>{r}</span> {ROLE_HELP[r]}</span>)}
        </div>
        {error && <p role="alert" className="px-4 pb-4 text-sm text-critical">{error}</p>}
      </form>

      <section className="panel table-wrap">
        <table className="table">
          <thead><tr><th>User</th><th>Role</th><th>Created</th><th aria-label="Actions" /></tr></thead>
          <tbody>
            {(users || []).map((u) => (
              <tr key={u.id}>
                <td>
                  <span className="inline-flex items-center gap-2.5"><span className="avatar avatar-sm">{initials(u.email)}</span>{u.email}</span>
                </td>
                <td>
                  <select value={u.role} onChange={(e) => changeRole(u.id, e.target.value)}
                    className="input input-sm !w-28" aria-label={`Role for ${u.email}`}>
                    {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                </td>
                <td className="text-muted">{fmtTime(u.created_at)}</td>
                <td className="text-right">
                  <button onClick={() => remove(u.id, u.email)} className="icon-btn hover:!text-critical" aria-label={`Delete ${u.email}`}>
                    <Trash2 size={15} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}

function UploadPanel() {
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const upload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append('file', file);
      setJob(await post('/api/uploads', fd));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
      e.target.value = '';
    }
  };

  return (
    <section className="panel panel-b flex flex-col gap-4">
      <label className="border-[1.5px] border-dashed border-line-strong rounded-[10px] p-7 flex flex-col items-center gap-2 text-center bg-raised/60 cursor-pointer hover:border-accent">
        <span className="w-[42px] h-[42px] rounded-[10px] grid place-items-center bg-accent/10 text-accent"><Upload size={20} /></span>
        <span className="font-medium">{busy ? 'Uploading…' : 'Choose a video file'}</span>
        <span className="text-[12.5px] text-muted max-w-md">
          MP4, AVI, MOV, MKV or WebM up to 500 MB. It plays on a loop as a camera so you can test rules.
          You can also upload and name videos from the Cameras page.
        </span>
        <input type="file" accept=".mp4,.avi,.mov,.mkv,.webm" onChange={upload} className="sr-only" disabled={busy} />
      </label>
      {error && <p role="alert" className="alert-banner alert-error">{error}</p>}
      {job && (
        <div className="flex items-center justify-between gap-3 px-3 py-2.5 border border-line rounded-lg text-sm">
          <span>Video added as <code className="font-mono">{job.camera_id}</code></span>
          <Link to="/cameras" className="link">Open in Cameras</Link>
        </div>
      )}
    </section>
  );
}

function HealthPanel() {
  const { data: health } = usePolling('/api/health', 15000);
  const { data: cameras } = usePolling('/api/cameras', 15000);
  const agent = health?.agent;
  const cams = cameras || [];
  const online = cams.filter((c) => c.health?.online).length;

  return (
    <>
      <section className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3">
        <HealthCard label="API" icon={Server} ok={health ? health.status === 'ok' : null} />
        <HealthCard label="Database" icon={Database} ok={health ? !!health.database?.ok : null} />
        <HealthCard label="Redis" icon={Zap} ok={health ? !!health.redis?.ok : null} />
        <HealthCard label="Cameras" icon={Camera} ok={cameras ? (online === cams.length ? true : 'warn') : null}
          value={cameras ? `${online} / ${cams.length}` : '—'} note={cameras ? `${cams.length - online} not streaming` : ''} />
        {agent && (
          <HealthCard label="Edge agent" icon={Cpu} ok={!!agent.online}
            value={agent.online ? 'Online' : 'Offline'}
            note={`${agent.agent_version || '—'} · ${agent.last_seen_ago != null ? `seen ${agent.last_seen_ago}s ago` : 'never seen'}`} />
        )}
      </section>

      {agent && (agent.cpu != null || agent.mem != null || agent.disk_free_gb != null) && (
        <section className="panel">
          <div className="panel-h"><h2 className="section-title">Edge agent resources</h2></div>
          <div className="panel-b grid grid-cols-1 sm:grid-cols-3 gap-4 text-[13px]">
            {agent.cpu != null && <Meter label="CPU" value={`${agent.cpu}%`} pct={agent.cpu} />}
            {agent.mem != null && <Meter label="Memory" value={`${agent.mem}%`} pct={agent.mem} />}
            {agent.disk_free_gb != null && (
              <div><div className="flex justify-between"><span>Disk free</span><span className="font-mono">{agent.disk_free_gb} GB</span></div></div>
            )}
          </div>
        </section>
      )}

      <section className="panel table-wrap">
        <div className="panel-h pb-2.5"><h2 className="section-title">Camera streams</h2></div>
        <table className="table">
          <thead>
            <tr><th>Camera</th><th>Status</th><th>FPS</th><th>Reconnects</th><th>Dropped frames</th><th>Last error</th></tr>
          </thead>
          <tbody>
            {cams.map((c) => (
              <tr key={c.id}>
                <td>{c.name}</td>
                <td>
                  <span className="inline-flex items-center gap-2">
                    <span className={`dot ${c.health?.online ? '' : 'dot-crit'}`} />{c.health?.online ? 'Online' : 'Offline'}
                  </span>
                </td>
                <td className="font-mono">{c.health?.fps ?? 0}</td>
                <td className={`font-mono ${(c.health?.reconnect_count ?? 0) > 2 ? 'text-warning' : 'text-muted'}`}>{c.health?.reconnect_count ?? 0}</td>
                <td className="font-mono text-muted">{c.health?.frames_dropped ?? 0}</td>
                <td className="text-muted text-xs max-w-[320px] truncate">{c.health?.error || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}

function HealthCard({ label, icon: Icon, ok, value, note }) {
  const dot = ok === null ? 'dot-off' : ok === true ? 'dot-ring' : ok === 'warn' ? 'dot-warn' : 'dot-crit';
  const text = value ?? (ok === null ? 'Checking…' : ok ? 'Healthy' : 'Down');
  return (
    <div className="panel px-3.5 py-3 flex flex-col gap-1.5">
      <span className="flex items-center justify-between text-[12.5px] text-ink-2">
        <span className="flex items-center gap-2"><Icon size={15} />{label}</span>
        <span className={`dot ${dot}`} />
      </span>
      <span className={`font-display font-semibold text-xl ${ok === false ? 'text-critical' : ''}`}>{text}</span>
      {note && <span className="font-mono text-[11.5px] text-muted">{note}</span>}
    </div>
  );
}

function Meter({ label, value, pct }) {
  return (
    <div>
      <div className="flex justify-between"><span>{label}</span><span className="font-mono">{value}</span></div>
      <div className="meter mt-1.5"><i style={{ width: `${Math.min(100, pct)}%`, background: pct > 85 ? 'var(--crit)' : undefined }} /></div>
    </div>
  );
}
