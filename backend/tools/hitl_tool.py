import os
import json
import asyncio
import secrets
from datetime import datetime, timezone

# Ensure the data directory exists
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
LINEAGE_LOG_PATH = os.path.join(DATA_DIR, "lineage_log.json")

os.makedirs(DATA_DIR, exist_ok=True)
if not os.path.exists(LINEAGE_LOG_PATH):
    with open(LINEAGE_LOG_PATH, "w") as f:
        json.dump([], f)


class HITLManager:
    """
    Smart Human-in-the-Loop (HITL) Manager for DebtPilot.
    Pauses agent execution only when specific thresholds or logic conditions are met.
    """

    def __init__(self):
        self.pending_actions = {}
        self.events = {}  # Keeps asyncio.Events separate from serializable data
        
        # Internal stats tracking
        self.stats = {
            "total_triggered": 0,
            "total_resolved": 0,
            "total_pending": 0,
            "total_resolve_time_seconds": 0.0,
            "auto_proceeded": 0
        }

    def should_pause(self, context: dict) -> tuple[bool, str | None]:
        """
        Evaluates strict business logic to determine if a human is needed.
        Returns (True, reason) if HITL is required, otherwise (False, None).
        Evaluates exactly in the order specified.
        """
        client = context.get("client", "Unknown Client")
        contact_name = context.get("contact_name")
        risk_score = context.get("risk_score", 0)
        amount = context.get("amount", 0)
        days_overdue = context.get("days_overdue", 0)
        invoice_id = context.get("invoice_id", "Unknown")
        dispute_flag = context.get("dispute_flag", False)
        email_tone = context.get("email_tone", "")
        prior_human_reviews = context.get("prior_human_reviews", 0)

        # CONDITION 1 — Missing Contact
        if contact_name is None or str(contact_name).strip() == "":
            reason = (
                f"Contact person is missing for {client}. Cannot proceed "
                f"without a verified recipient. Invoice: {invoice_id}, "
                f"Amount: ₹{amount}, Days Overdue: {days_overdue}"
            )
            return True, reason

        # CONDITION 2 — High Risk Score
        if risk_score >= 71:
            payment_history = context.get("payment_history",[])
            history_summary = ", ".join(payment_history) if payment_history else "No history available"
            dispute_str = "yes" if dispute_flag else "no"
            reason = (
                f"Client {client} has a HIGH risk score ({risk_score}/100). "
                f"History: {history_summary}. Dispute on file: {dispute_str}. "
                f"Recommend human review before contact."
            )
            return True, reason

        # CONDITION 3 — Large Amount + Significantly Overdue
        if amount > 50000 and days_overdue > 30:
            reason = (
                f"Invoice {invoice_id} for ₹{amount} is {days_overdue} days "
                f"overdue. Amount exceeds ₹50,000 threshold. Human sign-off "
                f"required before automated contact."
            )
            return True, reason

        # CONDITION 4 — Dispute Flag Active
        if dispute_flag is True:
            reason = (
                f"Active dispute flag on {client} account. Automated contact "
                f"during a live dispute could create legal liability. Human "
                f"must review before any communication."
            )
            return True, reason

        # CONDITION 5 — Final Notice Tone on First Automated Run
        if email_tone == "final_notice" and prior_human_reviews == 0:
            reason = (
                "This would be a Final Notice email but no human has "
                "reviewed this client before. First Final Notice requires "
                "human approval."
            )
            return True, reason

        # No conditions met; agent can proceed safely
        self.stats["auto_proceeded"] += 1
        return False, None

    async def wait_for_human(self, checkpoint_type: str, context: dict, reason: str) -> dict:
        """
        Creates a pending checkpoint, suspends the caller via asyncio.Event,
        and returns the human response once resolved.
        """
        # 1. Generate unique checkpoint ID
        checkpoint_id = f"HITL-{checkpoint_type.upper()}-{secrets.token_hex(3)}"

        # Determine System Confidence
        risk_score = context.get("risk_score", 0)
        if risk_score > 70:
            confidence = "low"
        elif 41 <= risk_score <= 70:
            confidence = "medium"
        else:
            confidence = "high"

        # Determine Suggested Action based on the context/reason
        if "Contact person is missing" in reason:
            suggested_action = "Locate contact details and provide below"
        elif "HIGH risk score" in reason:
            suggested_action = "Review client history and approve or escalate"
        elif "Amount exceeds" in reason:
            suggested_action = "Confirm automated contact is appropriate"
        elif "Active dispute" in reason:
            suggested_action = "Check with legal team before proceeding"
        elif "Final Notice" in reason:
            suggested_action = "Review and approve final notice"
        else:
            suggested_action = "Review and provide response"

        # 2. Create checkpoint record
        record = {
            "id": checkpoint_id,
            "type": checkpoint_type,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "context": context,
            "reason": reason,
            "confidence": confidence,
            "suggested_action": suggested_action,
            "response": None,
            "resolved_at": None
        }

        # 3. Store checkpoint and event
        self.pending_actions[checkpoint_id] = record
        self.events[checkpoint_id] = asyncio.Event()

        self.stats["total_triggered"] += 1
        self.stats["total_pending"] += 1

        print(f"[HITL] Checkpoint created: {checkpoint_id} | Reason: {reason}")

        # 4. Wait for human intervention
        await self.events[checkpoint_id].wait()

        # 5. Return human's response
        return self.pending_actions[checkpoint_id]["response"]

    def resolve_checkpoint(self, checkpoint_id: str, response: dict):
        """
        Resolves a pending checkpoint, logs the decision, and wakes up the sleeping agent.
        """
        if checkpoint_id not in self.pending_actions:
            print(f"[HITL] Warning: Cannot resolve unknown checkpoint {checkpoint_id}")
            return

        record = self.pending_actions[checkpoint_id]
        if record["status"] == "resolved":
            return

        now = datetime.now(timezone.utc)
        created_at = datetime.fromisoformat(record["created_at"])
        time_to_resolve_seconds = (now - created_at).total_seconds()

        # 1-3. Merge response and resolve status
        record["status"] = "resolved"
        record["resolved_at"] = now.isoformat()
        record["response"] = response

        # 4. Increment human review counter
        record["context"]["prior_human_reviews"] = record["context"].get("prior_human_reviews", 0) + 1

        # Update stats
        self.stats["total_pending"] -= 1
        self.stats["total_resolved"] += 1
        self.stats["total_resolve_time_seconds"] += time_to_resolve_seconds

        # 6. Log entry to lineage tracker safely
        log_entry = {
            "timestamp": now.isoformat(),
            "agent": "hitl_manager",
            "action": "checkpoint_resolved",
            "checkpoint_id": checkpoint_id,
            "reason_paused": record["reason"],
            "human_response": response,
            "time_to_resolve_seconds": time_to_resolve_seconds,
            "hitl_triggered": True,
            "hitl_reason": record["reason"]
        }

        try:
            with open(LINEAGE_LOG_PATH, "r") as f:
                logs = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            logs =[]

        logs.append(log_entry)

        with open(LINEAGE_LOG_PATH, "w") as f:
            json.dump(logs, f, indent=2)

        print(f"[HITL] Checkpoint resolved: {checkpoint_id} in {time_to_resolve_seconds:.1f}s")

        # 5. Unblock the waiting task
        if checkpoint_id in self.events:
            self.events[checkpoint_id].set()

    def get_all_pending(self) -> list:
        """Returns a list of all currently pending checkpoints (without asyncio Events)."""
        return[
            record for record in self.pending_actions.values() 
            if record["status"] == "pending"
        ]

    def get_checkpoint(self, checkpoint_id: str) -> dict | None:
        """Returns a single checkpoint."""
        return self.pending_actions.get(checkpoint_id)

    def get_stats(self) -> dict:
        """Returns statistics on HITL activity."""
        total_res = self.stats["total_resolved"]
        avg_time = self.stats["total_resolve_time_seconds"] / total_res if total_res > 0 else 0.0
        
        return {
            "total_triggered": self.stats["total_triggered"],
            "total_resolved": total_res,
            "total_pending": self.stats["total_pending"],
            "avg_resolve_time_seconds": avg_time,
            "auto_proceeded": self.stats["auto_proceeded"]
        }

# Singleton instance exported for use across the application
hitl_manager = HITLManager()