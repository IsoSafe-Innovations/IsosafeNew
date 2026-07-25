import { FileSpreadsheet, FileText } from 'lucide-react';
import { useState } from 'react';
import { api } from '../lib/api';

const REPORTS = [
  { id: 'daily_summary', label: 'Daily Summary', desc: 'Footfall, vehicles, occupancy, and incidents for the last day.' },
  { id: 'weekly_security', label: 'Weekly Security', desc: 'All security incidents from the last 7 days with severity breakdown.' },
  { id: 'monthly_business', label: 'Monthly Business', desc: 'Business metrics and per-camera trends over 30 days.' },
  { id: 'incident_report', label: 'Incident Report', desc: 'Detailed incident log for the selected period.' },
  { id: 'camera_health', label: 'Camera Health', desc: 'Camera inventory, uptime, and stream status.' },
];

export default function Reports() {
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  const download = async (id, format) => {
    setBusy(`${id}-${format}`);
    setError(null);
    try {
      const res = await api(`/api/reports/${id}?format=${format}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `isosafe_${id}.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold text-white">Reports</h1>
      {error && <p className="text-sm text-critical">{error}</p>}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        {REPORTS.map((r) => (
          <div key={r.id} className="bg-surface-800 border border-surface-700 rounded-lg p-4 flex flex-col">
            <h2 className="text-sm font-semibold text-white">{r.label}</h2>
            <p className="text-xs text-slate-500 mt-1 flex-1">{r.desc}</p>
            <div className="flex gap-2 mt-3">
              <button
                onClick={() => download(r.id, 'pdf')}
                disabled={busy === `${r.id}-pdf`}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md bg-surface-700 hover:bg-surface-600 disabled:opacity-50"
              >
                <FileText size={13} /> {busy === `${r.id}-pdf` ? 'Generating…' : 'PDF'}
              </button>
              <button
                onClick={() => download(r.id, 'xlsx')}
                disabled={busy === `${r.id}-xlsx`}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md bg-surface-700 hover:bg-surface-600 disabled:opacity-50"
              >
                <FileSpreadsheet size={13} /> {busy === `${r.id}-xlsx` ? 'Generating…' : 'Excel'}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
