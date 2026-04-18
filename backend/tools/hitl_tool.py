import os
import json
import asyncio
import secrets
from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
LINEAGE_LOG_PATH = os.path.join(DATA_DIR, "lineage_log.json")

os.makedirs(DATA_DIR, exist_ok=True)
if not os.path.exists(LINEAGE_LOG_PATH):
    with open(LINEAGE_LOG_PATH, "w") as f:
        json.dump([], f)


def get_days_since_last_contact(comms_history: list) -> float | None:
    if not comms_history:
        return None
    latest = None
    for c in comms_history:
        if "timestamp" in c:
            try:
                dt = datetime.fromisoformat(c["timestamp"].replace("Z", "+00:00"))
                if latest is None or dt > latest:
                    latest = dt
            except ValueError:
                pass
    if latest:
        return (datetime.now(timezone.utc) - latest).total_seconds() / 86400.0
    return None


def compute_confidence(invoice: dict, comms_history: list, planned_action: str) -> float:
    score = 1.0

    if not invoice.get("contact_name"):
        score -= 0.4

    if invoice.get("dispute_flag"):
        score -= 0.35

    if invoice.get("days_overdue", 0) > 60 and invoice.get("risk_score", 100) < 40:
        score -= 0.45

    if invoice.get("amount", 0) > 50000 and invoice.get("days_overdue", 0) > 45:
        score -= 0.2

    days_since_last_contact = get_days_since_last_contact(comms_history)
    if days_since_last_contact is not None and days_since_last_contact < 3:
        score -= 0.25

    return max(0.0, round(score, 2))


