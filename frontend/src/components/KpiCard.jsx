import { useNavigate } from 'react-router-dom';
import { fmtNumber } from '../lib/format';

// Summary tile. `delta` is a % change vs the prior period; `invert` marks
// metrics where a rise is bad (incidents), so the colour flips.
export default function KpiCard({ label, value, delta, icon: Icon, to, accent = 'text-accent', note, invert = false }) {
  const navigate = useNavigate();
  const good = delta == null ? null : invert ? delta <= 0 : delta >= 0;
  const Tag = to ? 'button' : 'div';
  return (
    <Tag onClick={to ? () => navigate(to) : undefined} className="kpi">
      <span className="flex items-center justify-between text-xs text-muted">
        {label}
        {Icon && <Icon size={16} className={accent} />}
      </span>
      <span className="kpi-value">{fmtNumber(value)}</span>
      {delta != null ? (
        <span className={`font-mono text-[11.5px] ${good ? 'text-normal' : 'text-critical'}`}>
          {delta >= 0 ? '▲' : '▼'} {Math.abs(delta)}% vs yesterday
        </span>
      ) : (
        <span className="text-[11.5px] text-muted">{note || ' '}</span>
      )}
    </Tag>
  );
}
