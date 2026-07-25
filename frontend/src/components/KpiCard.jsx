import { TrendingDown, TrendingUp } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { fmtNumber } from '../lib/format';

export default function KpiCard({ label, value, delta, icon: Icon, to, accent = 'text-info' }) {
  const navigate = useNavigate();
  return (
    <button
      onClick={() => to && navigate(to)}
      className="bg-surface-800 border border-surface-700 rounded-lg p-4 text-left hover:border-surface-600 transition-colors w-full"
    >
      <div className="flex items-center justify-between">
        <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
        {Icon && <Icon size={16} className={accent} />}
      </div>
      <p className="text-2xl font-semibold text-white mt-1">{fmtNumber(value)}</p>
      {delta != null && (
        <p className={`text-xs mt-1 flex items-center gap-1 ${delta >= 0 ? 'text-normal' : 'text-critical'}`}>
          {delta >= 0 ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
          {Math.abs(delta)}% vs prior period
        </p>
      )}
    </button>
  );
}
