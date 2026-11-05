import { Trash2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useWebSocket } from '../hooks/useWebSocket.jsx';
import { CHART } from '../lib/format';

// Draw polygon zones (click to add points, double-click to close) or a 2-point
// line over a live frame. Coordinates are stored normalized (0..1).
export default function ZoneEditor({ camera, zones, onChange }) {
  const [frame, setFrame] = useState(null);
  const [drawing, setDrawing] = useState([]);
  const [mode, setMode] = useState('polygon'); // polygon | line
  const [name, setName] = useState('');
  const containerRef = useRef(null);

  const { subscribe, unsubscribe } = useWebSocket((msg) => {
    if (msg.type === 'frame' && msg.camera_id === camera.id) setFrame(msg.image);
  });

  useEffect(() => {
    subscribe([camera.id]);
    return () => unsubscribe([camera.id]);
  }, [camera.id, subscribe, unsubscribe]);

  const toNorm = (e) => {
    const rect = containerRef.current.getBoundingClientRect();
    return [
      Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width)),
      Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height)),
    ].map((v) => Math.round(v * 1000) / 1000);
  };

  const handleClick = (e) => {
    const pt = toNorm(e);
    if (mode === 'line' && drawing.length === 1) {
      finishZone([...drawing, pt]);
    } else {
      setDrawing((d) => [...d, pt]);
    }
  };

  const finishZone = (points) => {
    const pts = points || drawing;
    const minPoints = mode === 'line' ? 2 : 3;
    if (pts.length < minPoints) return;
    const id = (name || `zone-${zones.length + 1}`).toLowerCase().replaceAll(/\s+/g, '-');
    const zone = mode === 'line'
      ? { id, name: name || id, line: pts.slice(0, 2) }
      : { id, name: name || id, polygon: pts };
    onChange([...zones, zone]);
    setDrawing([]);
    setName('');
  };

  const removeZone = (zoneId) => onChange(zones.filter((z) => z.id !== zoneId));

  const renderShape = (zone, color) => {
    if (zone.polygon) {
      return (
        <polygon
          key={zone.id}
          points={zone.polygon.map(([x, y]) => `${x * 100},${y * 100}`).join(' ')}
          fill={color} fillOpacity={0.15} stroke={color} strokeWidth={0.4}
        />
      );
    }
    if (zone.line) {
      const [[x1, y1], [x2, y2]] = zone.line;
      return (
        <line key={zone.id} x1={x1 * 100} y1={y1 * 100} x2={x2 * 100} y2={y2 * 100}
              stroke={color} strokeWidth={0.6} strokeDasharray="2 1" />
      );
    }
    return null;
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <select value={mode} onChange={(e) => { setMode(e.target.value); setDrawing([]); }}
                className="input !w-auto">
          <option value="polygon">Polygon zone</option>
          <option value="line">Perimeter line</option>
        </select>
        <input
          value={name} onChange={(e) => setName(e.target.value)}
          placeholder="Zone name (e.g. gate, queue, restricted)"
          className="input flex-1 min-w-40 !w-auto"
        />
        {drawing.length > 0 && (
          <>
            <button onClick={() => finishZone()} className="btn btn-primary">
              Finish ({drawing.length} pts)
            </button>
            <button onClick={() => setDrawing([])} className="btn">
              Cancel
            </button>
          </>
        )}
      </div>

      <div
        ref={containerRef}
        onClick={handleClick}
        onDoubleClick={() => mode === 'polygon' && finishZone()}
        className="feed relative aspect-video cursor-crosshair"
      >
        {frame ? (
          <img src={`data:image/jpeg;base64,${frame}`} alt="" className="w-full h-full object-fill select-none" draggable={false} />
        ) : (
          <div className="feed-empty">
            Waiting for live frame… (the pipeline must be running)
          </div>
        )}
        <svg className="absolute inset-0 w-full h-full pointer-events-none" viewBox="0 0 100 100" preserveAspectRatio="none">
          {zones.map((z) => renderShape(z, CHART.accent))}
          {drawing.length > 0 && renderShape(
            mode === 'line' ? { id: '_d', line: [...drawing, ...drawing].slice(0, 2) } : { id: '_d', polygon: drawing },
            CHART.warn
          )}
          {drawing.map(([x, y], i) => (
            <circle key={i} cx={x * 100} cy={y * 100} r={0.8} fill={CHART.warn} />
          ))}
        </svg>
      </div>

      <div className="flex flex-wrap gap-2">
        {zones.map((z) => (
          <span key={z.id} className="tag !rounded-full">
            {z.name || z.id}
            <span className="text-muted">{z.line ? 'line' : `${z.polygon?.length} pts`}</span>
            <button onClick={() => removeZone(z.id)} className="text-muted hover:text-critical" aria-label={`Remove ${z.name || z.id}`}>
              <Trash2 size={12} />
            </button>
          </span>
        ))}
        {zones.length === 0 && <p className="text-xs text-muted">No zones drawn. Click on the frame to start.</p>}
      </div>
    </div>
  );
}
