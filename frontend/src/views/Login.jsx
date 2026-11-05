import { Bell, Lock, ScanSearch, SlidersHorizontal } from 'lucide-react';
import { useState } from 'react';
import { useAuth } from '../hooks/useAuth.jsx';

const FEATURES = [
  [ScanSearch, 'Detects people and vehicles on every camera'],
  [SlidersHorizontal, '8 rule types: loitering, intrusion, line crossing and more'],
  [Bell, 'Alerts and incidents your team can pick up and resolve'],
];

export default function Login() {
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
    } catch (err) {
      setError(err.message || 'Sign-in failed. Check your email and password.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-full grid lg:grid-cols-[minmax(0,1.1fr)_minmax(400px,0.9fr)]">
      <div
        aria-hidden="true"
        className="relative overflow-hidden bg-accent text-white min-h-[300px] flex items-end"
        style={{
          backgroundImage:
            'linear-gradient(rgba(255,255,255,.05) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.05) 1px, transparent 1px), radial-gradient(circle at 70% 25%, rgba(255,255,255,.10), transparent 55%)',
          backgroundSize: '48px 48px, 48px 48px, 100% 100%',
        }}
      >
        {/* decorative detection boxes */}
        <span className="absolute left-[18%] top-[18%] w-[90px] h-[180px] border-2 border-white/80 rounded-sm hidden sm:block">
          <span className="absolute -top-5 left-[-2px] bg-white text-accent font-mono text-[10px] px-1.5 py-0.5">person 0.94</span>
        </span>
        <span className="absolute left-[46%] top-[34%] w-[190px] h-[100px] border-2 border-white/80 rounded-sm hidden sm:block">
          <span className="absolute -top-5 left-[-2px] bg-white text-accent font-mono text-[10px] px-1.5 py-0.5">truck 0.97</span>
        </span>
        <span className="absolute right-[12%] top-[14%] w-[70px] h-[140px] border-2 border-dashed border-white/80 rounded-sm hidden md:block">
          <span className="absolute -top-5 left-[-2px] bg-white text-accent font-mono text-[10px] px-1.5 py-0.5">zone intrusion</span>
        </span>
        <div className="absolute inset-0 bg-gradient-to-t from-accent via-accent/75 to-transparent" />
        <div className="relative p-6 sm:p-12 max-w-xl flex flex-col gap-4">
          <img src="/logo-full-light.png" alt="Iso Safe Innovations" className="h-28 sm:h-32 w-auto self-start -ml-2" />
          <h1 className="font-display font-bold text-3xl sm:text-[40px] leading-[1.08] text-white">
            See what matters on every camera, as it happens.
          </h1>
          <ul className="flex flex-col gap-2 text-[14px] text-white/80">
            {FEATURES.map(([Icon, text]) => (
              <li key={text} className="flex items-center gap-2.5"><Icon size={16} className="text-white" />{text}</li>
            ))}
          </ul>
        </div>
      </div>

      <div className="flex items-center justify-center px-6 py-10 bg-panel">
        <form onSubmit={submit} className="w-full max-w-[360px] flex flex-col gap-4">
          <img src="/logo-mark-green.png" alt="" className="h-12 w-auto self-start" />
          <div>
            <h2 className="page-title !text-2xl">Sign in</h2>
            <p className="text-muted mt-1">Use the account your administrator created for you.</p>
          </div>
          <div>
            <label htmlFor="login-email" className="field-label">Work email</label>
            <input id="login-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required
              autoComplete="username" placeholder="name@company.com" className="input !h-[42px] !text-sm" />
          </div>
          <div>
            <label htmlFor="login-password" className="field-label">Password</label>
            <input id="login-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required
              autoComplete="current-password" className="input !h-[42px] !text-sm" />
          </div>
          {error && <p role="alert" className="alert-banner alert-error">{error}</p>}
          <button type="submit" disabled={busy} className="btn btn-primary !h-[42px] !text-sm">
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
          <p className="text-xs text-muted flex items-center gap-2">
            <Lock size={13} />Forgot your password? Ask your site administrator to reset it.
          </p>
        </form>
      </div>
    </div>
  );
}
