import { Bot, RefreshCw, Send } from 'lucide-react';
import { useState } from 'react';
import { usePolling } from '../hooks/usePolling.jsx';
import { post } from '../lib/api';
import { fmtTime } from '../lib/format';

const EXAMPLES = [
  'How many people entered today compared to yesterday?',
  'Show critical incidents from the last 7 days',
  'Which camera had the most loitering alerts this week?',
  'List all vehicle plates seen at the gate camera today',
  'What was the busiest hour yesterday?',
];

export default function Assistant() {
  const { data: insights, refresh: refreshInsights } = usePolling('/api/insights', 300000);
  const [query, setQuery] = useState('');
  const [history, setHistory] = useState([]);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const available = insights?.available !== false;

  const ask = async (q) => {
    const question = (q || query).trim();
    if (!question || busy) return;
    setBusy(true);
    setQuery('');
    setHistory((h) => [...h, { role: 'user', text: question }]);
    try {
      const result = await post('/api/search', { query: question });
      setHistory((h) => [...h, { role: 'assistant', result }]);
    } catch (e) {
      setHistory((h) => [...h, { role: 'assistant', error: e.message }]);
    } finally {
      setBusy(false);
    }
  };

  const refreshAI = async () => {
    setRefreshing(true);
    try {
      await post('/api/insights/refresh', {});
      refreshInsights();
    } catch { /* rate limited */ }
    setRefreshing(false);
  };

  if (!available) {
    return (
      <div className="max-w-xl mx-auto mt-20 text-center space-y-3">
        <Bot size={40} className="mx-auto text-slate-600" />
        <h1 className="text-lg font-semibold text-white">AI Assistant is disabled</h1>
        <p className="text-sm text-slate-500">
          No Anthropic API key is configured on this node. Set <code className="text-slate-400">ANTHROPIC_API_KEY</code> in
          the environment and restart the backend to enable natural-language search and insights.
          All other platform features run unaffected.
        </p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
      <div className="xl:col-span-2 space-y-4">
        <h1 className="text-lg font-semibold text-white">AI Assistant</h1>

        <div className="space-y-3 min-h-64">
          {history.length === 0 && (
            <div className="bg-surface-800 border border-surface-700 rounded-lg p-4">
              <p className="text-sm text-slate-400 mb-3">
                Ask questions about detections, incidents, and analytics in plain English.
                Only your question text is sent to the AI — never video or data.
              </p>
              <div className="flex flex-wrap gap-2">
                {EXAMPLES.map((ex) => (
                  <button key={ex} onClick={() => ask(ex)}
                          className="text-xs px-2.5 py-1.5 rounded-full bg-surface-900 border border-surface-600 hover:border-info text-slate-300">
                    {ex}
                  </button>
                ))}
              </div>
            </div>
          )}

          {history.map((msg, i) => (
            <div key={i}>
              {msg.role === 'user' ? (
                <p className="text-sm bg-info/15 border border-info/30 rounded-lg px-3 py-2 inline-block">{msg.text}</p>
              ) : msg.error ? (
                <p className="text-sm text-critical bg-critical/10 border border-critical/30 rounded-lg px-3 py-2">{msg.error}</p>
              ) : (
                <div className="bg-surface-800 border border-surface-700 rounded-lg p-3 space-y-2">
                  <p className="text-sm text-slate-300">{msg.result.explanation}</p>
                  <pre className="text-xs bg-surface-950 rounded-md p-2 overflow-x-auto text-info">{msg.result.sql}</pre>
                  {msg.result.rows.length > 0 ? (
                    <div className="overflow-x-auto">
                      <table className="text-xs w-full">
                        <thead>
                          <tr className="text-left text-slate-500 border-b border-surface-700">
                            {msg.result.columns.map((c) => <th key={c} className="p-1.5 pr-4">{c}</th>)}
                          </tr>
                        </thead>
                        <tbody>
                          {msg.result.rows.map((row, ri) => (
                            <tr key={ri} className="border-b border-surface-700/40">
                              {row.map((cell, ci) => (
                                <td key={ci} className="p-1.5 pr-4 text-slate-300">
                                  {cell == null ? '—' : typeof cell === 'object' ? JSON.stringify(cell) : String(cell)}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <p className="text-xs text-slate-500">No rows returned.</p>
                  )}
                  <p className="text-[10px] text-slate-600">{msg.result.row_count} rows</p>
                </div>
              )}
            </div>
          ))}
          {busy && <p className="text-sm text-slate-500 animate-pulse">Thinking…</p>}
        </div>

        <form onSubmit={(e) => { e.preventDefault(); ask(); }} className="flex gap-2 sticky bottom-4">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g. Which zone had the most traffic this week?"
            className="flex-1 bg-surface-800 border border-surface-600 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:border-info"
          />
          <button type="submit" disabled={busy || !query.trim()}
                  className="bg-info hover:bg-info/80 disabled:opacity-40 text-white rounded-lg px-4">
            <Send size={16} />
          </button>
        </form>
      </div>

      <div>
        <div className="flex items-center justify-between mb-2 mt-1">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wide">AI Insights</h2>
          <button onClick={refreshAI} disabled={refreshing}
                  className="text-slate-500 hover:text-white disabled:opacity-50" title="Regenerate insights">
            <RefreshCw size={15} className={refreshing ? 'animate-spin' : ''} />
          </button>
        </div>
        <div className="space-y-2">
          {(insights?.insights || []).map((ins, i) => (
            <div key={i} className="bg-surface-800 border border-surface-700 rounded-lg p-3">
              <div className="flex items-center gap-2">
                <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-surface-900 text-slate-500">
                  {ins.kind}
                </span>
                <p className="text-sm font-medium text-white">{ins.title}</p>
              </div>
              <p className="text-xs text-slate-400 mt-1">{ins.detail}</p>
            </div>
          ))}
          {(insights?.insights || []).length === 0 && (
            <p className="text-sm text-slate-500">No insights generated yet. They refresh hourly, or press refresh.</p>
          )}
          {insights?.generated_at && (
            <p className="text-[10px] text-slate-600">Updated {fmtTime(insights.generated_at)}</p>
          )}
        </div>
      </div>
    </div>
  );
}
