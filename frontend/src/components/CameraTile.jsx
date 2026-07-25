import { Activity, Car, Users } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useWebSocket } from '../hooks/useWebSocket.jsx';
import { SEVERITY_BORDER } from '../lib/format';

// Live camera tile. When `live` is true it subscribes to the frame stream;
// otherwise it renders counts only (thumbnail mode).
export default function CameraTile({ camera, live = false, large = false, onClick }) {
  const [frame, setFrame] = useState(null);
  const [counts, setCounts] = useState({});
  const [inFrame, setInFrame] = useState({});
  const [alertSeverity, setAlertSeverity] = useState(null);
  const alertTimer = useRef(null);

  const { subscribe, unsubscribe } = useWebSocket((msg) => {
    if (msg.camera_id !== camera.id) return;
    if (msg.type === 'frame') {
      setFrame(msg.image);
      setCounts(msg.counts || {});
      setInFrame(msg.in_frame || {});
    } else if (msg.type === 'counts') {
      setCounts(msg.counts || {});
      setInFrame(msg.in_frame || {});
    } else if (msg.type === 'incident') {
      setAlertSeverity(msg.severity);
      clearTimeout(alertTimer.current);
      alertTimer.current = setTimeout(() => setAlertSeverity(null), 15000);
    }
  });

  useEffect(() => {
    if (live) subscribe([camera.id]);
    return () => { if (live) unsubscribe([camera.id]); };
  }, [live, camera.id, subscribe, unsubscribe]);

  useEffect(() => () => clearTimeout(alertTimer.current), []);

  const online = camera.health?.online;
  const people = inFrame.person || 0;
  const vehicles = (inFrame.car || 0) + (inFrame.truck || 0) + (inFrame.bus || 0) + (inFrame.motorcycle || 0);
  const riskScore = alertSeverity === 'critical' ? 'HIGH' : alertSeverity === 'warning' ? 'MED' : 'LOW';
  const activity = people > 0
    ? `${people} ${people === 1 ? 'person' : 'people'} in frame`
    : vehicles > 0 ? `${vehicles} vehicle${vehicles === 1 ? '' : 's'}` : 'No activity';

  const borderClass = alertSeverity
    ? `${SEVERITY_BORDER[alertSeverity]} border-2 alert-pulse`
    : 'border-surface-700 border';

  return (
    <button
      onClick={onClick}
      className={`relative rounded-lg overflow-hidden bg-surface-800 text-left w-full transition-transform ${borderClass} ${
        alertSeverity ? 'scale-[1.02] z-10' : ''
      }`}
    >
      <div className={`relative ${large ? 'aspect-video' : 'aspect-[4/3]'} bg-black`}>
        {frame ? (
          <img
            src={`data:image/jpeg;base64,${frame}`}
            alt={camera.name}
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-slate-600 text-sm">
            {online ? 'Streaming…' : 'Offline'}
          </div>
        )}
        <div className="absolute top-2 left-2 flex items-center gap-2">
          {online && (
            <span className="flex items-center gap-1 bg-black/70 text-white text-[10px] font-semibold px-1.5 py-0.5 rounded">
              <span className="w-1.5 h-1.5 rounded-full bg-critical animate-pulse" /> LIVE
            </span>
          )}
          <span className={`bg-black/70 text-[10px] px-1.5 py-0.5 rounded font-semibold ${
            riskScore === 'HIGH' ? 'text-critical' : riskScore === 'MED' ? 'text-warning' : 'text-normal'
          }`}>
            RISK {riskScore}
          </span>
        </div>
        <div className="absolute bottom-2 left-2 right-2 flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs bg-black/70 rounded px-2 py-1">
            <span className="flex items-center gap-1 text-slate-200">
              <Users size={12} /> {people}
            </span>
            <span className="flex items-center gap-1 text-slate-200">
              <Car size={12} /> {vehicles}
            </span>
          </div>
        </div>
      </div>
      <div className="p-2 flex items-center justify-between">
        <div className="min-w-0">
          <p className="text-sm font-medium text-white truncate">{camera.name}</p>
          <p className="text-xs text-slate-500 flex items-center gap-1 truncate">
            <Activity size={11} /> {activity}
          </p>
        </div>
        {counts.person != null && (
          <p className="text-xs text-slate-500 whitespace-nowrap pl-2">{counts.person} today</p>
        )}
      </div>
    </button>
  );
}
