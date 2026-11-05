export default function AnalysisSettings({ value = {}, onChange, zones = [] }) {
  const update = (key, next) => onChange({ ...value, [key]: next });
  const regions = value.regions || [];
  return <div className="space-y-4">
    <label className="block text-sm">Analysis quality
      <select className="input mt-1" value={value.preset || 'fast'} onChange={(e) => onChange({ ...value, preset: e.target.value, input_size: null })}>
        <option value="fast">Fast — lowest CPU use</option>
        <option value="balanced">Balanced — stronger detector</option>
        <option value="detail">Detailed — strongest small-object view, slower</option>
      </select>
    </label>
    <p className="text-xs text-muted">Detailed modes use more memory and processing time. Compare analysed fps and frame age after saving. A new model may need to download on first use.</p>
    <label className="block text-sm">Tracking
      <select className="input mt-1" value={value.tracker || 'centroid'} onChange={(e) => update('tracker', e.target.value)}>
        <option value="bytetrack">Stable tracking — ByteTrack</option>
        <option value="botsort">Motion tracking — BoT-SORT</option>
        <option value="centroid">Basic tracking — current default</option>
      </select>
    </label>
    <label className="block text-sm">People confidence: {Math.round((value.person_confidence ?? .35)*100)}%
      <input aria-label="People confidence" className="w-full" type="range" min="10" max="90" step="5" value={(value.person_confidence ?? .35)*100} onChange={(e) => update('person_confidence', Number(e.target.value)/100)} />
    </label>
    <label className="block text-sm">Vehicle confidence: {Math.round((value.vehicle_confidence ?? .35)*100)}%
      <input aria-label="Vehicle confidence" className="w-full" type="range" min="10" max="90" step="5" value={(value.vehicle_confidence ?? .35)*100} onChange={(e) => update('vehicle_confidence', Number(e.target.value)/100)} />
    </label>
    <p className="text-xs text-muted">Lower confidence can find more objects and produce more false detections. Use a labeled benchmark to choose it.</p>
    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={value.tiled || false} onChange={(e) => update('tiled', e.target.checked)} />Extra small-object detail (slower)</label>
    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={value.plate_reading ?? true} onChange={(e) => update('plate_reading', e.target.checked)} />Read clear number plates</label>
    <p className="text-xs text-muted">Plate readings require a sharp plate-sized crop and agreement across several frames. Distant or blurred plates are left unrecognized.</p>
    <label className="block text-sm">Confirm objects across analysed frames
      <input className="input mt-1" type="number" min="1" max="15" value={value.confirmation_frames ?? 3} onChange={(e) => update('confirmation_frames', Math.max(1, Math.min(15, Number(e.target.value) || 1)))} />
    </label>
    <div className="space-y-2">
      <h3 className="text-sm font-medium">Distant detail regions ({regions.length}/4)</h3>
      <p className="text-xs text-muted">A region receives an extra close-up detection pass. Coordinates are percentages of frame width/height, measured from the top left. Full-frame analysis remains enabled.</p>
      {regions.map((region, i) => <div className="grid grid-cols-2 gap-2 border border-line p-2 rounded" key={i}>
        {['x1','y1','x2','y2'].map((key) => <label className="text-xs" key={key}>{key.toUpperCase()} %
          <input className="input input-sm" type="number" min="0" max="100" value={Math.round(region[key]*100)} onChange={(e) => update('regions', regions.map((r,j) => j === i ? { ...r, [key]: Math.max(0,Math.min(100,Number(e.target.value)))/100 } : r))} />
        </label>)}
        <button className="btn btn-sm" type="button" onClick={() => update('regions', regions.filter((_,j) => j!==i))}>Remove region</button>
      </div>)}
      <button className="btn btn-sm" type="button" disabled={regions.length >= 4} onClick={() => update('regions', [...regions, { x1:0, y1:0, x2:1, y2:.5 }])}>Add detail region</button>
      {zones.some((z) => z.polygon?.length > 2) && <select aria-label="Use a drawn zone as a detail region" className="input" value="" disabled={regions.length >= 4} onChange={(e) => {
        const polygon = zones.find((z) => z.id === e.target.value)?.polygon;
        if (polygon) update('regions', [...regions, { x1:Math.min(...polygon.map((p) => p[0])), y1:Math.min(...polygon.map((p) => p[1])), x2:Math.max(...polygon.map((p) => p[0])), y2:Math.max(...polygon.map((p) => p[1])) }]);
      }}><option value="">Use a drawn polygon zone…</option>{zones.filter((z) => z.polygon?.length > 2).map((z) => <option key={z.id} value={z.id}>{z.name || z.id}</option>)}</select>}
    </div>
  </div>;
}
