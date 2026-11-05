export default function AnalysisStatus({ camera, detailed = false }) {
  const a = camera.analysis || {};
  const state = !camera.enabled ? 'paused' : a.state || 'waiting';
  const running = state === 'running' || state === 'delayed';
  const label = { waiting: 'Waiting for AI', warming_up: 'AI starting', running: 'AI running', delayed:'AI delayed', stalled: 'AI stalled', error: 'AI error', paused: 'AI paused' }[state] || state;
  if (!detailed) return <span className={`text-xs ${state === 'running' ? 'text-normal' : state === 'error' || state === 'stalled' ? 'text-critical' : 'text-warning'}`} aria-live="polite">{label}{running ? ` · ${a.processed_fps ?? 0} analysed fps` : ''}</span>;
  return (
    <div className="text-xs space-y-1" aria-live="polite">
      <p className={state === 'running' ? 'text-normal' : state === 'error' || state === 'stalled' ? 'text-critical' : 'text-warning'}>
        {label}{running ? ` · ${a.processed_fps ?? 0} analysed fps` : ''}
      </p>
      {detailed && <>
        <p className="text-muted">Latest result: {a.result_age_secs == null ? 'none yet' : `${a.result_age_secs}s ago`} · Frame age: {a.frame_age_secs == null ? 'unknown' : `${a.frame_age_secs}s`}</p>
        <p className="text-muted">Processed: {a.processed_frames ?? 0} · Skipped/dropped: {a.dropped_frames ?? 0} · Queued: {a.queue_depth ?? 0}</p>
        <p className="text-muted">Model batch time: {a.inference_ms == null ? 'warming up' : `${a.inference_ms} ms`} · Plate reading: {(a.ocr_state || 'idle').replaceAll('_', ' ')}</p>
        {a.frame_age_secs > 3 && <p className="text-warning">Analysis is behind the received video. Try a faster quality setting or fewer detail regions.</p>}
        {a.error && <p role="alert" className="text-critical">Analysis failed: {a.error}</p>}
        {Object.entries(a.crossings || {}).map(([key,count]) => <p key={key} className="text-muted">Line crossing {key}: {count}</p>)}
      </>}
    </div>
  );
}
