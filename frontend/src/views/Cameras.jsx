import { Plus, RadioTower, X } from 'lucide-react';
import { useState } from 'react';
import CameraTile from '../components/CameraTile.jsx';
import ZoneEditor from '../components/ZoneEditor.jsx';
import { useAuth } from '../hooks/useAuth.jsx';
import { usePolling } from '../hooks/usePolling.jsx';
import { del, patch, post } from '../lib/api';

const RULE_TEMPLATES = [
  { type: 'loitering', label: 'Loitering', fields: { object: 'person', threshold_seconds: 30, severity: 'warning' } },
  { type: 'zone_intrusion', label: 'Zone intrusion', fields: { object: 'person', severity: 'critical' } },
  { type: 'stopped_vehicle', label: 'Stopped vehicle', fields: { threshold_seconds: 10, severity: 'warning' } },
  { type: 'after_hours_activity', label: 'After-hours activity', fields: { object: 'person', severity: 'critical', schedule: { days: [0, 1, 2, 3, 4, 5, 6], hours: '22:00-06:00' } } },
  { type: 'queue_threshold', label: 'Queue threshold', fields: { threshold_count: 5, severity: 'info' } },
  { type: 'crowd_density', label: 'Crowd density', fields: { threshold_count: 15, severity: 'warning' } },
  { type: 'line_crossing', label: 'Line crossing', fields: { object: 'person', severity: 'critical' } },
  { type: 'abandoned_object', label: 'Abandoned object', fields: { threshold_seconds: 60, severity: 'critical' } },
];

export default function Cameras() {
  const { hasRole } = useAuth();
  const isAdmin = hasRole('admin');
  const { data: cameras, refresh } = usePolling('/api/cameras', 15000);
  const { data: profiles } = usePolling('/api/cameras/profiles', 600000, isAdmin);
  const [editing, setEditing] = useState(null);
  const [adding, setAdding] = useState(false);
  const [discovered, setDiscovered] = useState(null);
  const [discovering, setDiscovering] = useState(false);
  const [form, setForm] = useState({ name: '', source: '', type: 'rtsp', vertical_profile: '' });
  const [error, setError] = useState(null);

  const discover = async () => {
    setDiscovering(true);
    try {
      setDiscovered(await post('/api/cameras/discover', {}));
    } catch (e) {
      setError(e.message);
    } finally {
      setDiscovering(false);
    }
  };

  const addCamera = async () => {
    setError(null);
    try {
      await post('/api/cameras', { ...form, vertical_profile: form.vertical_profile || null });
      setAdding(false);
      setForm({ name: '', source: '', type: 'rtsp', vertical_profile: '' });
      refresh();
    } catch (e) {
      setError(e.message);
    }
  };

  const saveCamera = async (id, body) => {
    setError(null);
    try {
      await patch(`/api/cameras/${id}`, body);
      refresh();
    } catch (e) {
      setError(e.message);
    }
  };

  const removeCamera = async (id) => {
    if (!window.confirm('Delete this camera and stop its stream?')) return;
    await del(`/api/cameras/${id}`);
    setEditing(null);
    refresh();
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-white">Cameras</h1>
        {isAdmin && (
          <div className="flex gap-2">
            <button onClick={discover} disabled={discovering}
              className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md bg-surface-700 hover:bg-surface-600 disabled:opacity-50">
              <RadioTower size={15} /> {discovering ? 'Scanning…' : 'ONVIF Discovery'}
            </button>
            <button onClick={() => setAdding(true)}
              className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md bg-info hover:bg-info/80 text-white">
              <Plus size={15} /> Add camera
            </button>
          </div>
        )}
      </div>

      {error && <p className="text-sm text-critical bg-critical/10 border border-critical/30 rounded-md p-2">{error}</p>}

      {discovered && (
        <div className="bg-surface-800 border border-surface-700 rounded-lg p-4">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-sm font-semibold text-slate-300">Discovered ONVIF devices</h2>
            <button onClick={() => setDiscovered(null)}><X size={16} className="text-slate-500" /></button>
          </div>
          {discovered.length === 0 && <p className="text-sm text-slate-500">No ONVIF devices found on the local subnet.</p>}
          {discovered.map((d, i) => (
            <div key={i} className="flex items-center justify-between py-1.5 border-b border-surface-700/50 last:border-0">
              <span className="text-sm text-slate-300">{d.host}:{d.port}</span>
              <button
                onClick={() => { setForm((f) => ({ ...f, name: `Camera ${d.host}`, source: d.xaddr, type: 'rtsp' })); setAdding(true); }}
                className="text-xs px-2 py-1 rounded bg-surface-700 hover:bg-surface-600"
              >
                Use
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3">
        {(cameras || []).map((cam) => (
          <div key={cam.id} className="space-y-1">
            <CameraTile camera={cam} live onClick={() => isAdmin && setEditing(cam)} />
            <div className="flex items-center justify-between px-1">
              <span className={`text-xs ${cam.health?.online ? 'text-normal' : 'text-critical'}`}>
                {cam.health?.online ? `● ${cam.health.fps} fps` : '● offline'}
              </span>
              <span className="text-xs text-slate-600">
                {cam.health?.reconnect_count ?? 0} reconnects · {cam.rules?.length ?? 0} rules
              </span>
            </div>
          </div>
        ))}
      </div>

      {adding && (
        <Modal title="Add camera" onClose={() => setAdding(false)}>
          <div className="space-y-3">
            <Field label="Name">
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="input" />
            </Field>
            <Field label="Source type">
              <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })} className="input">
                <option value="rtsp">RTSP stream</option>
                <option value="snapshot_url">HTTP snapshot URL</option>
                <option value="file">Video file (demo loop)</option>
              </select>
            </Field>
            <Field label="Source URL / path">
              <input value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })}
                     placeholder="rtsp://user:pass@10.0.0.5:554/stream1" className="input" />
            </Field>
            <Field label="Vertical profile (pre-populates rules)">
              <select value={form.vertical_profile} onChange={(e) => setForm({ ...form, vertical_profile: e.target.value })} className="input">
                <option value="">None — configure manually</option>
                {(profiles || []).map((p) => (
                  <option key={p.id} value={p.id}>{p.label} ({p.rule_count} rules)</option>
                ))}
              </select>
            </Field>
            <button onClick={addCamera} disabled={!form.name || !form.source}
                    className="w-full bg-info hover:bg-info/80 disabled:opacity-40 text-white rounded-md py-2 text-sm">
              Create camera
            </button>
          </div>
        </Modal>
      )}

      {editing && (
        <Modal title={`Edit ${editing.name}`} onClose={() => setEditing(null)} wide>
          <CameraEditor
            camera={editing}
            onSave={(body) => saveCamera(editing.id, body)}
            onDelete={() => removeCamera(editing.id)}
          />
        </Modal>
      )}

      <style>{`.input { width: 100%; background: #0f1522; border: 1px solid #2b3548; border-radius: 6px; padding: 6px 10px; font-size: 14px; }`}</style>
    </div>
  );
}

