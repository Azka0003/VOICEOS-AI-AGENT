"""
action_agent.py — Decision Engine
The ONLY agent that decides what happens next.
Receives unified context + risk verdict. Chooses: call / email / escalate / HITL pause.
Executes the chosen action and writes outcomes to both Excel and ChromaDB.
"""

import json
from datetime import datetime, timedelta

from tools.excel_tool import excel_tool
from tools.chroma_tool import ChromaTool
from tools.hitl_tool import hitl_tool
from tools.twilio_tool import twilio_tool
from tools.comms_logger import comms_logger
from tools.lineage_logger import lineage_logger
from agents.email_agent import EmailAgent

chroma_tool = ChromaTool()
email_agent = EmailAgent()

BASE_URL = "https://your-server.ngrok.io"  # Replace with actual server URL in prod

# ── Demo broadcast hook (set by main.py at startup) ───────────────────────────
# main.py calls ActionAgent.set_broadcast(broadcast_fn) after creating the app.
# This lets action_agent push live events to the SSE stream without circular import.
_broadcast_fn = None


class ActionAgent:
    """
    Decision engine. Reads Next Action from context (sourced from Excel),
    validates it, runs HITL confidence checks, then executes.
    """

    @staticmethod
    def set_broadcast(fn):
        """Called by main.py to inject the SSE broadcast function."""
        global _broadcast_fn
        _broadcast_fn = fn

    async def decide(self, context: dict, risk: dict) -> dict:
        """
        Main entry. Returns a decision result dict describing what was done.
        """

        # ── GATE 1: Protected Next Action values ─────────────────────────────
        # Never override legal or disputed status — humans own these
        next_action = context.get("next_action", "")
        if "legal" in next_action or next_action == "disputed_under_review":
            result = {
                "decision": "blocked",
                "reason": f"Next Action is '{next_action}' — protected value, "
                          f"cannot be overridden by automated agent"
            }
            lineage_logger.log({
                "agent": "action_agent",
                "client": context["client"],
                "decision": "blocked",
                "next_action": next_action
            })
            return result

        # ── GATE 2: HITL confidence check ────────────────────────────────────
        hitl_scenario = risk.get("hitl_scenario")
        confidence = risk.get("confidence", 1.0)

        if hitl_scenario or confidence < 0.5:
            await hitl_tool.trigger(
                scenario=hitl_scenario or "LOW_CONFIDENCE",
                confidence=confidence,
                context=context,
                risk=risk
            )
            return {"decision": "hitl_triggered", "scenario": hitl_scenario}

        # ── GATE 3: Missing contact blocks calls and emails ───────────────────
        if next_action == "resolve_contact_details":
            await hitl_tool.trigger(
                scenario="MISSING_CONTACT",
                confidence=0.0,
                context=context,
                risk=risk
            )
            return {"decision": "hitl_triggered", "scenario": "MISSING_CONTACT"}

        # ── GATE 4: Route to action ───────────────────────────────────────────
        if next_action in ("schedule_call", "send_call"):
            return await self._execute_call(context, risk)

        elif next_action in (
            "send_friendly_reminder",
            "send_urgent_followup",
            "send_final_notice"
        ):
            tone_map = {
                "send_friendly_reminder": "friendly_reminder",
                "send_urgent_followup": "urgent_followup",
                "send_final_notice": "final_notice"
            }
            return await self._execute_email(context, risk, tone_map[next_action])

        elif next_action == "escalate_to_legal":
            return await self._execute_escalation(context, risk)

        else:
            # Unrecognised action — safe to HITL rather than guess
            await hitl_tool.trigger(
                scenario="UNKNOWN_NEXT_ACTION",
                confidence=0.3,
                context=context,
                risk=risk
            )
            return {"decision": "hitl_triggered", "scenario": "UNKNOWN_NEXT_ACTION"}

    # ── Call execution ────────────────────────────────────────────────────────

    async def _execute_call(self, context: dict, risk: dict) -> dict:
        """
        Uses demo_actions.demo_call — places a real Twilio call if creds exist,
        otherwise runs a live simulated transcript through SSE so judges see
        the Call Monitor tab light up in real time.
        """
        from demo_actions import demo_call

        async def _noop(ev): pass
        broadcast = _broadcast_fn if _broadcast_fn else _noop

        return await demo_call(context, risk, broadcast)

    async def handle_call_webhook(
        self,
        context: dict,
        call_outcome: str,
        payment_commitment: str | None,
        notes: str
    ):
        """
        Called by the Twilio/Deepgram webhook after a call ends.
        Updates both Excel and ChromaDB based on the extracted call outcome.
        """
        await self._post_call_update(context, call_outcome, payment_commitment, notes)

    async def _post_call_update(
        self,
        context: dict,
        call_outcome: str,
        payment_commitment: str | None,
        notes: str
    ):
        """
        Dual-store write after every call, regardless of outcome.
        Excel: Next Action + contact log
        ChromaDB: metadata fields
        """
        client = context["client"]
        invoice_ids = [inv["id"] for inv in context["invoices"]]

        # Determine next Excel action from call outcome
        if call_outcome == "confirmed" and payment_commitment:
            next_action = f"await_payment_{payment_commitment}"
        elif call_outcome == "confirmed" and not payment_commitment:
            next_action = "send_urgent_followup"
        elif call_outcome == "wrong_person":
            follow_up_date = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
            next_action = f"follow_up_{follow_up_date}"
        elif call_outcome == "wrong_number":
            next_action = "resolve_contact_details"
            # Also alert HITL — contact data is corrupted
            await hitl_tool.trigger(
                scenario="WRONG_NUMBER",
                confidence=0.0,
                context=context,
                risk={}
            )
        elif call_outcome == "no_response":
            next_action = "schedule_call"  # Retry; contact_count NOT incremented
        else:
            next_action = "send_urgent_followup"

        # Update Excel for every invoice of this client
        for inv_id in invoice_ids:
            excel_tool.update_next_action(inv_id, next_action, "action_agent")
            if call_outcome != "no_response":
                excel_tool.log_contact_made(
                    invoice_id=inv_id,
                    contact_type="call",
                    outcome=call_outcome,
                    agent_name="action_agent"
                )

        # Update ChromaDB metadata (never overwrites page_content)
        new_contact_count = context["contact_count"] + (
            0 if call_outcome == "no_response" else 1
        )
        chroma_tool.update_client_metadata(client, {
            "last_contact_date": datetime.now().isoformat(),
            "last_contact_type": "call",
            "contact_count": new_contact_count,
            "next_action": next_action
        })

        # Persist full contact record
        comms_logger.log(client, {
            "type": "call",
            "timestamp": datetime.now().isoformat(),
            "outcome": call_outcome,
            "payment_commitment": payment_commitment,
            "notes": notes,
            "next_action_suggested": next_action
        })

        lineage_logger.log({
            "agent": "action_agent",
            "client": client,
            "event": "post_call_update",
            "call_outcome": call_outcome,
            "next_action": next_action
        })

    # ── Email execution ───────────────────────────────────────────────────────

    async def _execute_email(self, context: dict, risk: dict, requested_tone: str) -> dict:
        """
        Uses demo_actions.demo_email — sends a real Gmail email if SMTP creds exist,
        otherwise simulates and fires SSE events so the Agent Feed updates live.
        """
        from demo_actions import demo_email

        async def _noop(ev): pass
        broadcast = _broadcast_fn if _broadcast_fn else _noop

        result = await demo_email(context, requested_tone, broadcast)
        return {"decision": "email_sent", "email_result": result}

    # ── Escalation ────────────────────────────────────────────────────────────

    async def _execute_escalation(self, context: dict, risk: dict) -> dict:
        """
        Marks the client for legal escalation in both stores and triggers HITL.
        Action Agent does NOT initiate legal action — it flags for human review.
        """
        client = context["client"]

        for inv in context["invoices"]:
            excel_tool.update_next_action(inv["id"], "escalate_to_legal", "action_agent")

        chroma_tool.update_client_metadata(client, {
            "next_action": "escalate_to_legal",
            "hitl_required": True
        })

        await hitl_tool.trigger(
            scenario="LEGAL_ESCALATION",
            confidence=1.0,
            context=context,
            risk=risk
        )

        lineage_logger.log({
            "agent": "action_agent",
            "client": client,
            "decision": "escalated_to_legal"
        })

        return {
            "decision": "escalated_to_legal",
            "note": "HITL notified. Human must review before legal action is initiated."
        }
