import { Camera, ChartLine, Clock, Download, FileSpreadsheet, FileText, Shield, ShieldAlert } from 'lucide-react';
import { useState } from 'react';
import { PageHeader } from '../components/ui.jsx';
import { api } from '../lib/api';

// `includes` mirrors what backend/app/api/reports.py puts in the PDF; every
// Excel export also carries the hourly analytics and incident sheets.
const TOTALS = 'Totals: footfall, incidents (with critical count) and cameras';
const REPORTS = [
  {
    id: 'daily_summary', label: 'Daily summary', icon: FileText, period: 'Last 24 h',
    desc: 'Footfall and incidents per camera for the last day.',
    includes: [TOTALS, 'Footfall and incident count per camera'],
  },
  {
    id: 'weekly_security', label: 'Weekly security', icon: Shield, period: 'Last 7 days',
    desc: 'Every security incident from the last 7 days.',
    includes: [TOTALS, 'Incident list: time, camera, type, severity and status (up to 200)'],
  },
  {
    id: 'monthly_business', label: 'Monthly business', icon: ChartLine, period: 'Last 30 days',
    desc: 'Footfall and incidents per camera over 30 days.',
    includes: [TOTALS, 'Footfall and incident count per camera'],
  },
  {
    id: 'incident_report', label: 'Incident report', icon: ShieldAlert, period: 'Last 7 days',
    desc: 'Detailed incident log for the period.',
    includes: [TOTALS, 'Incident list: time, camera, type, severity and status (up to 200)'],
  },
  {
    id: 'camera_health', label: 'Camera inventory', icon: Camera, period: 'Last 24 h',
    desc: 'Every configured camera with its type, profile and whether it is enabled.',
    includes: [TOTALS, 'Camera list: ID, source type, vertical profile, enabled'],
  },
];
const EXCEL_NOTE = 'The Excel file adds an hourly analytics sheet (footfall, queues, occupancy) and a full incident sheet with descriptions.';

export default function Reports() {
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [selectedId, setSelectedId] = useState(REPORTS[0].id);
  const selected = REPORTS.find((r) => r.id === selectedId);

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

  const DownloadButtons = ({ id, size = 'btn-sm' }) => (
    <>
      <button onClick={(e) => { e.stopPropagation(); download(id, 'pdf'); }} disabled={busy === `${id}-pdf`} className={`btn ${size}`}>
        <FileText size={13} /> {busy === `${id}-pdf` ? 'Generating…' : 'PDF'}
      </button>
      <button onClick={(e) => { e.stopPropagation(); download(id, 'xlsx'); }} disabled={busy === `${id}-xlsx`} className={`btn ${size}`}>
        <FileSpreadsheet size={13} /> {busy === `${id}-xlsx` ? 'Generating…' : 'Excel'}
      </button>
    </>
  );

  return (
    <>
      <PageHeader title="Reports" subtitle="Download as PDF to share, or as Excel for your own analysis" />
      {error && <p role="alert" className="alert-banner alert-error">{error}</p>}

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_380px] gap-4 items-start">
        <section className="panel overflow-hidden">
          {REPORTS.map((r) => {
            const Icon = r.icon;
            return (
              <div
                key={r.id} role="button" tabIndex={0}
                onClick={() => setSelectedId(r.id)}
                onKeyDown={(e) => e.key === 'Enter' && setSelectedId(r.id)}
                aria-current={r.id === selectedId}
                className={`grid grid-cols-[40px_1fr] sm:grid-cols-[40px_1fr_auto] gap-3.5 items-center px-4 py-3.5 border-t border-line first:border-0 cursor-pointer ${
                  r.id === selectedId ? 'bg-accent/[0.07]' : 'hover:bg-raised'
                }`}
              >
                <span className="w-10 h-10 rounded-lg bg-accent/10 text-accent grid place-items-center"><Icon size={18} /></span>
                <span className="min-w-0">
                  <span className="block font-medium">{r.label}</span>
                  <span className="block text-[12.5px] text-muted">{r.desc}</span>
                  <span className="tag mt-1.5"><Clock size={12} />{r.period}</span>
                </span>
                <span className="col-span-2 sm:col-span-1 flex gap-2"><DownloadButtons id={r.id} /></span>
              </div>
            );
          })}
        </section>

        <aside className="panel detail-pane" aria-label="Report details">
          <div className="panel-h"><h2 className="section-title">What’s in it</h2><span className="tag">{selected.period}</span></div>
          <div className="panel-b flex flex-col gap-4">
            <div>
              <h3 className="text-[17px] font-semibold">{selected.label}</h3>
              <p className="text-[13px] text-ink-2 mt-1">{selected.desc}</p>
            </div>
            <ul className="flex flex-col gap-2 text-[13px]">
              {selected.includes.map((item) => (
                <li key={item} className="flex gap-2.5"><span className="mt-[7px] w-1.5 h-1.5 rounded-full bg-accent flex-none" />{item}</li>
              ))}
            </ul>
            <p className="text-xs text-muted">{EXCEL_NOTE}</p>
            <div className="grid grid-cols-2 gap-2">
              <button onClick={() => download(selected.id, 'pdf')} disabled={busy === `${selected.id}-pdf`} className="btn btn-primary">
                <Download size={15} />{busy === `${selected.id}-pdf` ? 'Generating…' : 'Download PDF'}
              </button>
              <button onClick={() => download(selected.id, 'xlsx')} disabled={busy === `${selected.id}-xlsx`} className="btn">
                <FileSpreadsheet size={15} />{busy === `${selected.id}-xlsx` ? 'Generating…' : 'Download Excel'}
              </button>
            </div>
          </div>
        </aside>
      </div>
    </>
  );
}
