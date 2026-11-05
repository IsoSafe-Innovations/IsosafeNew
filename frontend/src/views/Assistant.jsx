import { Bot, Database, Lock, Plus, RefreshCw, Send, Sparkles } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { PageHeader, Panel } from '../components/ui.jsx';
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
  const endRef = useRef(null);

  const available = insights?.available !== false;

  useEffect(() => { endRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }, [history, busy]);

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
      <div className="panel max-w-xl mx-auto mt-16 p-8 text-center flex flex-col gap-3 items-center">
        <span className="w-12 h-12 rounded-xl bg-raised grid place-items-center text-muted"><Bot size={26} /></span>
        <h1 className="page-title !text-lg">AI assistant is turned off</h1>
        <p className="text-sm text-ink-2">
          No Anthropic API key is configured on this node. Set <code className="font-mono text-[12.5px] bg-raised px-1 rounded">ANTHROPIC_API_KEY</code> in
          the environment and restart the backend to turn on plain-English search and insights.
          Everything else keeps working without it.
        </p>
      </div>
    );
  }

  return (
    <>
      <PageHeader title="AI assistant" subtitle="Ask about detections, incidents and analytics in plain English">
        {history.length > 0 && (
          <button className="btn" onClick={() => setHistory([])} disabled={busy}><Plus size={15} />New conversation</button>
        )}
      </PageHeader>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_340px] gap-4 items-start">
        <section className="panel flex flex-col min-h-[560px]">
          <div className="flex-1 p-5 flex flex-col gap-[18px]">
            {history.length === 0 && (
              <div className="m-auto max-w-md text-center flex flex-col items-center gap-2.5 py-10">
                <span className="w-11 h-11 rounded-xl grid place-items-center bg-accent p-2"><img src="/logo-mark-light.png" alt="" className="w-full h-auto" /></span>
                <p className="font-display font-semibold text-lg">What would you like to know?</p>
                <p className="text-[13px] text-muted">
                  Ask a question below or pick one from “Try asking”. You’ll get a table of results and the query used to build it.
                </p>
              </div>
            )}

            {history.map((msg, i) => (
              msg.role === 'user' ? (
                <p key={i} className="self-end max-w-[80%] bg-accent/10 border border-accent/25 px-3 py-2 rounded-[12px_12px_3px_12px] text-sm">
                  {msg.text}
                </p>
              ) : (
                <div key={i} className="grid grid-cols-[30px_1fr] gap-3 max-w-full">
                  <span className="w-[30px] h-[30px] rounded-lg grid place-items-center bg-accent p-1"><img src="/logo-mark-light.png" alt="" className="w-full h-auto" /></span>
                  {msg.error ? (
                    <p className="alert-banner alert-error">{msg.error}</p>
                  ) : (
                    <div className="flex flex-col gap-2.5 min-w-0">
                      <p className="text-sm">{msg.result.explanation}</p>
                      {msg.result.rows.length > 0 ? (
                        <div className="table-wrap border border-line rounded-lg">
                          <table className="table !text-[12.5px]">
                            <thead>
                              <tr>{msg.result.columns.map((c) => <th key={c} className="!py-2">{c}</th>)}</tr>
                            </thead>
                            <tbody>
                              {msg.result.rows.map((row, ri) => (
                                <tr key={ri}>
                                  {row.map((cell, ci) => (
                                    <td key={ci} className="!py-2">
                                      {cell == null ? '—' : typeof cell === 'object' ? JSON.stringify(cell) : String(cell)}
                                    </td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : (
                        <p className="text-xs text-muted">No rows matched.</p>
                      )}
                      <details>
                        <summary className="cursor-pointer text-xs text-muted inline-flex items-center gap-1.5 hover:text-ink">
                          <Database size={13} />Show the query · {msg.result.row_count} rows
                        </summary>
                        <pre className="mt-2 font-mono text-xs bg-raised border border-line rounded-lg px-3 py-2.5 overflow-x-auto text-accent">{msg.result.sql}</pre>
                      </details>
                    </div>
                  )}
                </div>
              )
            ))}
            {busy && <p className="text-sm text-muted animate-pulse pl-[42px]">Working on it…</p>}
            <div ref={endRef} />
          </div>

          <form onSubmit={(e) => { e.preventDefault(); ask(); }} className="border-t border-line p-3.5 flex gap-2.5">
            <input
              value={query} onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g. Which zone had the most traffic this week?"
              aria-label="Your question" className="input !h-[42px] !text-sm"
            />
            <button type="submit" disabled={busy || !query.trim()} className="btn btn-primary !h-[42px]">
              <Send size={15} />Ask
            </button>
          </form>
        </section>

        <aside className="flex flex-col gap-4">
          <Panel title="Try asking">
            <div className="flex flex-col gap-1.5">
              {EXAMPLES.map((ex) => (
                <button key={ex} onClick={() => ask(ex)} disabled={busy}
                  className="text-left text-[13px] px-3 py-2 border border-line rounded-lg text-ink-2 hover:border-accent hover:text-ink disabled:opacity-50">
                  {ex}
                </button>
              ))}
            </div>
          </Panel>

          <Panel
            title="Insights"
            action={(
              <button onClick={refreshAI} disabled={refreshing} className="btn btn-ghost btn-sm" title="Regenerate insights">
                <RefreshCw size={13} className={refreshing ? 'animate-spin' : ''} />Refresh
              </button>
            )}
          >
            {(insights?.insights || []).length === 0 && (
              <p className="text-sm text-muted">No insights yet. They refresh hourly, or press Refresh.</p>
            )}
            <div className="flex flex-col">
              {(insights?.insights || []).map((ins, i) => (
                <div key={i} className="grid grid-cols-[26px_1fr] gap-2.5 py-2.5 border-t border-line first:border-0 first:pt-0">
                  <span className="w-[26px] h-[26px] rounded-md grid place-items-center bg-accent/10 text-accent"><Sparkles size={14} /></span>
                  <div className="min-w-0">
                    <p className="text-[13.5px] font-medium">{ins.title}</p>
                    <p className="text-[12.5px] text-ink-2 mt-0.5">{ins.detail}</p>
                    {ins.kind && <span className="tag mt-1.5 !text-[10.5px] uppercase tracking-wide">{ins.kind}</span>}
                  </div>
                </div>
              ))}
            </div>
            {insights?.generated_at && <p className="text-[11px] text-muted mt-2 font-mono">Updated {fmtTime(insights.generated_at)}</p>}
          </Panel>

          <div className="grid grid-cols-[18px_1fr] gap-2.5 text-[12.5px] text-ink-2 p-3 rounded-lg bg-normal/[0.06] border border-normal/25">
            <Lock size={16} className="text-normal mt-0.5" />
            <span>Only your question text is sent to the AI model. Video, images and raw detections stay on your system.</span>
          </div>
        </aside>
      </div>
    </>
  );
}
