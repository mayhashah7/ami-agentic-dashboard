import { useEffect, useState } from 'react';
import { getJson } from '../lib/api';

type Agent = { name: string; domain: string; icon: string; color: string };

export function AgentRoster({ activeNames }: { activeNames: Set<string> }) {
  const [agents, setAgents] = useState<Agent[]>([]);
  useEffect(() => { getJson<Agent[]>('/api/agents/roster').then(setAgents).catch(() => {}); }, []);

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-baseline justify-between mb-2">
        <h2 className="text-sm font-semibold tracking-wide">AGENT FABRIC</h2>
        <span className="text-xs text-slate-500">{agents.length} agents</span>
      </div>
      <div className="grid grid-cols-2 gap-1.5 overflow-y-auto scroll-fade pr-1">
        {agents.map(a => {
          const active = activeNames.has(a.name);
          return (
            <div
              key={a.name}
              className={`p-1.5 rounded-md border text-[10px] font-mono transition ${
                active
                  ? 'border-grid-accent bg-grid-accent/10 text-grid-accent shadow-[0_0_12px_rgba(251,191,36,0.4)]'
                  : 'border-grid-border bg-grid-bg text-slate-400'
              }`}
              title={a.name}
            >
              <div className="flex items-center gap-1">
                <span style={{ color: a.color }} className="text-sm">{a.icon}</span>
                <span className="truncate">{a.name.replace('ami-', '')}</span>
                {active && <span className="ml-auto w-1.5 h-1.5 bg-grid-accent rounded-full animate-pulse" />}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
