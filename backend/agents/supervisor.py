"""
supervisor.py — Orchestration Layer
Reads the Excel task queue, routes each client through the full agent pipeline.
Never makes collections decisions. Never sends emails or places calls itself.
"""

import asyncio
import datetime
from tools.excel_tool import excel_tool
from tools.chroma_tool import ChromaTool
from tools.hitl_tool import hitl_tool
from tools.lineage_logger import lineage_logger
from agents.invoice_agent import InvoiceAgent
from agents.risk_agent import RiskAgent
from agents.action_agent import ActionAgent

chroma_tool = ChromaTool()
invoice_agent = InvoiceAgent()
risk_agent = RiskAgent()
action_agent = ActionAgent()


class SupervisorAgent:
    """
    The only agent that sees the full picture.
    Orchestrates the pipeline — does NOT make collections decisions.
    """

    async def run_batch(self):
        """
        Entry point for every scheduled batch run.
        Reads the Excel task queue, processes each actionable client in priority order.
        """
        actionable_rows = excel_tool.get_next_actions()
        # Rows are pre-sorted by priority:
        # escalate_to_legal → final_notice → urgent_followup →
        # schedule_call → friendly_reminder → follow_up (date passed) →
        # resolve_contact_details

        print(f"[SUPERVISOR] Batch started. {len(actionable_rows)} actionable rows found.")

        results = []
        for row in actionable_rows:
            # Concurrency lock: prevents double-processing in parallel runs
            if not self._acquire_client_lock(row["id"]):
                print(f"[SUPERVISOR] Skipping {row['client']} — already being processed.")
                continue

            result = await self._process_client(row)
            results.append(result)

        print(f"[SUPERVISOR] Batch complete. {len(results)} clients processed.")
        return results

    def _acquire_client_lock(self, invoice_id: str) -> bool:
        """
        Sets a 'processing' lock in Excel before handling a client.
        Returns False if another run already holds the lock.
        """
        current = excel_tool.get_invoice_by_id(invoice_id)
        if not current:
            return False
        if current.get("next_action") == "processing":
            return False  # Another run has this client
        excel_tool.update_next_action(invoice_id, "processing", "supervisor")
        return True

    async def _process_client(self, excel_row: dict) -> dict:
        """
        Full pipeline for a single client row from the Excel task queue.
        """
        client_name = excel_row["client"]
        invoice_id = excel_row["id"]

        print(f"[SUPERVISOR] Processing client: {client_name} (invoice: {invoice_id})")

        # ── Step 1: ChromaDB identity check ──────────────────────────────────
        # Identity and history MUST come from ChromaDB — never invented by LLM
        briefing = chroma_tool.get_client_briefing(client_name)
        if not briefing:
            print(f"[SUPERVISOR] ChromaDB MISS for {client_name} — triggering HITL.")
            hitl_tool.trigger(
                scenario="CHROMADB_MISS",
                reason=f"No ChromaDB document found for {client_name}. "
                       f"Cannot proceed without verified client data.",
                invoice_context=excel_row,
                confidence=0.0
            )
            # Restore the Next Action so this row isn't stuck as 'processing'
            excel_tool.update_next_action(invoice_id, excel_row["next_action"], "supervisor")
            return {"client": client_name, "status": "hitl_triggered", "reason": "CHROMADB_MISS"}

        # ── Step 2: Invoice Agent builds unified context ──────────────────────
        context = invoice_agent.get_client_context(client_name)
        if context.get("error"):
            hitl_tool.trigger(
                scenario=context["error"],
                reason=f"Invoice Agent returned error for {client_name}.",
                invoice_context=excel_row,
                confidence=0.0
            )
            excel_tool.update_next_action(invoice_id, excel_row["next_action"], "supervisor")
            return {"client": client_name, "status": "hitl_triggered", "reason": context["error"]}

        # ── Step 3: Risk Agent evaluates ──────────────────────────────────────
        risk_result = await risk_agent.evaluate(context)

        # ── Step 4: Action Agent decides and executes ─────────────────────────
        action_result = await action_agent.decide(context, risk_result)

        # ── Step 5: Lineage logging ───────────────────────────────────────────
        lineage_logger.log({
            "agent": "supervisor",
            "client": client_name,
            "invoice_id": invoice_id,
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "risk_result": risk_result,
            "action_decided": action_result
        })

        print(f"[SUPERVISOR] Done: {client_name} → {action_result.get('decision', 'unknown')}")
        return {
            "client": client_name,
            "status": "processed",
            "risk": risk_result,
            "action": action_result
        }

    def process_client_sync(self, client_name: str) -> dict:
        """
        Synchronous wrapper for single-client processing (used in tests/CLI).
        Finds the most urgent invoice row for this client and runs the pipeline.
        """
        rows = excel_tool.get_invoices_by_client(client_name)
        if not rows:
            return {"error": f"Client '{client_name}' not found in Excel."}
        # Use the most-overdue invoice row as the trigger
        rows.sort(key=lambda r: r["days_overdue"], reverse=True)
        return asyncio.run(self._process_client(rows[0]))


# ── CLI test harness ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    supervisor = SupervisorAgent()

    print("=== Running full batch ===")
    asyncio.run(supervisor.run_batch())