import { useEffect, useState } from 'react';
import { GridMap } from './components/GridMap';
import { LoadChart } from './components/LoadChart';
import { ScenarioPanel } from './components/ScenarioPanel';
import { CasePanel } from './components/CasePanel';
import { ChatPanel } from './components/ChatPanel';
import { TopBar } from './components/TopBar';
import { WS_URL, getJson, type Substation, type Case } from './lib/api';

export default function App() {
  const [subs, setSubs] = useState<Substation[]>([]);
  const [cases, setCases] = useState<Case[]>([]);
  const [systemKw, setSystemKw] = useState<number>(0);
  const [tickHistory, setTickHistory] = useState<{ ts: string; mw: number }[]>([]);
  const [foundryConfigured, setFoundryConfigured] = useState<boolean>(false);

  useEffect(() => {
    getJson<{ foundry_configured: boolean }>('/api/health').then(h => setFoundryConfigured(h.foundry_configured)).catch(() => {});
    getJson<Substation[]>('/api/substations').then(setSubs).catch(console.error);
    getJson<Case[]>('/api/cases').then(setCases).catch(console.error);
  }, []);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let stopped = false;
    function connect() {
      ws = new WebSocket(WS_URL);
      ws.onmessage = ev => {
        try {
          const m = JSON.parse(ev.data);
          if (m.type === 'tick') {
            const mw = m.data.system_kw / 1000;
            setSystemKw(m.data.system_kw);
            setTickHistory(h => {
              const next = [...h, { ts: m.data.ts, mw }];
              return next.length > 120 ? next.slice(next.length - 120) : next;
            });
            if (m.data.sub_totals_kw) {
              setSubs(prev => prev.map(s => ({ ...s, total_kw: m.data.sub_totals_kw[s.substation_id] ?? s.total_kw })));
            }
          } else if (m.type === 'case') {
            setCases(prev => {
              const others = prev.filter(c => c.case_id !== m.data.case_id);
              return [m.data, ...others].slice(0, 30);
            });
          } else if (m.type === 'snapshot') {
            if (m.data.cases) setCases(m.data.cases);
          }
        } catch { /* ignore */ }
      };
      ws.onclose = () => { if (!stopped) setTimeout(connect, 2000); };
    }
    connect();
    return () => { stopped = true; ws?.close(); };
  }, []);

  return (
    <div className="h-full flex flex-col">
      <TopBar systemKw={systemKw} substations={subs.length} foundry={foundryConfigured} />
      <div className="flex-1 grid grid-cols-12 gap-3 p-3 overflow-hidden">
        <div className="col-span-7 flex flex-col gap-3 overflow-hidden">
          <div className="flex-1 bg-grid-panel border border-grid-border rounded-xl overflow-hidden min-h-0">
            <GridMap substations={subs} />
          </div>
          <div className="h-56 bg-grid-panel border border-grid-border rounded-xl p-3">
            <LoadChart history={tickHistory} />
          </div>
          <div className="h-44 bg-grid-panel border border-grid-border rounded-xl p-3">
            <ScenarioPanel onRan={() => getJson<Case[]>('/api/cases').then(setCases)} substations={subs} />
          </div>
        </div>

        <div className="col-span-3 bg-grid-panel border border-grid-border rounded-xl p-3 overflow-hidden flex flex-col">
          <CasePanel cases={cases} />
        </div>

        <div className="col-span-2 bg-grid-panel border border-grid-border rounded-xl p-3 overflow-hidden flex flex-col">
          <ChatPanel />
        </div>
      </div>
    </div>
  );
}
