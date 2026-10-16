import { Construction } from 'lucide-react';

export default function ComingSoon() {
  return (
    <div className="flex flex-col items-center justify-center text-center mt-24 gap-2">
      <Construction className="text-slate-600" size={32} />
      <p className="text-sm font-semibold text-slate-300">Coming soon</p>
      <p className="text-xs text-slate-500">This feature is not part of the demo.</p>
    </div>
  );
}