class HITLManager:
    def __init__(self):
        self.pending_actions = {}
        self.events = {}

    def _log_lineage(self, entry: dict):
        try:
            with open(LINEAGE_LOG_PATH, "r") as f:
                logs = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            logs = []
        if "timestamp" not in entry:
            entry = {"timestamp": datetime.now(timezone.utc).isoformat(), **entry}
        logs.append(entry)
        with open(LINEAGE_LOG_PATH, "w") as f:
            json.dump(logs, f, indent=2)

    async def trigger(self, scenario: str, confidence: float, context: dict, risk: dict) -> dict:
        client = context.get("client", "Unknown Client")
        amount = context.get("total_outstanding", 0)
        days_overdue = context.get("max_days_overdue", 0)
        risk_score = risk.get("risk_score", 50)
        risk_label = risk.get("risk_label", "Medium")
        contact_name = context.get("contact_name")
        dispute_flag = context.get("dispute_flag", False)
        
        reason = f"Agent triggered HITL pause for {client}. Scenario: {scenario}. Confidence: {confidence}."
        
        checkpoint_id = f"hitl_{client.lower().replace(' ', '_')}_{secrets.token_hex(3)}"
        
        checkpoint = {
            "checkpoint_id": checkpoint_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
            "trigger": {
                "scenario_code": scenario,
                "human_readable_reason": reason,
                "confidence_before_pause": confidence,
                "would_have_done": "unknown"
            },
            "invoice_context": {
                "client": client,
                "invoice_id": context.get("invoices", [{}])[0].get("id", "Unknown") if context.get("invoices") else "Unknown",
                "amount": amount,
                "days_overdue": days_overdue,
                "risk_score": risk_score,
                "risk_label": risk_label,
                "dispute_flag": dispute_flag,
                "contact_name": contact_name or None,
                "contact_email": context.get("contact_email")
            },
            "comms_history_summary": {
                "total_contacts": context.get("contact_count", 0),
                "last_contact_type": "none",
                "last_contact_date": None,
                "last_tone": "none"
            },
            "options_for_human": [
                {
                    "option_id": "provide_contact",
                    "label": "Provide correct contact name and proceed",
                    "requires_input": {"contact_name": "string"}
                },
                {
                    "option_id": "proceed_anyway",
                    "label": "Proceed anyway, accept the risk",
                    "requires_input": None
                },
                {
                    "option_id": "skip",
                    "label": "Skip this client for now, revisit in 2 days",
                    "requires_input": None
                },
                {
                    "option_id": "cancel",
                    "label": "Cancel this action entirely",
                    "requires_input": None
                }
            ],
            "resolution": None,
            "resolved_at": None,
            "resolved_by": "human"
        }

        self.pending_actions[checkpoint_id] = checkpoint
        self.events[checkpoint_id] = asyncio.Event()

        self._log_lineage({
            "agent": "action_agent",
            "action": "HITL checkpoint created",
            "hitl_triggered": True,
            "hitl_scenario": scenario,
            "confidence": confidence,
            "checkpoint_id": checkpoint_id
        })

        print(f"\n[HITL PAUSED] Confidence: {confidence} | Scenario: {scenario}\n[REASON] {reason}\n")

        await self.events[checkpoint_id].wait()
        return self.pending_actions[checkpoint_id]["resolution"]

    async def evaluate_and_wait(self, invoice: dict, comms_history: list, planned_action: str) -> dict:
        confidence = compute_confidence(invoice, comms_history, planned_action)

        client       = invoice.get("client", "Unknown Client")
        amount       = invoice.get("amount", 0)
        days_overdue = invoice.get("days_overdue", 0)
        risk_score   = invoice.get("risk_score", 50)
        contact_name = (invoice.get("contact_name") or "").strip()
        contact_phone= invoice.get("contact_phone", "")
        dispute_flag = invoice.get("dispute_flag", False)
        next_action_excel = invoice.get("next_action", "")
        invoice_id   = invoice.get("invoice_id", "Unknown")
        risk_label   = invoice.get("risk_label", "High" if risk_score > 70 else "Low" if risk_score < 40 else "Medium")

        action_lower  = planned_action.lower()
        is_email      = "email" in action_lower
        is_call       = "call" in action_lower
        is_aggressive = any(t in action_lower for t in ["aggressive", "final notice", "final_notice", "escalated"])

        amount_str = f"₹{amount:,.0f}" if amount else "₹0"

        # FIX: generic_terms no longer includes "" — empty string meant every
        # client with a missing name triggered MISSING_CONTACT even when
        # ChromaDB simply hadn't loaded yet. Now we only trigger when the name
        # is truly absent (None / empty after strip).
        GENERIC_TERMS = {"accounts", "finance team", "admin", "billing", "info"}
        is_generic = contact_name.lower() in GENERIC_TERMS
        is_missing  = not contact_name  # empty string or None

        triggered     = False
        scenario_code = None
        reason        = None

        # SCENARIO 1: Contact person is missing or a known generic placeholder
        if is_missing or is_generic:
            triggered     = True
            scenario_code = "MISSING_CONTACT"
            reason = (
                f"Cannot confirm decision-maker at {client}. "
                f"Invoice {amount_str}, {days_overdue} days overdue. "
                f"Sending to a generic inbox risks non-delivery to an authorised person. "
                f"Please confirm the contact name before proceeding."
            )

        # SCENARIO 2: High-value + long overdue
        elif amount > 50000 and days_overdue > 45:
            triggered     = True
            scenario_code = "HIGH_STAKES_OVERDUE"
            reason = (
                f"High-value invoice ({amount_str}) at {days_overdue} days overdue for {client}. "
                f"Risk score: {risk_score} ({risk_label}). "
                f"Recommend human review of tone before sending."
            )

        # SCENARIO 3: Active dispute + aggressive action
        elif dispute_flag and (is_email or is_call) and is_aggressive:
            triggered     = True
            scenario_code = "ACTIVE_DISPUTE"
            reason = (
                f"{client} has an active dispute on {invoice_id}. "
                f"Sending escalated communication during an unresolved dispute could "
                f"create legal liability. Human must confirm dispute is resolved first."
            )

        else:
            days_since_last = get_days_since_last_contact(comms_history)

            # SCENARIO 4: Contacted too recently
            if days_since_last is not None and days_since_last < 3 and is_email:
                triggered     = True
                scenario_code = "CONTACT_HISTORY_CONFLICT"
                last_ts = comms_history[-1].get("timestamp", "unknown") if comms_history else "unknown"
                reason = (
                    f"A message was already sent to {client} {int(days_since_last)} day(s) ago "
                    f"(timestamp: {last_ts}). Sending again this quickly may damage deliverability "
                    f"and client relationship. Confirm whether to proceed or wait."
                )

            # SCENARIO 5: Phone number is a known demo/test number shared across clients
            # FIX: Removed the hard-coded "+919634143593 belongs to Raj Traders" check.
            # In the demo dataset every client shares one phone number — that is intentional
            # per the architecture doc ("all clients share one phone number"). This scenario
            # should only fire when the number is literally a placeholder like 0000000000.
            elif contact_phone in ("0000000000", "1234567890", "9999999999", ""):
                triggered     = True
                scenario_code = "DATA_ERROR_PHONE"
                reason = (
                    f"Phone number for {client} appears to be a placeholder ({contact_phone}). "
                    f"Proceeding would call an invalid number. Human must correct it first."
                )

            # SCENARIO 6: Excel says legal but agent about to email/call
            elif "legal" in str(next_action_excel).lower() and (is_email or is_call):
                triggered     = True
                scenario_code = "LEGAL_ESCALATION_CONFLICT"
                reason = (
                    f"{client} has already been flagged for legal escalation in Excel. "
                    f"Sending a routine message would contradict that status and may interfere "
                    f"with legal proceedings. Human must confirm whether to override."
                )

            # SCENARIO 7: Contradictory risk score
            elif days_overdue > 60 and risk_score < 40:
                triggered     = True
                scenario_code = "CONTRADICTORY_RISK_SCORE"
                reason = (
                    f"Data inconsistency for {client}: {days_overdue} days overdue but risk "
                    f"score is {risk_score} (Low). Risk score may be stale. Human must trigger "
                    f"a recalculation or manually confirm the correct tone."
                )

        # Meta-check: low confidence fallback
        if not triggered and confidence < 0.5:
            triggered     = True
            scenario_code = "LOW_CONFIDENCE_FALLBACK"
            reason = (
                f"System confidence fell below threshold (score: {confidence}). "
                f"Manual review required."
            )

        # Auto-proceed
        if not triggered:
            self._log_lineage({
                "hitl_triggered": False,
                "hitl_evaluated": True,
                "confidence": confidence,
                "client": client,
                "reason_not_triggered": "All conditions clear."
            })
            return {"option_id": "auto_proceed"}

        # Build checkpoint
        checkpoint_id = f"hitl_{client.lower().replace(' ', '_')}_{secrets.token_hex(3)}"

        last_contact = comms_history[-1] if comms_history else {}
        comms_summary = {
            "total_contacts": len(comms_history),
            "last_contact_type": last_contact.get("type", "none"),
            "last_contact_date": last_contact.get("timestamp"),
            "last_tone": last_contact.get("tone", "none")
        }

        checkpoint = {
            "checkpoint_id": checkpoint_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
            "trigger": {
                "scenario_code": scenario_code,
                "human_readable_reason": reason,
                "confidence_before_pause": confidence,
                "would_have_done": planned_action
            },
            "invoice_context": {
                "client": client,
                "invoice_id": invoice_id,
                "amount": amount,
                "days_overdue": days_overdue,
                "risk_score": risk_score,
                "risk_label": risk_label,
                "dispute_flag": dispute_flag,
                "contact_name": contact_name or None,
                "contact_email": invoice.get("contact_email")
            },
            "comms_history_summary": comms_summary,
            "options_for_human": [
                {
                    "option_id": "provide_contact",
                    "label": "Provide correct contact name and proceed",
                    "requires_input": {"contact_name": "string"}
                },
                {
                    "option_id": "proceed_anyway",
                    "label": "Proceed anyway, accept the risk",
                    "requires_input": None
                },
                {
                    "option_id": "skip",
                    "label": "Skip this client for now, revisit in 2 days",
                    "requires_input": None
                },
                {
                    "option_id": "cancel",
                    "label": "Cancel this action entirely",
                    "requires_input": None
                }
            ],
            "resolution": None,
            "resolved_at": None,
            "resolved_by": "human"
        }

        self.pending_actions[checkpoint_id] = checkpoint
        self.events[checkpoint_id] = asyncio.Event()

        self._log_lineage({
            "agent": "hitl_manager",
            "action": "HITL checkpoint created",
            "hitl_triggered": True,
            "hitl_scenario": scenario_code,
            "confidence": confidence,
            "checkpoint_id": checkpoint_id
        })

        print(f"\n[HITL PAUSED] Confidence: {confidence} | Scenario: {scenario_code}\n[REASON] {reason}\n")

        await self.events[checkpoint_id].wait()
        return self.pending_actions[checkpoint_id]["resolution"]

    def resolve_checkpoint(self, checkpoint_id: str, resolution_data: dict):
        if checkpoint_id not in self.pending_actions:
            print(f"[HITL] Warning: unknown checkpoint {checkpoint_id}")
            return

        checkpoint = self.pending_actions[checkpoint_id]
        if checkpoint["status"] == "resolved":
            return

        checkpoint["status"]      = "resolved"
        checkpoint["resolution"]  = resolution_data
        checkpoint["resolved_at"] = datetime.now(timezone.utc).isoformat()
        checkpoint["resolved_by"] = "human"

        client    = checkpoint["invoice_context"]["client"]
        option_id = resolution_data.get("option_id")

        if option_id == "provide_contact":
            new_contact = resolution_data.get("inputs", {}).get("contact_name", "Unknown")
            print(f"[HITL] {client} → contact set to '{new_contact}'. Resuming.")
        elif option_id == "proceed_anyway":
            print(f"[HITL] {client} → human override. Resuming.")
            self._log_lineage({"agent": "hitl_manager", "action": "human_override", "checkpoint_id": checkpoint_id})
        elif option_id == "skip":
            print(f"[HITL] {client} → skipped.")
        elif option_id == "cancel":
            print(f"[HITL] {client} → cancelled.")

        self._log_lineage({
            "agent": "hitl_manager",
            "action": "HITL checkpoint resolved",
            "checkpoint_id": checkpoint_id,
            "resolution": resolution_data
        })

        if checkpoint_id in self.events:
            self.events[checkpoint_id].set()

    def get_all_pending(self) -> list:
        return [r for r in self.pending_actions.values() if r["status"] == "pending"]


hitl_manager = HITLManager()
hitl_tool = hitl_manager