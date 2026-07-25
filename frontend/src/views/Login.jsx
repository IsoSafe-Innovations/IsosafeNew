import { Shield } from 'lucide-react';
import { useState } from 'react';
import { useAuth } from '../hooks/useAuth.jsx';

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
      setError(err.message || 'Login failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <form onSubmit={submit} className="bg-surface-800 border border-surface-700 rounded-xl p-8 w-full max-w-sm space-y-4">
        <div className="flex flex-col items-center gap-2 pb-2">
          <Shield className="text-info" size={36} />
          <h1 className="text-xl font-bold text-white">Iso Safe</h1>
          <p className="text-sm text-slate-500">Video intelligence platform</p>
        </div>
        <div>
          <label className="text-xs text-slate-400 block mb-1">Email</label>
          <input
            type="email" value={email} onChange={(e) => setEmail(e.target.value)} required
            className="w-full bg-surface-900 border border-surface-600 rounded-md px-3 py-2 text-sm focus:outline-none focus:border-info"
          />
        </div>
        <div>
          <label className="text-xs text-slate-400 block mb-1">Password</label>
          <input
            type="password" value={password} onChange={(e) => setPassword(e.target.value)} required
            className="w-full bg-surface-900 border border-surface-600 rounded-md px-3 py-2 text-sm focus:outline-none focus:border-info"
          />
        </div>
        {error && <p className="text-sm text-critical">{error}</p>}
        <button
          type="submit" disabled={busy}
          className="w-full bg-info hover:bg-info/80 disabled:opacity-50 text-white rounded-md py-2 text-sm font-medium"
        >
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  );
}
