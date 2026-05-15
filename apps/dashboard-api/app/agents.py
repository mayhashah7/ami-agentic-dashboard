"""Foundry agent client — runs the orchestrator agent for chat turns and
handles tool calls back to the local store. Falls back to a deterministic
mock when no Foundry endpoint is configured (so local dev works offline).
"""
from __future__ import annotations

import json
import time
import uuid
from typing import AsyncIterator

from ami_tools.dispatch import handle_tool_call

from .config import settings
from .store import store

ORCHESTRATOR_NAME = "ami-orchestrator"


class FoundryAgentRunner:
    """Thin wrapper over the Foundry Agents SDK; lazy imports so the API still
    boots when SDK is unavailable."""

    def __init__(self) -> None:
        self._client = None
        self._agent_ids: dict[str, str] = {}

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        try:
            from azure.identity import DefaultAzureCredential
            from azure.ai.agents import AgentsClient
        except ImportError:
            print("[agents] SDK not installed — using mock runner")
            return None
        if not settings.foundry_endpoint:
            print("[agents] FOUNDRY_PROJECT_ENDPOINT not set — using mock runner")
            return None
        cred = DefaultAzureCredential(managed_identity_client_id=settings.azure_client_id or None)
        self._client = AgentsClient(endpoint=settings.foundry_endpoint, credential=cred)
        for a in self._client.list_agents():
            self._agent_ids[a.name] = a.id
        return self._client

    async def chat(self, *, text: str, persona: str | None = None, case_id: str | None = None) -> AsyncIterator[dict]:
        """Run a chat turn through the orchestrator. Yields dict events:
        {type: 'token'|'tool_call'|'tool_result'|'final'|'error', ...}.
        """
        client = self._ensure_client()
        if client is None:
            async for evt in self._mock_chat(text=text, persona=persona, case_id=case_id):
                yield evt
            return

        try:
            agent_id = self._agent_ids.get(ORCHESTRATOR_NAME)
            if not agent_id:
                yield {"type": "error", "message": "orchestrator agent not registered (run seed-foundry-agents.py)"}
                return

            thread = client.threads.create()
            client.messages.create(
                thread_id=thread.id, role="user",
                content=json.dumps({"kind": "chat", "actor": persona or "operator", "text": text, "case_id": case_id})
            )
            run = client.runs.create(thread_id=thread.id, agent_id=agent_id)

            terminal = {"completed", "failed", "cancelled", "expired", "requires_action"}
            while run.status not in terminal:
                time.sleep(0.4)
                run = client.runs.get(thread_id=thread.id, run_id=run.id)
                yield {"type": "status", "status": run.status}

                if run.status == "requires_action" and getattr(run, "required_action", None):
                    tool_outputs = []
                    for call in run.required_action.submit_tool_outputs.tool_calls:
                        name = call.function.name
                        args = json.loads(call.function.arguments or "{}")
                        yield {"type": "tool_call", "name": name, "arguments": args}
                        result = handle_tool_call(store, name, args)
                        yield {"type": "tool_result", "name": name, "result": result}
                        tool_outputs.append({"tool_call_id": call.id, "output": json.dumps(result)})
                    run = client.runs.submit_tool_outputs(thread_id=thread.id, run_id=run.id, tool_outputs=tool_outputs)

            if run.status != "completed":
                yield {"type": "error", "message": f"run ended with status {run.status}"}
                return

            messages = client.messages.list(thread_id=thread.id, limit=5)
            assistant = None
            for m in messages:
                if m.role == "assistant":
                    assistant = m
                    break
            if assistant:
                # Concatenate text content blocks
                text_out = "\n".join(
                    getattr(c, "text", {}).get("value", "") if isinstance(getattr(c, "text", None), dict)
                    else (c.text.value if hasattr(c, "text") and hasattr(c.text, "value") else "")
                    for c in (assistant.content or [])
                )
                yield {"type": "final", "text": text_out, "case_id": case_id}
            else:
                yield {"type": "final", "text": "(no assistant message)", "case_id": case_id}
        except Exception as e:  # noqa: BLE001
            print(f"[agents] live runner failed, falling back to mock: {e}")
            async for evt in self._mock_chat(text=text, persona=persona, case_id=case_id):
                yield evt

    # ── Deterministic mock (offline dev) ───────────────────────────────────

    async def _mock_chat(self, *, text: str, persona: str | None, case_id: str | None) -> AsyncIterator[dict]:
        text_l = text.lower()
        # Routing decision
        if any(w in text_l for w in ["outage", "power out", "no power", "restore"]):
            kind, target = "outage", "ami-outage-detection"
        elif any(w in text_l for w in ["theft", "tamper", "bypass", "suspicious"]):
            kind, target = "theft", "ami-theft-detection"
        elif any(w in text_l for w in ["solar", "inverter", "backfeed", "volt-var", "der"]):
            kind, target = "der", "ami-der-management"
        elif any(w in text_l for w in ["demand response", "heat wave", "peak", "load shed", "shed"]):
            kind, target = "dr", "ami-demand-response"
        elif any(w in text_l for w in ["transformer", "harmonic", "maintenance", "aging"]):
            kind, target = "maintenance", "ami-predictive-maintenance"
        elif any(w in text_l for w in ["bill", "charge", "amount"]):
            kind, target = "billing", "ami-billing-anomaly"
        else:
            kind, target = "inquiry", "ami-customer-service"

        # Open case (or attach)
        if not case_id:
            r = handle_tool_call(store, "open_case", {"kind": kind, "summary": text[:80]})
            case_id = r["case_id"]
            yield {"type": "tool_call", "name": "open_case", "arguments": {"kind": kind}}
            yield {"type": "tool_result", "name": "open_case", "result": r}

        handle_tool_call(store, "record_trace", {
            "case_id": case_id, "agent": ORCHESTRATOR_NAME, "step": "received",
            "status": "started", "payload": {"text": text, "actor": persona},
        })
        yield {"type": "trace", "step": "received"}

        handle_tool_call(store, "record_trace", {
            "case_id": case_id, "agent": ORCHESTRATOR_NAME, "step": "classify",
            "status": "triaging", "payload": {"target": target, "reason": f"keyword match in '{text[:30]}'"},
        })
        yield {"type": "trace", "step": "classify"}

        handle_tool_call(store, "dispatch_to_agent", {
            "target_agent": target, "case_id": case_id, "context": text[:200],
        })
        yield {"type": "tool_call", "name": "dispatch_to_agent", "arguments": {"target_agent": target}}

        # Specialist runs synthetic action
        async for evt in self._mock_specialist(target=target, case_id=case_id, text=text, persona=persona):
            yield evt

        yield {"type": "final", "text": f"Routed to **{target}** — see case `{case_id}` for live trace.", "case_id": case_id}

    async def _mock_specialist(self, *, target: str, case_id: str, text: str, persona: str | None) -> AsyncIterator[dict]:
        sub_id = next(iter(store.substations), "S-01")
        if target == "ami-outage-detection":
            for tool, args in [
                ("group_outage_by_topology", {"substation_id": sub_id}),
                ("correlate_outage_calls", {"substation_id": sub_id, "time_window_min": 10}),
                ("predict_restoration", {"scope": sub_id, "member_count": 120, "weather_severity": 0.4}),
                ("recommend_crew_dispatch", {"scope": sub_id, "eta_minutes": 45}),
            ]:
                r = handle_tool_call(store, tool, args)
                yield {"type": "tool_call", "name": tool, "arguments": args}
                yield {"type": "tool_result", "name": tool, "result": r}
                handle_tool_call(store, "record_trace", {
                    "case_id": case_id, "agent": target, "step": tool,
                    "status": "in_progress", "payload": r,
                })
            handle_tool_call(store, "close_case", {
                "case_id": case_id,
                "summary": "Outage triaged: feeder-level fault, crew dispatched.",
                "recommendation": "Crew Alpha → on-site ETA ~55m",
            })
        elif target == "ami-theft-detection":
            r = handle_tool_call(store, "score_theft", {"scope": {"substation_id": sub_id}})
            yield {"type": "tool_call", "name": "score_theft", "arguments": {"scope": {"substation_id": sub_id}}}
            yield {"type": "tool_result", "name": "score_theft", "result": r}
            handle_tool_call(store, "record_trace", {
                "case_id": case_id, "agent": target, "step": "score", "status": "in_progress", "payload": r,
            })
            handle_tool_call(store, "close_case", {
                "case_id": case_id,
                "summary": f"Found {len(r.get('suspects', []))} candidate theft cases.",
                "recommendation": "Top 3 → field inspection",
            })
        elif target == "ami-der-management":
            r1 = handle_tool_call(store, "get_der_status", {"substation_id": sub_id})
            r2 = handle_tool_call(store, "recommend_volt_var", {"substation_id": sub_id, "affected_meters": r1.get("overvoltage_meters", [])})
            yield {"type": "tool_result", "name": "get_der_status", "result": r1}
            yield {"type": "tool_result", "name": "recommend_volt_var", "result": r2}
            handle_tool_call(store, "close_case", {
                "case_id": case_id,
                "summary": f"{r1['overvoltage_count']} DER meters over-voltage; Volt-VAR curve adjustment proposed (IEEE 1547-2018).",
                "recommendation": json.dumps(r2["proposed_curve"]),
            })
        elif target == "ami-demand-response":
            r = handle_tool_call(store, "compute_demand_response", {"target_mw": 5, "window_minutes": 60, "cohort_filters": ["residential", "opt_in_DR"]})
            yield {"type": "tool_result", "name": "compute_demand_response", "result": r}
            handle_tool_call(store, "close_case", {
                "case_id": case_id,
                "summary": f"DR event staged: {r['cohort_size']} meters → ~{r['projected_shed_mw']} MW for {r['window_minutes']}m.",
                "recommendation": f"Stage event; payment liability ${r['payment_liability_usd']}",
            })
        elif target == "ami-predictive-maintenance":
            r = handle_tool_call(store, "score_transformer_health", {"substation_id": sub_id})
            yield {"type": "tool_result", "name": "score_transformer_health", "result": r}
            handle_tool_call(store, "close_case", {
                "case_id": case_id,
                "summary": f"Bottom 5 transformers identified; {sum(1 for t in r['worst'] if t['health'] < 30)} need urgent inspection.",
                "recommendation": "; ".join(f"{t['transformer_id']}={t['recommended_action']}" for t in r["worst"][:3]),
            })
        elif target == "ami-billing-anomaly":
            sample_meter = next(iter(store.meters))
            r = handle_tool_call(store, "detect_billing_anomaly", {"meter_id": sample_meter, "period_a": "2026-07", "period_b": "2026-08"})
            yield {"type": "tool_result", "name": "detect_billing_anomaly", "result": r}
            handle_tool_call(store, "close_case", {
                "case_id": case_id,
                "summary": f"Bill change ${r['delta_dollars']} (+{round((r['period_b_kwh']/r['period_a_kwh']-1)*100,1)}%); top driver: weather (55%).",
                "recommendation": r["recommendation"],
            })
        else:  # customer-service
            sample_meter = next(iter(store.meters))
            r = handle_tool_call(store, "get_meter", {"meter_id": sample_meter})
            yield {"type": "tool_result", "name": "get_meter", "result": r}
            handle_tool_call(store, "close_case", {
                "case_id": case_id,
                "summary": "Answered customer question with grounded meter data.",
                "recommendation": "n/a",
            })


runner = FoundryAgentRunner()
