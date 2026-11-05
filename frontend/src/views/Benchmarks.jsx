import { useEffect, useRef, useState } from 'react';
import { PageHeader } from '../components/ui.jsx';
import { useAuth } from '../hooks/useAuth.jsx';
import { usePolling } from '../hooks/usePolling.jsx';

const CLASSES = ['person','car','motorcycle','bus','truck','backpack','suitcase'];
const basename = (path) => path.replaceAll('\\','/').split('/').pop();

export default function Benchmarks() {
  const { hasRole } = useAuth();
  const [images, setImages] = useState([]);
  const [dataset, setDataset] = useState({ version:1, classes:['person'], frames:[] });
  const [index, setIndex] = useState(0);
  const [objectType, setObjectType] = useState('person');
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);
  const [draft, setDraft] = useState(null);
  const [eventRule, setEventRule] = useState('');
  const { data:cameras } = usePolling('/api/cameras',60000,hasRole('admin'));
  const start = useRef(null);
  const urls = useRef([]);
  useEffect(() => () => urls.current.forEach((url) => URL.revokeObjectURL(url)), []);
  if (!hasRole('admin')) return <p className="panel p-6">Accuracy checks require the admin role.</p>;

  const current = images[index];
  const frame = dataset.frames.find((f) => basename(f.image) === current?.name);
  const update = (changes) => setDataset((d) => ({ ...d, frames:d.frames.map((f) => f.image === frame.image ? { ...f, ...changes } : f) }));
  const addImages = (event) => {
    const files = Array.from(event.target.files || []);
    if (new Set(files.map((file) => file.name)).size !== files.length) { setError('Frame filenames must be unique.'); return; }
    urls.current.forEach((url) => URL.revokeObjectURL(url));
    urls.current = files.map((file) => URL.createObjectURL(file));
    setImages(files.map((file,i) => ({ name:file.name, url:urls.current[i] })));
    setDataset((d) => ({ ...d, frames:files.map((file) => d.frames.find((f) => basename(f.image)===file.name) || {
      image:`images/${file.name}`, sequence:file.name, scenario:'other', timestamp:1, split:'development', reviewed:false, labels:[],
    }) }));
    setIndex(0); setError(null);
  };
  const readJson = async (event, kind) => {
    try {
      const data = JSON.parse(await event.target.files[0].text());
      if (kind==='report') {
        if (!data.profiles) throw new Error('Choose a benchmark report.json.');
        setReport(data);
      } else {
        if (!Array.isArray(data.classes) || !Array.isArray(data.frames) || data.frames.some((f) => !Array.isArray(f.labels) || !f.image || f.labels.some((b) => !Array.isArray(b.bbox) || b.bbox.length!==4 || b.bbox.some((x) => !Number.isFinite(x) || x<0 || x>1)))) throw new Error('Choose a dataset with valid classes, frames and normalized labels.');
        setDataset(data);
      }
      setError(null);
    } catch (err) { setError(err.message); }
  };
  const coords = (event) => {
    const rect=event.currentTarget.getBoundingClientRect();
    return [Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height))];
  };
  const exportLabels = () => {
    const blob = new Blob([JSON.stringify(dataset,null,2)],{type:'application/json'});
    const url=URL.createObjectURL(blob);
    const link=document.createElement('a'); link.href=url; link.download='dataset.json'; link.click();
    URL.revokeObjectURL(url);
  };
  const boxPath = (bbox) => ({ x:100*bbox[0], y:100*bbox[1], width:100*(bbox[2]-bbox[0]), height:100*(bbox[3]-bbox[1]) });
  return <div className="space-y-5">
    <PageHeader title="Accuracy checks" subtitle="Label reference frames and compare detector results. Footage stays in your browser." />
    <div className="panel p-4 space-y-3">
      <p className="text-sm text-ink-2">Draw boxes around every object in the evaluated classes. Mark a frame reviewed only when labeling is complete; an empty reviewed frame means no objects. Keep frames from one video in the same sequence and split. Predictions are never ground truth.</p>
      <div className="flex flex-wrap gap-4 text-sm">
        <label>Reference images<input aria-label="Reference images" type="file" accept="image/*" multiple onChange={addImages} className="block mt-1" /></label>
        <label>Import labels<input aria-label="Import labels" type="file" accept=".json" onChange={(e) => readJson(e,'dataset')} className="block mt-1" /></label>
        <label>Import comparison report<input aria-label="Import comparison report" type="file" accept=".json" onChange={(e) => readJson(e,'report')} className="block mt-1" /></label>
      </div>
      {error && <p role="alert" className="text-critical">{error}</p>}
      <div className="flex flex-wrap gap-3 text-sm">Evaluate classes: {CLASSES.map((name) => <label key={name} className="flex gap-1 items-center"><input type="checkbox" checked={dataset.classes.includes(name)} onChange={(e) => setDataset((d) => ({ ...d, classes:e.target.checked ? [...d.classes,name] : d.classes.filter((c) => c!==name) }))} />{name}</label>)}</div>
      <button className="btn btn-primary" disabled={!dataset.frames.length || !dataset.classes.length} onClick={exportLabels}>Export reviewed labels</button>
      <label className="block text-sm">Reference alert rules
        <select aria-label="Use camera rules for event benchmark" className="input" value="" onChange={(e) => { const camera=cameras?.find((c) => c.id===e.target.value); if (camera) { setDataset((d) => ({ ...d,zones:camera.zones,rules:camera.rules })); setEventRule(''); } }}>
          <option value="">Copy rules from a camera for offline evaluation…</option>{(cameras || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </label>
      <p className="text-xs text-muted">Export includes labels and review status, not images. Keep original files under images/ beside dataset.json. The backend benchmark command evaluates only reviewed frames in the chosen split.</p>
    </div>
    {current && frame && <div className="panel p-4 space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <button className="btn" disabled={!index} onClick={() => { setIndex(index-1); setDraft(null); }}>Previous</button>
        <span>{index+1}/{images.length} · {current.name}</span>
        <button className="btn" disabled={index===images.length-1} onClick={() => { setIndex(index+1); setDraft(null); }}>Next</button>
        <label>New box class<select className="input" value={objectType} onChange={(e) => setObjectType(e.target.value)}>{CLASSES.map((c) => <option key={c}>{c}</option>)}</select></label>
      </div>
      <div className="relative select-none" style={{touchAction:'none'}}>
        <img src={current.url} alt={`Reference frame ${current.name}`} className="w-full h-auto block" />
        <svg role="img" aria-label="Draw reference bounding boxes" viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 w-full h-full cursor-crosshair"
          onPointerDown={(e) => { start.current=coords(e); e.currentTarget.setPointerCapture(e.pointerId); }}
          onPointerMove={(e) => { if (start.current) { const p=coords(e),s=start.current; setDraft([Math.min(s[0],p[0]),Math.min(s[1],p[1]),Math.max(s[0],p[0]),Math.max(s[1],p[1])]); } }}
          onPointerCancel={() => { start.current=null; setDraft(null); }}
          onPointerUp={(e) => { if (!start.current) return; const p=coords(e),s=start.current; start.current=null; setDraft(null); const box=[Math.min(s[0],p[0]),Math.min(s[1],p[1]),Math.max(s[0],p[0]),Math.max(s[1],p[1])]; if (box[2]-box[0]>.002 && box[3]-box[1]>.002) update({ reviewed:false, labels:[...frame.labels,{ object_type:objectType,bbox:box }] }); }}>
          {frame.labels.map((label,i) => <g key={i}><rect {...boxPath(label.bbox)} fill="none" stroke="#00ff88" strokeWidth=".25" /><text x={label.bbox[0]*100} y={Math.max(2,label.bbox[1]*100-1)} fontSize="2" fill="#00ff88">{i+1}: {label.object_type}</text></g>)}
          {draft && <rect {...boxPath(draft)} fill="none" stroke="#ffcc00" strokeWidth=".25" />}
        </svg>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
        <label>Scenario<select className="input" value={frame.scenario} onChange={(e) => update({ scenario:e.target.value })}>{['day','night','crowded','blurred','other'].map((s) => <option key={s}>{s}</option>)}</select></label>
        <label>Sequence/video ID<input className="input" value={frame.sequence || ''} onChange={(e) => update({ sequence:e.target.value })} /></label>
        <label>Time in sequence (s)<input type="number" min="0" step=".01" className="input" value={frame.timestamp ?? 1} onChange={(e) => update({ timestamp:Number(e.target.value) })} /></label>
        <label>Split<select className="input" value={frame.split || 'development'} onChange={(e) => update({ split:e.target.value })}><option>development</option><option>test</option></select></label>
      </div>
      {frame.labels.map((label,i) => <div key={i} className="flex flex-wrap gap-2 items-end border-t border-line pt-2 text-xs">
        <span>Box {i+1}: {label.object_type}</span>
        {label.bbox.map((v,k) => <label key={k}>{['Left','Top','Right','Bottom'][k]} %<input aria-label={`Box ${i+1} ${['left','top','right','bottom'][k]}`} type="number" min="0" max="100" step=".1" className="input !w-20" value={Math.round(v*1000)/10} onChange={(e) => update({ reviewed:false,labels:frame.labels.map((b,j) => j===i ? { ...b,bbox:b.bbox.map((x,n) => n===k ? Number(e.target.value)/100 : x) } : b) })} /></label>)}
        <label>Track ID (optional)<input className="input !w-24" value={label.track_id || ''} onChange={(e) => update({ reviewed:false, labels:frame.labels.map((b,j) => j===i ? { ...b,track_id:e.target.value || undefined } : b) })} /></label>
        <button className="btn btn-sm" onClick={() => update({reviewed:false,labels:frame.labels.filter((_,j) => i!==j)})}>Delete box</button>
      </div>)}
      <button className="btn" onClick={() => update({ reviewed:false, labels:[...frame.labels,{object_type:objectType,bbox:[.1,.1,.3,.4]}] })}>Add box with coordinates</button>
      <label className="flex gap-2 text-sm"><input type="checkbox" checked={frame.reviewed || false} onChange={(e) => update({ reviewed:e.target.checked })} />I reviewed every evaluated object in this frame</label>
      {(dataset.rules || []).length>0 && <div className="space-y-2 border-t border-line pt-3">
        <p className="text-sm">Expected alert at this point in the recording</p>
        <select aria-label="Expected alert rule" className="input" value={eventRule} onChange={(e) => setEventRule(e.target.value)}><option value="">Choose a rule…</option>{dataset.rules.map((r) => <option key={r.id} value={r.id}>{r.id} · {r.type}</option>)}</select>
        <button className="btn" disabled={!eventRule} onClick={() => { const rule=dataset.rules.find((r) => r.id===eventRule); setDataset((d) => ({ ...d,events:[...(d.events || []),{ sequence:frame.sequence,timestamp:frame.timestamp,type:rule.type,rule_id:rule.id }] })); }}>Label expected alert</button>
        {(dataset.events || []).map((event,i) => <p className="text-xs" key={i}>{event.sequence} · {event.timestamp}s · {event.type} <button className="link" onClick={() => setDataset((d) => ({ ...d,events:d.events.filter((_,j) => i!==j) }))}>Remove event</button></p>)}
      </div>}
    </div>}
    {report && <div className="panel p-4 overflow-x-auto space-y-3">
      <h2 className="text-base font-semibold">Detector comparison · {report.frames} reviewed frames · {report.split}</h2>
      <table className="w-full text-sm"><thead><tr>{['Profile','Precision','Recall','mAP50','Count error','FPS','p95 ms'].map((h) => <th key={h} className="p-2 text-left">{h}</th>)}</tr></thead>
        <tbody>{Object.entries(report.profiles).map(([name,r]) => <tr key={name}><td className="p-2">{name}</td>{['precision','recall','map50','count_mean_absolute_error','inference_fps','inference_ms_p95'].map((key) => <td className="p-2" key={key}>{r[key] == null ? 'Not measured' : Number(r[key]).toFixed(3)}</td>)}</tr>)}</tbody></table>
      {(report.limitations || []).map((text) => <p className="text-xs text-muted" key={text}>{text}</p>)}
      {Object.entries(report.profiles).map(([name,r]) => <details key={name} className="border-t border-line pt-3">
        <summary className="cursor-pointer text-sm">{name}: tracking, alerts and confidence thresholds</summary>
        <p className="text-xs text-muted my-2">Compare track coverage as well as ID switches. A tracker that misses most labeled tracks can have few switches.</p>
        <table className="w-full text-xs"><thead><tr>{['Tracker','Coverage','ID switches','Missed alerts','False alerts','Alert delay (s)'].map((h) => <th className="p-2 text-left" key={h}>{h}</th>)}</tr></thead><tbody>
          {Object.entries(r.trackers || {}).map(([tracker,t]) => <tr key={tracker}><td className="p-2">{tracker}</td><td>{t.coverage == null ? 'Not measured' : `${(t.coverage*100).toFixed(1)}%`}</td><td>{t.id_switches}</td><td>{t.events?.missed ?? 'Not measured'}</td><td>{t.events?.false_alerts ?? 'Not measured'}</td><td>{t.events?.mean_alert_delay_secs?.toFixed(2) ?? 'Not measured'}</td></tr>)}
        </tbody></table>
        {Object.keys(r.confidence_sweep || {}).length>0 && <><p className="text-xs text-muted my-2">Development thresholds only. Confirm your choice on independent test clips.</p>
          <table className="w-full text-xs"><thead><tr><th className="text-left p-2">Threshold</th><th>Precision</th><th>Recall</th><th>F1</th></tr></thead><tbody>{Object.entries(r.confidence_sweep).map(([threshold,t]) => <tr key={threshold}><td className="p-2">{threshold}</td>{['precision','recall','f1'].map((key) => <td className="text-center" key={key}>{t[key]?.toFixed(3) ?? 'N/A'}</td>)}</tr>)}</tbody></table></>}
      </details>)}
    </div>}
  </div>;
}
