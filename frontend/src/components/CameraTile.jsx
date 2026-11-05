import { Car, Users } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useWebSocket } from '../hooks/useWebSocket.jsx';
import AnalysisStatus from './AnalysisStatus.jsx';

// Live camera tile. When `live` is true it subscribes to the frame stream;
// otherwise it renders counts only (thumbnail mode). The video surface stays
// dark on purpose; the caption sits on the light card.
export default function CameraTile({ camera, live = false, large = false, onClick, selected = false, caption = true }) {
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
  const youtube = camera.type === 'youtube' && /^[A-Za-z0-9_-]{11}$/.test(camera.youtube_id || '');
  const people = inFrame.person || 0;
  const vehicles = (inFrame.car || 0) + (inFrame.truck || 0) + (inFrame.bus || 0) + (inFrame.motorcycle || 0);
  const risk = alertSeverity === 'critical' ? 'HIGH' : alertSeverity === 'warning' ? 'MED' : 'LOW';
  const riskColor = risk === 'HIGH' ? 'text-[#ff7b73]' : risk === 'MED' ? 'text-[#ffbf4d]' : 'text-[#5fdc9a]';
  const activity = youtube && !camera.analysis?.ready
    ? 'Analysis connecting…'
    : people > 0
      ? `${people} ${people === 1 ? 'person' : 'people'} in frame`
      : vehicles > 0 ? `${vehicles} vehicle${vehicles === 1 ? '' : 's'}` : 'No activity';

  return (
    <div className="flex flex-col gap-1.5 min-w-0 h-full">
      <div
        className={`feed ${large ? 'aspect-video flex-1' : 'aspect-video'} ${youtube ? 'min-h-[200px]' : ''} ${
          alertSeverity ? `feed-alert-${alertSeverity} alert-pulse` : ''
        } ${selected ? 'ring-2 ring-accent ring-offset-2 ring-offset-panel' : ''}`}
      >
        {youtube && live && camera.enabled ? (
          <iframe title={`${camera.name} live video`}
            src={`https://www.youtube-nocookie.com/embed/${camera.youtube_id}?autoplay=1&mute=1&playsinline=1&rel=0`}
            allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
            referrerPolicy="strict-origin-when-cross-origin" allowFullScreen
            className="w-full h-full border-0" />
        ) : frame ? (
          <img src={`data:image/jpeg;base64,${frame}`} alt={camera.name} className="w-full h-full object-cover" />
        ) : (
          <div className="feed-empty">
            {online ? 'Streaming…' : camera.is_upload && camera.enabled ? 'Waiting for playback…' : 'Offline'}
          </div>
        )}
        {!youtube && (
          <>
            <div className="absolute top-2 left-2 right-2 flex items-center gap-1.5 pointer-events-none">
              {camera.is_upload ? (
                <span className="ovtag !text-[#7fd8e8]">UPLOAD · LOOP</span>
              ) : online ? (
                <span className="ovtag ovtag-live">LIVE</span>
              ) : (
                <span className="ovtag !text-[#ff7b73]">OFFLINE</span>
              )}
              {online && camera.analysis?.ready && <span className={`ovtag ${riskColor}`}>{alertSeverity ? `ALERT ${risk}` : 'NO ACTIVE ALERT'}</span>}
            </div>
            <div className="absolute bottom-2 left-2 pointer-events-none">
              <span className="ovtag">
                <Users size={11} /> {people}
                <Car size={11} className="ml-1" /> {vehicles}
              </span>
            </div>
          </>
        )}
      </div>
      {caption && (
        <button onClick={onClick} className="flex items-baseline justify-between gap-2 px-0.5 text-left w-full">
          <span className="text-[13px] font-medium truncate">{camera.name}{youtube ? ' · YouTube' : ''}</span>
          <span className="text-[11.5px] text-muted whitespace-nowrap">
            {counts.person != null && !people && !vehicles ? `${counts.person} tracks this session` : activity}
          </span>
        </button>
      )}
      {caption && <AnalysisStatus camera={camera} />}
    </div>
  );
}
