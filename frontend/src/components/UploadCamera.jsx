import { Upload } from 'lucide-react';
import { useState } from 'react';
import { usePolling } from '../hooks/usePolling.jsx';
import { uploadVideo } from '../lib/api';

export default function UploadCamera({ onUploaded, onBusyChange }) {
  const { data: config, error: configError } = usePolling('/api/uploads/config', 600000);
  const [file, setFile] = useState(null);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState(null);

  const chooseFile = (event) => {
    const next = event.target.files?.[0];
    setError(null);
    setFile(null);
    if (!next) return;
    const extension = `.${next.name.split('.').pop().toLowerCase()}`;
    if (!config.extensions.includes(extension)) {
      setError('Choose an MP4, MOV, AVI, MKV or WebM video.');
      return;
    }
    if (!next.size || next.size > config.max_mb * 1024 * 1024) {
      setError(next.size ? `Choose a video smaller than ${config.max_mb} MB.` : 'This file is empty.');
      return;
    }
    setFile(next);
    setName(next.name.replace(/\.[^.]+$/, '').slice(0, 120));
  };

  const submit = async (event) => {
    event.preventDefault();
    if (!file || busy) return;
    setBusy(true);
    onBusyChange(true);
    setProgress(0);
    setError(null);
    const body = new FormData();
    body.append('file', file);
    body.append('name', name.trim());
    try {
      const result = await uploadVideo(body, setProgress);
      onUploaded(result, name.trim() || file.name);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
      onBusyChange(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <p className="text-sm text-ink-2">
        Upload a recording to add it to your camera grid. It will play on repeat and run through video detection.
      </p>
      <div>
        <label htmlFor="camera-video" className="field-label">Video file</label>
        <input id="camera-video" type="file" accept={config?.extensions.join(',')}
          disabled={busy || !config} onChange={chooseFile}
          className="block w-full text-sm text-ink-2 file:mr-3 file:rounded-md file:border file:border-line file:bg-raised file:px-3 file:py-2 file:text-ink file:font-medium disabled:opacity-50" />
        <p className="mt-2 text-xs text-muted">
          MP4, MOV, AVI, MKV or WebM{config ? ` · Up to ${config.max_mb} MB` : ''}
          {file ? ` · ${(file.size / 1024 / 1024).toFixed(1)} MB selected` : ''}
        </p>
      </div>
      <div>
        <label htmlFor="upload-camera-name" className="field-label">Camera name</label>
        <input id="upload-camera-name" value={name} onChange={(event) => setName(event.target.value)}
          disabled={busy} maxLength={120} placeholder="e.g. Entrance recording" className="input" />
      </div>
      {(error || configError) && <p role="alert" className="text-sm text-critical">{error || configError.message}</p>}
      {busy && (
        <div role="status" className="space-y-2">
          <progress aria-label="Video upload progress" max="100" value={progress} className="w-full h-2 accent-accent" />
          <p className="text-xs text-ink-2">
            {progress < 100 ? `Uploading ${progress}% — keep this page open.` : 'Checking video and creating your camera…'}
          </p>
        </div>
      )}
      <button type="submit" disabled={!file || busy || !config}
        className="btn btn-primary w-full">
        <Upload size={16} /> {busy ? 'Adding camera…' : 'Upload and create camera'}
      </button>
    </form>
  );
}