function Modal({ title, children, onClose, wide }) {
  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className={`bg-surface-800 border border-surface-600 rounded-xl w-full max-h-[90vh] overflow-y-auto p-5 ${wide ? 'max-w-3xl' : 'max-w-md'}`}
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold text-white">{title}</h2>
          <button onClick={onClose}><X size={18} className="text-slate-500 hover:text-white" /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div>
      <label className="text-xs text-slate-500 block mb-1">{label}</label>
      {children}
    </div>
  );
}

function CameraEditor({ camera, onSave, onDelete }) {
  const [zones, setZones] = useState(camera.zones || []);
  const [rules, setRules] = useState(camera.rules || []);
  const [enabled, setEnabled] = useState(camera.enabled);

  const addRule = (template) => {
    const id = `${template.type}-${Date.now().toString(36)}`;
    setRules([...rules, { id, type: template.type, zone_id: null, cooldown_seconds: 120, ...template.fields }]);
  };

  const updateRule = (i, key, value) => {
    const next = [...rules];
    next[i] = { ...next[i], [key]: value };
    setRules(next);
  };

  return (
    <div className="space-y-5">
      <section>
        <h3 className="text-sm font-semibold text-slate-300 mb-2">Zones</h3>
        <ZoneEditor camera={camera} zones={zones} onChange={setZones} />
      </section>

      <section>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold text-slate-300">Rules</h3>
          <select
            onChange={(e) => {
              const t = RULE_TEMPLATES.find((r) => r.type === e.target.value);
              if (t) addRule(t);
              e.target.value = '';
            }}
            defaultValue=""
            className="bg-surface-900 border border-surface-600 rounded-md px-2 py-1 text-xs"
          >
            <option value="" disabled>+ Add from template</option>
            {RULE_TEMPLATES.map((t) => <option key={t.type} value={t.type}>{t.label}</option>)}
          </select>
        </div>
        <div className="space-y-2">
          {rules.map((rule, i) => (
            <div key={rule.id} className="bg-surface-900 border border-surface-700 rounded-md p-2 grid grid-cols-2 md:grid-cols-4 gap-2 items-center">
              <span className="text-xs font-medium text-white">{rule.type}</span>
              <select value={rule.zone_id || ''} onChange={(e) => updateRule(i, 'zone_id', e.target.value || null)}
                      className="bg-surface-800 border border-surface-600 rounded px-1.5 py-1 text-xs">
                <option value="">Whole frame</option>
                {zones.map((z) => <option key={z.id} value={z.id}>{z.name || z.id}</option>)}
              </select>
              <select value={rule.severity} onChange={(e) => updateRule(i, 'severity', e.target.value)}
                      className="bg-surface-800 border border-surface-600 rounded px-1.5 py-1 text-xs">
                {['info', 'warning', 'critical'].map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <div className="flex items-center gap-2 justify-end">
                {rule.threshold_seconds != null && (
                  <input type="number" value={rule.threshold_seconds}
                         onChange={(e) => updateRule(i, 'threshold_seconds', Number(e.target.value))}
                         className="w-16 bg-surface-800 border border-surface-600 rounded px-1.5 py-1 text-xs" title="Threshold seconds" />
                )}
                {rule.threshold_count != null && (
                  <input type="number" value={rule.threshold_count}
                         onChange={(e) => updateRule(i, 'threshold_count', Number(e.target.value))}
                         className="w-16 bg-surface-800 border border-surface-600 rounded px-1.5 py-1 text-xs" title="Threshold count" />
                )}
                <button onClick={() => setRules(rules.filter((_, j) => j !== i))}
                        className="text-xs text-slate-500 hover:text-critical">Remove</button>
              </div>
            </div>
          ))}
          {rules.length === 0 && <p className="text-xs text-slate-600">No rules. This camera records detections but never alerts.</p>}
        </div>
      </section>

      <div className="flex items-center justify-between pt-2 border-t border-surface-700">
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          Stream enabled
        </label>
        <div className="flex gap-2">
          <button onClick={onDelete} className="text-sm px-3 py-1.5 rounded-md bg-critical/20 text-critical hover:bg-critical/30">
            Delete
          </button>
          <button onClick={() => onSave({ zones, rules, enabled })}
                  className="text-sm px-4 py-1.5 rounded-md bg-info hover:bg-info/80 text-white">
            Save changes
          </button>
        </div>
      </div>
    </div>
  );
}
