import { useState } from 'react';
import { postJson, type Substation } from '../lib/api';

const SCENARIOS = [
  { id: 'storm-outage',     label: 'Storm Outage',         hint: 'Knocks a feeder offline + customer calls' },
  { id: 'der-overvoltage',  label: 'Solar Backfeed Burst', hint: 'Solar overvoltage on secondaries'        },
  { id: 'heat-wave',        label: 'Heat Wave',            hint: 'System peak / DR signal'                 },
  { id: 'theft',            label: 'Theft Pattern',        hint: 'Plant tampers + flat-overnight reads'    },
];

export function ScenarioPanel({ onRan, substations }: { onRan: () => void; substations: Substation[] }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [last, setLast] = useState<string>('');
  const sub = substations[0]?.substation_id ?? '';

  async function run(id: string) {
    setBusy(id); setLast('');
    try {
      const body: any = id === 'storm-outage' ? { substation_id: sub, feeder_index: 7 }
                       : id === 'theft'       ? { substation_id: sub, count: 3 }
                       : id === 'der-overvoltage' ? { substation_id: sub }
                       : {};
      const r = await postJson<any>(`/api/scenarios/${id}`, body);
      setLast(`${id}: ${JSON.stringify(r)}`);
      onRan();
    } catch (e: any) { setLast(`error: ${e.message}`); }
    finally { setBusy(null); }
  }

  return (
    <div className="h-full flex flex-col">
      <h2 className="text-sm font-semibold tracking-wide mb-2">SCENARIOS</h2>
      <div className="grid grid-cols-2 gap-2 flex-1">
        {SCENARIOS.map(s => (
          <button
            key={s.id}
            disabled={!!busy}
            onClick={() => run(s.id)}
            className="text-left p-2 rounded-lg bg-grid-bg border border-grid-border hover:border-grid-accent disabled:opacity-50 transition"
          >
            <div className="text-sm font-medium text-grid-accent">{busy === s.id ? '⏳ ' + s.label : s.label}</div>
            <div className="text-[11px] text-slate-400">{s.hint}</div>
          </button>
        ))}
      </div>
      {last && <div className="text-[10px] text-slate-500 mt-1 truncate font-mono">{last}</div>}
    </div>
  );
}
