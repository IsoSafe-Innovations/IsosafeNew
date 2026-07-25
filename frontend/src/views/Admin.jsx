import { Plus, Trash2, Upload } from 'lucide-react';
import { useState } from 'react';
import { useAuth } from '../hooks/useAuth.jsx';
import { usePolling } from '../hooks/usePolling.jsx';
import { del, patch, post } from '../lib/api';
import { fmtTime } from '../lib/format';

export default function Admin() {
  const { hasRole } = useAuth();
  if (!hasRole('admin')) {
    return <p className="text-sm text-slate-500 mt-20 text-center">Administration requires the admin role.</p>;
  }
  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold text-white">Administration</h1>
      <UsersPanel />
      <UploadPanel />
      <HealthPanel />
    </div>
  );
}

function UsersPanel() {
  const { data: users, refresh } = usePolling('/api/users', 60000);
  const [form, setForm] = useState({ email: '', password: '', role: 'viewer' });
  const [error, setError] = useState(null);

  const create = async () => {
    setError(null);
    try {
      await post('/api/users', form);
      setForm({ email: '', password: '', role: 'viewer' });
      refresh();
    } catch (e) {
      setError(e.message);
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
    <section className="bg-surface-800 border border-surface-700 rounded-lg p-4">
      <h2 className="text-sm font-semibold text-slate-300 mb-3">Users & Roles</h2>
      {error && <p className="text-sm text-critical mb-2">{error}</p>}
      <div className="flex flex-wrap gap-2 mb-4">
        <input value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })}
               placeholder="email@company.com" type="email"
               className="bg-surface-900 border border-surface-600 rounded-md px-2.5 py-1.5 text-sm flex-1 min-w-48" />
        <input value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })}
               placeholder="password (min 8 chars)" type="password"
               className="bg-surface-900 border border-surface-600 rounded-md px-2.5 py-1.5 text-sm w-52" />
        <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}
                className="bg-surface-900 border border-surface-600 rounded-md px-2 py-1.5 text-sm">
          {['viewer', 'operator', 'admin'].map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <button onClick={create} disabled={!form.email || form.password.length < 8}
                className="flex items-center gap-1 text-sm px-3 py-1.5 rounded-md bg-info hover:bg-info/80 disabled:opacity-40 text-white">
          <Plus size={14} /> Add
        </button>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs uppercase text-slate-500 border-b border-surface-700">
            <th className="p-2">Email</th><th className="p-2">Role</th><th className="p-2">Created</th><th className="p-2" />
          </tr>
        </thead>
        <tbody>
          {(users || []).map((u) => (
            <tr key={u.id} className="border-b border-surface-700/40">
              <td className="p-2 text-slate-300">{u.email}</td>
              <td className="p-2">
                <select value={u.role} onChange={(e) => changeRole(u.id, e.target.value)}
                        className="bg-surface-900 border border-surface-600 rounded px-1.5 py-1 text-xs">
                  {['viewer', 'operator', 'admin'].map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </td>
              <td className="p-2 text-slate-500">{fmtTime(u.created_at)}</td>
              <td className="p-2 text-right">
                <button onClick={() => remove(u.id, u.email)} className="text-slate-500 hover:text-critical">
                  <Trash2 size={14} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
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
    <section className="bg-surface-800 border border-surface-700 rounded-lg p-4">
      <h2 className="text-sm font-semibold text-slate-300 mb-2">Footage Upload</h2>
      <p className="text-xs text-slate-500 mb-3">
        Upload recorded footage (max 500MB) for single-pass analysis. Detections and
        incidents appear under the generated camera id.
      </p>
      <label className="inline-flex items-center gap-2 text-sm px-3 py-2 rounded-md bg-surface-700 hover:bg-surface-600 cursor-pointer">
        <Upload size={15} /> {busy ? 'Uploading…' : 'Choose video file'}
        <input type="file" accept=".mp4,.avi,.mov,.mkv,.webm" onChange={upload} className="hidden" disabled={busy} />
      </label>
      {error && <p className="text-sm text-critical mt-2">{error}</p>}
      {job && (
        <p className="text-sm text-normal mt-2">
          Upload accepted — processing as <code className="text-slate-300">{job.camera_id}</code> (job {job.job_id}).
        </p>
      )}
    </section>
  );
}

function HealthPanel() {
  const { data: health } = usePolling('/api/health', 15000);
  const { data: cameras } = usePolling('/api/cameras', 15000);

  return (
    <section className="bg-surface-800 border border-surface-700 rounded-lg p-4">
      <h2 className="text-sm font-semibold text-slate-300 mb-3">System Health</h2>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <Stat label="API" ok={health?.status === 'ok'} />
        <Stat label="Database" ok={health?.database?.ok} />
        <Stat label="Redis" ok={health?.redis?.ok} />
        <Stat label="Cameras online"
              value={`${(cameras || []).filter((c) => c.health?.online).length}/${(cameras || []).length}`} />
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs uppercase text-slate-500 border-b border-surface-700">
            <th className="p-2">Camera</th><th className="p-2">Status</th><th className="p-2">FPS</th>
            <th className="p-2">Reconnects</th><th className="p-2">Dropped frames</th>
          </tr>
        </thead>
        <tbody>
          {(cameras || []).map((c) => (
            <tr key={c.id} className="border-b border-surface-700/40">
              <td className="p-2 text-slate-300">{c.name}</td>
              <td className="p-2">
                <span className={c.health?.online ? 'text-normal' : 'text-critical'}>
                  {c.health?.online ? 'online' : 'offline'}
                </span>
              </td>
              <td className="p-2 text-slate-400">{c.health?.fps ?? 0}</td>
              <td className="p-2 text-slate-400">{c.health?.reconnect_count ?? 0}</td>
              <td className="p-2 text-slate-400">{c.health?.frames_dropped ?? 0}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function Stat({ label, ok, value }) {
  return (
    <div className="bg-surface-900 border border-surface-700 rounded-md p-3">
      <p className="text-xs text-slate-500">{label}</p>
      {value != null ? (
        <p className="text-lg font-semibold text-white">{value}</p>
      ) : (
        <p className={`text-lg font-semibold ${ok ? 'text-normal' : 'text-critical'}`}>
          {ok ? 'Healthy' : 'Down'}
        </p>
      )}
    </div>
  );
}
