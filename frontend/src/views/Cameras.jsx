import { Link2, Plus, RadioTower, Trash2, Upload, X } from 'lucide-react';
import { useMemo, useState } from 'react';
import CameraTile from '../components/CameraTile.jsx';
import UploadCamera from '../components/UploadCamera.jsx';
import ZoneEditor from '../components/ZoneEditor.jsx';
import { Field, Modal, PageHeader, Segmented } from '../components/ui.jsx';
import { useAuth } from '../hooks/useAuth.jsx';
import { usePolling } from '../hooks/usePolling.jsx';
import { del, patch, post } from '../lib/api';
import { incidentLabel, SEVERITY_CLASS } from '../lib/format';

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

const EMPTY_FORM = { name: '', source: '', type: 'rtsp', vertical_profile: '' };

export default function Cameras() {
  const { hasRole } = useAuth();
  const isAdmin = hasRole('admin');
  const canUpload = hasRole('operator');
  const { data: cameras, refresh } = usePolling('/api/cameras', 15000);
  const { data: profiles } = usePolling('/api/cameras/profiles', 600000, isAdmin);
  const [selectedId, setSelectedId] = useState(null);
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [adding, setAdding] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploaded, setUploaded] = useState(null);
  const [discovered, setDiscovered] = useState(null);
  const [discovering, setDiscovering] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [error, setError] = useState(null);
  const [creating, setCreating] = useState(false);

  const all = cameras || [];
  const counts = {
    all: all.length,
    online: all.filter((c) => c.health?.online).length,
    offline: all.filter((c) => !c.health?.online).length,
    upload: all.filter((c) => c.is_upload).length,
  };
  const list = useMemo(() => {
    const q = search.trim().toLowerCase();
    return all.filter((c) => {
      if (filter === 'online' && !c.health?.online) return false;
      if (filter === 'offline' && c.health?.online) return false;
      if (filter === 'upload' && !c.is_upload) return false;
      return !q || c.name.toLowerCase().includes(q) || c.id.toLowerCase().includes(q);
    });
  }, [all, filter, search]);
  const selected = all.find((c) => c.id === selectedId) || null;

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
    if (creating) return;
    setCreating(true);
    setError(null);
    try {
      await post('/api/cameras', { ...form, vertical_profile: form.vertical_profile || null });
      setAdding(false);
      setForm(EMPTY_FORM);
      refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setCreating(false);
    }
  };

  const saveCamera = async (id, body) => {
    setError(null);
    try {
      await patch(`/api/cameras/${id}`, body);
      refresh();
      return true;
    } catch (e) {
      setError(e.message);
      return false;
    }
  };

  const removeCamera = async (id) => {
    if (!window.confirm('Delete this camera and stop its stream?')) return;
    await del(`/api/cameras/${id}`);
    setSelectedId(null);
    refresh();
  };

  const openAdd = (type = 'rtsp') => { setForm({ ...EMPTY_FORM, type }); setError(null); setAdding(true); };

  return (
    <>
      <PageHeader
        title="Cameras"
        subtitle={cameras ? `${counts.all} sources · ${counts.online} streaming${counts.upload ? ` · ${counts.upload} uploaded` : ''}` : 'Loading cameras…'}
      >
        {isAdmin && (
          <button onClick={discover} disabled={discovering} className="btn">
            <RadioTower size={15} /> {discovering ? 'Scanning…' : 'ONVIF discovery'}
          </button>
        )}
        {isAdmin && <button onClick={() => openAdd('youtube')} className="btn"><Link2 size={15} />Add live link</button>}
        {canUpload && <button onClick={() => setUploading(true)} className="btn"><Upload size={15} />Upload video</button>}
        {isAdmin && <button onClick={() => openAdd()} className="btn btn-primary"><Plus size={15} />Add camera</button>}
      </PageHeader>

      {error && !adding && <p role="alert" className="alert-banner alert-error">{error}</p>}
      {uploaded && (
        <p role="status" className="alert-banner alert-success">
          {uploaded.name} was added as a camera. Playback starts shortly and repeats automatically.
        </p>
      )}

      {discovered && (
        <section className="panel">
          <div className="panel-h">
            <h2 className="section-title">Discovered ONVIF devices</h2>
            <button className="icon-btn" onClick={() => setDiscovered(null)} aria-label="Close discovery results"><X size={16} /></button>
          </div>
          <div className="panel-b !pt-2">
            {discovered.length === 0 && <p className="text-sm text-muted">No ONVIF devices found on the local subnet.</p>}
            {discovered.map((d, i) => (
              <div key={i} className="flex items-center justify-between py-2 border-b border-line last:border-0">
                <span className="text-sm font-mono">{d.host}:{d.port}</span>
                <button
                  onClick={() => { setForm({ ...EMPTY_FORM, name: `Camera ${d.host}`, source: d.xaddr }); setAdding(true); }}
                  className="btn btn-sm"
                >
                  Use this device
                </button>
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="flex flex-wrap items-center gap-2.5">
        <Segmented
          label="Filter cameras" value={filter} onChange={setFilter}
          options={[
            { value: 'all', label: 'All', count: counts.all },
            { value: 'online', label: 'Online', count: counts.online },
            { value: 'offline', label: 'Offline', count: counts.offline },
            { value: 'upload', label: 'Uploads', count: counts.upload },
          ]}
        />
        <input
          value={search} onChange={(e) => setSearch(e.target.value)}
          placeholder="Filter by name or ID" aria-label="Filter cameras by name or ID"
          className="input sm:!w-60"
        />
      </div>

      <div className={`grid gap-4 items-start ${selected ? 'xl:grid-cols-[minmax(0,1fr)_420px]' : ''}`}>
        <div className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-3.5">
          {list.map((cam) => (
            <div
              key={cam.id}
              className={`panel p-2 flex flex-col gap-2 transition-colors ${
                cam.id === selectedId ? '!border-accent ring-1 ring-accent' : 'hover:border-line-strong'
              } ${cam.id === uploaded?.camera_id ? 'ring-2 ring-normal' : ''}`}
            >
              <CameraTile camera={cam} live caption={false} />
              <button
                onClick={() => setSelectedId(cam.id === selectedId ? null : cam.id)}
                className="text-left px-1 flex flex-col gap-1.5"
                aria-label={`Show settings for ${cam.name}`}
              >
                <span className="flex justify-between gap-2">
                  <span className="min-w-0">
                    <span className="block text-[13.5px] font-medium truncate">{cam.name}</span>
                    <span className="block font-mono text-[11px] text-muted truncate">{cam.id}</span>
                  </span>
                  <span className="text-xs text-muted whitespace-nowrap">{cam.rules?.length ?? 0} rules</span>
                </span>
                <span className="flex gap-2.5 pt-1.5 border-t border-line font-mono text-[11.5px] text-muted">
                  <HealthLabel cam={cam} />
                  <span>{cam.health?.reconnect_count ?? 0} reconnects</span>
                </span>
                {cam.health?.error && <span className="text-[11.5px] text-warning">{cam.health.error}</span>}
              </button>
            </div>
          ))}
          {cameras && list.length === 0 && (
            <p className="col-span-full text-sm text-muted py-10 text-center">
              {all.length ? 'No cameras match this filter.' : 'No cameras yet. Add a camera, a live link or upload a video to get started.'}
            </p>
          )}
        </div>

        {selected && (
          <aside className="panel detail-pane" aria-label={`${selected.name} settings`}>
            <div className="p-4 border-b border-line flex flex-col gap-1.5">
              <div className="flex items-center justify-between gap-2.5">
                <h3 className="text-[15px] font-semibold truncate">{selected.name}</h3>
                <button className="icon-btn" onClick={() => setSelectedId(null)} aria-label="Close camera settings"><X size={17} /></button>
              </div>
              <span className="flex items-center gap-2 text-[12.5px] text-ink-2">
                <span className={`dot ${selected.health?.online ? 'dot-ring' : 'dot-off'}`} />
                {selected.health?.online ? 'Streaming' : selected.enabled ? 'Not streaming' : 'Disabled'}
                <span className="font-mono text-muted text-[11.5px]">· {selected.type}{selected.is_upload ? ' · upload' : ''}</span>
              </span>
            </div>
            {isAdmin ? (
              <CameraEditor
                key={selected.id}
                camera={selected}
                onSave={(body) => saveCamera(selected.id, body)}
                onDelete={() => removeCamera(selected.id)}
              />
            ) : (
              <div className="scroll"><HealthDetails camera={selected} /></div>
            )}
          </aside>
        )}
      </div>

      {uploading && (
        <Modal title="Upload video as a camera" onClose={() => { if (!uploadBusy) setUploading(false); }} busy={uploadBusy}>
          <UploadCamera onBusyChange={setUploadBusy} onUploaded={(result, name) => {
            setUploaded({ ...result, name });
            setUploading(false);
            refresh();
          }} />
        </Modal>
      )}

      {adding && (
        <Modal title={form.type === 'youtube' ? 'Add live link' : 'Add camera'} onClose={() => { if (!creating) setAdding(false); }} busy={creating}>
          <div className="flex flex-col gap-3.5">
            <Field label="Name" htmlFor="cam-name">
              <input id="cam-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="input" />
            </Field>
            <Field label="Source type" htmlFor="cam-type">
              <select id="cam-type" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })} className="input">
                <option value="rtsp">RTSP stream</option>
                <option value="snapshot_url">HTTP snapshot URL</option>
                <option value="file">Video file (demo loop)</option>
                <option value="youtube">YouTube live link</option>
              </select>
            </Field>
            <Field label="Source URL or path" htmlFor="cam-source">
              <input id="cam-source" value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })}
                placeholder={form.type === 'youtube' ? 'https://www.youtube.com/watch?v=Q71sLS8h9a4' : 'rtsp://user:pass@10.0.0.5:554/stream1'}
                className="input font-mono !text-[12.5px]" />
            </Field>
            {form.type === 'youtube' && (
              <p className="text-xs text-ink-2">
                Paste a public YouTube live video link. Playback starts muted; use the player controls for sound and full screen. Analysis connects separately.
              </p>
            )}
            <Field label="Vertical profile (pre-fills rules)" htmlFor="cam-profile">
              <select id="cam-profile" value={form.vertical_profile} onChange={(e) => setForm({ ...form, vertical_profile: e.target.value })} className="input">
                <option value="">None, configure manually</option>
                {(profiles || []).map((p) => (
                  <option key={p.id} value={p.id}>{p.label} ({p.rule_count} rules)</option>
                ))}
              </select>
            </Field>
            {error && <p role="alert" className="text-sm text-critical">{error}</p>}
            <button onClick={addCamera} disabled={!form.name.trim() || !form.source.trim() || creating} className="btn btn-primary w-full">
              {creating ? 'Creating camera…' : 'Create camera'}
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}

function HealthLabel({ cam }) {
  const h = cam.health;
  if (cam.type === 'youtube') {
    return <span className={h?.online ? 'text-normal' : 'text-warning'}>{h?.online ? `● analysis ${h.fps} fps` : '● analysis connecting'}</span>;
  }
  if (h?.online) return <span className="text-normal">● {h.fps} fps</span>;
  if (cam.is_upload && cam.enabled) return <span className="text-info">● waiting for playback</span>;
  return <span className="text-critical">● offline</span>;
}

function HealthDetails({ camera }) {
  const h = camera.health || {};
  return (
    <div className="pane-section">
      <dl className="kv">
        <div><dt>Status</dt><dd>{h.online ? 'Streaming' : 'Not streaming'}</dd></div>
        <div><dt>Frame rate</dt><dd className="font-mono">{h.fps ?? 0} fps</dd></div>
        <div><dt>Reconnects</dt><dd className="font-mono">{h.reconnect_count ?? 0}</dd></div>
        <div><dt>Dropped frames</dt><dd className="font-mono">{h.frames_dropped ?? 0}</dd></div>
        <div><dt>Rules</dt><dd>{camera.rules?.length ?? 0}</dd></div>
        <div><dt>Zones</dt><dd>{camera.zones?.length ?? 0}</dd></div>
      </dl>
      {h.error && <p className="alert-banner alert-error !text-xs">{h.error}</p>}
    </div>
  );
}

function CameraEditor({ camera, onSave, onDelete }) {
  const [tab, setTab] = useState('zones');
  const [zones, setZones] = useState(camera.zones || []);
  const [rules, setRules] = useState(camera.rules || []);
  const [enabled, setEnabled] = useState(camera.enabled);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const addRule = (template) => {
    const id = `${template.type}-${Date.now().toString(36)}`;
    setRules([...rules, { id, type: template.type, zone_id: null, cooldown_seconds: 120, ...template.fields }]);
  };

  const updateRule = (i, key, value) => {
    const next = [...rules];
    next[i] = { ...next[i], [key]: value };
    setRules(next);
  };

  const save = async () => {
    setSaving(true);
    setSaved(false);
    const ok = await onSave({ zones, rules, enabled });
    setSaving(false);
    setSaved(ok);
  };

  return (
    <>
      <div className="tabs px-4" role="tablist">
        {[['zones', `Zones · ${zones.length}`], ['rules', `Rules · ${rules.length}`], ['health', 'Health']].map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>
      <div className="scroll">
        {tab === 'zones' && (
          <div className="pane-section">
            <ZoneEditor camera={camera} zones={zones} onChange={setZones} />
            <p className="text-xs text-muted">Click to add points, double-click to close a polygon. Lines need two clicks.</p>
          </div>
        )}
        {tab === 'rules' && (
          <div className="pane-section">
            <select
              aria-label="Add a rule from a template"
              onChange={(e) => {
                const t = RULE_TEMPLATES.find((r) => r.type === e.target.value);
                if (t) addRule(t);
                e.target.value = '';
              }}
              defaultValue=""
              className="input"
            >
              <option value="" disabled>+ Add rule from template</option>
              {RULE_TEMPLATES.map((t) => <option key={t.type} value={t.type}>{t.label}</option>)}
            </select>
            {rules.map((rule, i) => (
              <div key={rule.id} className="border border-line rounded-lg p-2.5 bg-raised/60 flex flex-col gap-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[13px] font-medium">{incidentLabel(rule.type)}</span>
                  <span className={SEVERITY_CLASS[rule.severity]}>{rule.severity}</span>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <select value={rule.zone_id || ''} onChange={(e) => updateRule(i, 'zone_id', e.target.value || null)}
                    className="input input-sm" aria-label="Zone">
                    <option value="">Whole frame</option>
                    {zones.map((z) => <option key={z.id} value={z.id}>{z.name || z.id}</option>)}
                  </select>
                  <select value={rule.severity} onChange={(e) => updateRule(i, 'severity', e.target.value)}
                    className="input input-sm" aria-label="Severity">
                    {['info', 'warning', 'critical'].map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
                <div className="flex items-center gap-2 text-xs text-muted">
                  {rule.threshold_seconds != null && (
                    <label className="flex items-center gap-1.5">
                      <input type="number" value={rule.threshold_seconds}
                        onChange={(e) => updateRule(i, 'threshold_seconds', Number(e.target.value))}
                        className="input input-sm !w-16" /> seconds
                    </label>
                  )}
                  {rule.threshold_count != null && (
                    <label className="flex items-center gap-1.5">
                      <input type="number" value={rule.threshold_count}
                        onChange={(e) => updateRule(i, 'threshold_count', Number(e.target.value))}
                        className="input input-sm !w-16" /> objects
                    </label>
                  )}
                  <button onClick={() => setRules(rules.filter((_, j) => j !== i))}
                    className="ml-auto btn btn-ghost btn-sm hover:!text-critical">
                    <Trash2 size={13} /> Remove
                  </button>
                </div>
              </div>
            ))}
            {rules.length === 0 && <p className="text-xs text-muted">No rules. This camera records detections but never alerts.</p>}
          </div>
        )}
        {tab === 'health' && <HealthDetails camera={camera} />}
        <div className="pane-section !flex-row items-center justify-between flex-wrap">
          <label className="flex items-center gap-2.5 text-[13px] cursor-pointer">
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} className="w-4 h-4 accent-accent" />
            Stream enabled
          </label>
          <div className="flex gap-2 items-center">
            {saved && <span className="text-xs text-normal">Saved</span>}
            <button onClick={onDelete} className="btn btn-sm btn-danger"><Trash2 size={13} />Delete</button>
            <button onClick={save} disabled={saving} className="btn btn-sm btn-primary">{saving ? 'Saving…' : 'Save changes'}</button>
          </div>
        </div>
      </div>
    </>
  );
}
