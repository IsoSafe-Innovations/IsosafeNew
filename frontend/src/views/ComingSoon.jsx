import { Construction } from 'lucide-react';

export default function ComingSoon() {
  return (
    <div className="panel max-w-md mx-auto mt-16 p-8 flex flex-col items-center text-center gap-2">
      <span className="w-11 h-11 rounded-xl bg-raised grid place-items-center text-muted"><Construction size={22} /></span>
      <p className="font-display font-semibold text-lg">Coming soon</p>
      <p className="text-sm text-muted">This feature isn’t part of the demo yet.</p>
    </div>
  );
}
