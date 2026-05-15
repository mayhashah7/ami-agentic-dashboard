import { useRef, useState, useEffect } from 'react';
import { chatStream } from '../lib/api';

type Msg = { role: 'user' | 'assistant' | 'tool'; text: string; meta?: any };

const STARTERS = [
  'Are there any outages right now on substation S-01?',
  'Find suspicious meters that look like theft on S-02.',
  'Plan a 5 MW demand response event for the next hour.',
  'Score transformer health on substation S-03.',
  "Why was this customer's August bill higher than July?",
];

export function ChatPanel() {
  const [persona, setPersona] = useState<'operator' | 'planner' | 'customer'>('operator');
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => { scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight); }, [msgs]);

  async function send(t: string) {
    if (!t.trim() || busy) return;
    setMsgs(m => [...m, { role: 'user', text: t }]);
    setText(''); setBusy(true);
    try {
      let buffered = '';
      for await (const evt of chatStream(t, persona)) {
        if (evt.type === 'tool_call') {
          setMsgs(m => [...m, { role: 'tool', text: `→ ${evt.name}(${JSON.stringify(evt.arguments).slice(0, 80)})` }]);
        } else if (evt.type === 'final') {
          setMsgs(m => [...m, { role: 'assistant', text: evt.text }]);
        } else if (evt.type === 'token') {
          buffered += evt.text ?? '';
        }
      }
      if (buffered) setMsgs(m => [...m, { role: 'assistant', text: buffered }]);
    } catch (e: any) {
      setMsgs(m => [...m, { role: 'assistant', text: `error: ${e.message}` }]);
    } finally { setBusy(false); }
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-baseline justify-between mb-2">
        <h2 className="text-sm font-semibold tracking-wide">CHAT</h2>
        <select
          value={persona}
          onChange={e => setPersona(e.target.value as any)}
          className="text-[10px] bg-grid-bg border border-grid-border rounded px-1 py-0.5"
        >
          <option value="operator">operator</option>
          <option value="planner">planner</option>
          <option value="customer">customer</option>
        </select>
      </div>
      <div ref={scrollRef} className="flex-1 overflow-y-auto scroll-fade text-xs space-y-1.5 pr-1">
        {msgs.length === 0 && (
          <div className="space-y-1">
            <div className="text-slate-500 mb-1">Try:</div>
            {STARTERS.map(s => (
              <button key={s} onClick={() => send(s)} className="block text-left text-[11px] text-grid-info hover:text-grid-accent">• {s}</button>
            ))}
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={
            m.role === 'user' ? 'text-slate-200 bg-grid-bg p-1.5 rounded'
            : m.role === 'tool' ? 'text-[10px] text-grid-info font-mono'
            : 'text-emerald-300 bg-emerald-500/10 p-1.5 rounded border border-emerald-500/20'
          }>
            {m.text}
          </div>
        ))}
      </div>
      <div className="mt-2 flex gap-1">
        <input
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && send(text)}
          placeholder={busy ? 'thinking…' : 'ask the AMI fabric…'}
          disabled={busy}
          className="flex-1 bg-grid-bg border border-grid-border rounded px-2 py-1 text-xs"
        />
        <button onClick={() => send(text)} disabled={busy} className="px-2 py-1 text-xs rounded bg-grid-accent text-black disabled:opacity-50">↩</button>
      </div>
    </div>
  );
}
