"""
invoice_agent.py — Data Assembler
Pulls from ChromaDB (identity, history, briefing) AND Excel (numbers, task status).
Never makes decisions. Returns a single unified context object for all downstream agents.
"""

from tools.excel_tool import excel_tool
from tools.chroma_tool import chroma_tool


class InvoiceAgent:
    """
    Assembles the unified context object that every downstream agent relies on.
    Two mandatory sources: ChromaDB (identity/history) + Excel (numbers/status).
    """

    def get_client_context(self, client_name: str) -> dict:
        """
        Primary method. Queries both data sources and merges into one context dict.
        Returns {"error": "CHROMADB_MISS"} if ChromaDB has no record — never proceeds blind.
        """

        # ── SOURCE 1: ChromaDB ─────────────────────────────────────────────────
        # Identity, history, briefing text, tone guidance, contact details
        chroma_result = chroma_tool.get_client_briefing(client_name)

        if not chroma_result:
            return {"error": "CHROMADB_MISS", "client": client_name}

        briefing_text = chroma_result["page_content"]
        metadata = chroma_result["metadata"]

        # ── SOURCE 2: Excel ────────────────────────────────────────────────────
        # Current numbers, recalculated days_overdue, Next Action column, contact count
        # days_overdue is ALWAYS recalculated by excel_tool on read — never trust stored value
        excel_rows = excel_tool.get_invoices_by_client(client_name)

        if not excel_rows:
            return {"error": "EXCEL_MISS", "client": client_name}

        total_outstanding = sum(r["amount"] for r in excel_rows)
        max_days_overdue = max(r["days_overdue"] for r in excel_rows)

        # ── MERGE into unified context ─────────────────────────────────────────
        return {
            "client": client_name,
            # Contact fields from ChromaDB (authoritative for identity)
            "contact_name": metadata.get("contact_name"),
            "contact_email": metadata.get("contact_email"),
            "contact_phone": metadata.get("contact_phone"),
            # ChromaDB narrative — injected as LLM system prompt for calls/emails
            "briefing_text": briefing_text,
            # Risk fields from ChromaDB metadata
            "risk_score": metadata.get("risk_score", 0),
            "risk_label": metadata.get("risk_label", "Unknown"),
            "dispute_flag": metadata.get("dispute_flag", False),
            # Aggregated numbers from Excel (always freshly calculated)
            "total_outstanding": total_outstanding,
            "max_days_overdue": max_days_overdue,
            "invoice_count": len(excel_rows),
            "invoices": excel_rows,
            # Task + contact history — Excel is authoritative for these
            "next_action": excel_rows[0]["next_action"],
            "contact_count": metadata.get("contact_count", excel_rows[0].get("contact_count", 0)),
            "last_contact_date": metadata.get("last_contact_date", excel_rows[0].get("last_contact_date", "Never")),
            "last_contact_type": metadata.get("last_contact_type", excel_rows[0].get("last_contact_type", "none")),
            # HITL flag from ChromaDB
            "hitl_required": metadata.get("hitl_required", False)
        }

    # ── Portfolio aggregation (Excel only, no ChromaDB) ───────────────────────

    def get_portfolio_summary(self) -> dict:
        """
        Dashboard-level stats. Aggregates directly from Excel — no ChromaDB.
        Called by dashboard and supervisor for overview metrics.
        """
        invoices = excel_tool.get_all_invoices()
        summary = {
            "total_outstanding": sum(inv["amount"] for inv in invoices),
            "count_by_risk": {
                "High": sum(1 for inv in invoices if inv["risk_label"] == "High"),
                "Medium": sum(1 for inv in invoices if inv["risk_label"] == "Medium"),
                "Low": sum(1 for inv in invoices if inv["risk_label"] == "Low"),
            },
            "count_by_next_action": {},
            "hitl_flagged_clients": [],
            "overdue_gt_60": sum(1 for inv in invoices if inv["days_overdue"] > 60),
            "avg_days_overdue": (
                round(sum(inv["days_overdue"] for inv in invoices) / len(invoices), 1)
                if invoices else 0
            )
        }

        for inv in invoices:
            action = inv["next_action"]
            if action:
                summary["count_by_next_action"][action] = (
                    summary["count_by_next_action"].get(action, 0) + 1
                )
            if inv.get("hitl_required") or not inv.get("contact_name"):
                if inv["client"] not in summary["hitl_flagged_clients"]:
                    summary["hitl_flagged_clients"].append(inv["client"])

        return summary

    def get_client_data(self, client_name: str) -> dict | None:
        """
        Backward-compatible method for main.py.
        Maps the unified context shape to the flat dict main.py expects.
        """
        ctx = self.get_client_context(client_name)

        if not ctx or ctx.get("error"):
            return None

        invoices = ctx.get("invoices", [])
        latest_invoice_id = invoices[0]["id"] if invoices else "INV_UNKNOWN"

        comms_history = []
        if ctx.get("last_contact_date") and ctx["last_contact_date"] != "Never":
            comms_history.append({
                "type": ctx.get("last_contact_type", "unknown"),
                "date": ctx["last_contact_date"],
                "contact_count": ctx.get("contact_count", 0)
            })

        return {
            "total_due": ctx["total_outstanding"],
            "max_days_overdue": ctx["max_days_overdue"],
            "risk_score": ctx["risk_score"],
            "dispute_flag": ctx["dispute_flag"],
            "next_action": ctx["next_action"],
            "latest_invoice_id": latest_invoice_id,
            "comms_history": comms_history,
            "contact_info": {
                "name": ctx.get("contact_name", ""),
                "email": ctx.get("contact_email", ""),
                "phone": ctx.get("contact_phone", "")
            },
            "_full_context": ctx
        }

    def get_priority_clients(self) -> list:
        """
        Returns clients sorted by a composite priority score.
        Composite = (risk_score * 0.4) + (days_overdue_norm * 0.4) + (amount_norm * 0.2)
        Used to determine demo processing order.
        """
        invoices = excel_tool.get_all_invoices()

        # Aggregate per client
        client_map = {}
        for inv in invoices:
            name = inv["client"]
            if name not in client_map:
                client_map[name] = {
                    "client": name,
                    "total_amount": 0,
                    "max_days_overdue": 0,
                    "max_risk_score": 0
                }
            client_map[name]["total_amount"] += inv["amount"]
            client_map[name]["max_days_overdue"] = max(
                client_map[name]["max_days_overdue"], inv["days_overdue"]
            )
            client_map[name]["max_risk_score"] = max(
                client_map[name]["max_risk_score"], inv["risk_score"]
            )

        clients = list(client_map.values())
        if not clients:
            return []

        max_days = max(c["max_days_overdue"] for c in clients) or 1
        max_amount = max(c["total_amount"] for c in clients) or 1

        for c in clients:
            c["priority_score"] = round(
                (c["max_risk_score"] * 0.4)
                + ((c["max_days_overdue"] / max_days) * 100 * 0.4)
                + ((c["total_amount"] / max_amount) * 100 * 0.2),
                2
            )

        clients.sort(key=lambda c: c["priority_score"], reverse=True)
        return clients