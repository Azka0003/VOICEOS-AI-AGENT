"""
call_tools.py — Live Data Tools for Voice Agent

Provides Deepgram function-calling definitions (client_side=True) and
their Python implementations, so the AI voice agent can query real data
(Excel invoices, ChromaDB briefings) during a live phone call.

Deepgram V1 client-side function definition format:
  {
    "name": "...",
    "description": "...",
    "parameters": { <JSON Schema> }
    # NO "endpoint" field for client-side functions
  }

The "client_side" flag is set by the SERVER in FunctionCallRequest events.
We don't set it in the function definition — it's controlled server-side.
"""

import json
import os
from tools.excel_tool import excel_tool
from tools.chroma_tool import chroma_tool


# ─────────────────────────────────────────────────────────────────────────────
# TOOL DEFINITIONS  (injected into Deepgram Settings → agent.think.functions)
# NO "endpoint" field = client-side execution (we handle it in deepgram_tool.py)
# ─────────────────────────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "get_invoice_summary",
        "description": (
            "Look up live invoice data for the client you are currently calling. "
            "Returns total amount due, number of outstanding invoices, days overdue, "
            "and dispute status. "
            "Use this when the customer asks how much they owe, about their balance, "
            "or about payment amounts. "
            "Pass the client company name you were given at the start of the call."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "client_name": {
                    "type": "string",
                    "description": (
                        "The company name to look up — use the client name "
                        "you were given at the start of this call."
                    )
                }
            },
            "required": ["client_name"]
        }
    },
    {
        "name": "get_invoice_list",
        "description": (
            "Get a detailed list of individual invoices for the client — "
            "invoice IDs, individual amounts, due dates, and statuses. "
            "Use this when the customer asks about specific invoices, "
            "wants to know which invoices are outstanding, "
            "or disputes a particular invoice number. "
            "Pass the client company name you were given at the start of the call."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "client_name": {
                    "type": "string",
                    "description": "The company name to look up."
                }
            },
            "required": ["client_name"]
        }
    },
    {
        "name": "get_client_briefing",
        "description": (
            "Fetch background on the client: communication history, risk level, "
            "contact details, and relationship notes. "
            "Use this when you need context on the client's payment history "
            "or past interactions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "client_name": {
                    "type": "string",
                    "description": "The company name to look up."
                }
            },
            "required": ["client_name"]
        }
    },
    {
        "name": "record_payment_promise",
        "description": (
            "Record that the customer has promised to pay by a specific date. "
            "Call this as soon as the customer gives a firm commitment with a date. "
            "This notifies the internal team so they can follow up."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "client_name": {
                    "type": "string",
                    "description": "The company name."
                },
                "promise_date": {
                    "type": "string",
                    "description": "The date the customer committed to pay (e.g. '2026-04-25' or 'this Friday')."
                },
                "amount": {
                    "type": "string",
                    "description": "Amount promised, e.g. 'full amount' or '50000'."
                }
            },
            "required": ["client_name", "promise_date"]
        }
    }
]


# ─────────────────────────────────────────────────────────────────────────────
# TOOL IMPLEMENTATIONS
# ─────────────────────────────────────────────────────────────────────────────

def _tool_get_invoice_summary(client_name: str) -> dict:
    rows = excel_tool.get_invoices_by_client(client_name)
    if not rows:
        # Try a fuzzy match — Deepgram LLM might pass a slightly different name
        all_invoices = excel_tool.get_all_invoices()
        name_lower = client_name.strip().lower()
        rows = [r for r in all_invoices if name_lower in r.get("client", "").lower()]

    if not rows:
        return {
            "error": f"No invoices found for '{client_name}'. "
                     "Check the company name and try again."
        }

    total_due = sum(r.get("amount", 0) for r in rows if r.get("status", "").lower() != "paid")
    max_overdue = max((r.get("days_overdue", 0) for r in rows), default=0)
    statuses = list({r.get("status", "Unknown") for r in rows})
    next_actions = list({r.get("next_action", "") for r in rows if r.get("next_action")})
    dispute = any(r.get("dispute", False) for r in rows)

    return {
        "client": client_name,
        "total_amount_due": f"₹{total_due:,}",
        "invoice_count": len(rows),
        "max_days_overdue": max_overdue,
        "statuses": statuses,
        "dispute_flag": dispute,
        "next_recommended_action": next_actions[0] if next_actions else "follow_up"
    }


def _tool_get_invoice_list(client_name: str) -> dict:
    rows = excel_tool.get_invoices_by_client(client_name)
    if not rows:
        return {"error": f"No invoices found for '{client_name}'."}

    invoices = [
        {
            "invoice_id": r.get("invoice_id", "N/A"),
            "amount": f"₹{r.get('amount', 0):,}",
            "due_date": str(r.get("due_date", "N/A")),
            "days_overdue": r.get("days_overdue", 0),
            "status": r.get("status", "Unknown"),
            "dispute": r.get("dispute", False)
        }
        for r in rows
    ]

    return {
        "client": client_name,
        "invoice_count": len(invoices),
        "invoices": invoices
    }


def _tool_get_client_briefing(client_name: str) -> dict:
    result = chroma_tool.get_client_briefing(client_name)
    if not result:
        return {"error": f"No briefing found for '{client_name}' in the knowledge base."}

    meta = result.get("metadata", {})
    return {
        "client": client_name,
        "contact_name": meta.get("contact_name"),
        "contact_email": meta.get("contact_email"),
        "risk_label": meta.get("risk_label"),
        "risk_score": meta.get("risk_score"),
        "dispute_flag": meta.get("dispute_flag"),
        "last_contact_date": meta.get("last_contact_date"),
        "last_contact_type": meta.get("last_contact_type"),
        "next_action": meta.get("next_action"),
        # First 400 chars — keep voice-friendly, not a wall of text
        "briefing_summary": result.get("page_content", "")[:400]
    }


def _tool_record_payment_promise(client_name: str, promise_date: str, amount: str = "full amount") -> dict:
    from datetime import datetime, timezone

    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": "voice_call",
        "action": "payment_promise_recorded",
        "client": client_name,
        "promise_date": promise_date,
        "amount_promised": amount,
        "source": "live_call"
    }

    DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
    log_path = os.path.join(DATA_DIR, "lineage_log.json")

    try:
        logs = []
        if os.path.exists(log_path):
            with open(log_path, "r") as f:
                logs = json.load(f)
        logs.append(log_entry)
        with open(log_path, "w") as f:
            json.dump(logs, f, indent=2)
        print(f"[CALL TOOLS] Payment promise logged: {client_name} → {promise_date} ({amount})")
    except Exception as e:
        print(f"[CALL TOOLS] Warning: Could not write lineage log: {e}")

    return {
        "status": "recorded",
        "message": (
            f"Noted — {client_name} has committed to pay {amount} by {promise_date}. "
            "Our team will follow up if the payment is not received."
        )
    }


# ─────────────────────────────────────────────────────────────────────────────
# DISPATCHER
# ─────────────────────────────────────────────────────────────────────────────

TOOL_MAP = {
    "get_invoice_summary":    _tool_get_invoice_summary,
    "get_invoice_list":       _tool_get_invoice_list,
    "get_client_briefing":    _tool_get_client_briefing,
    "record_payment_promise": _tool_record_payment_promise,
}


def dispatch_tool_call(function_name: str, parameters: dict) -> str:
    """
    Execute the named tool and return a JSON *string* (Deepgram expects a string
    in the FunctionCallResponse 'content' field).
    """
    fn = TOOL_MAP.get(function_name)
    if not fn:
        result = {"error": f"Unknown tool: '{function_name}'. Available: {list(TOOL_MAP)}"}
    else:
        try:
            result = fn(**parameters)
        except TypeError as e:
            result = {"error": f"Bad parameters for '{function_name}': {e}"}
        except Exception as e:
            result = {"error": f"Tool '{function_name}' failed: {e}"}

    print(f"[CALL TOOLS] {function_name}({parameters}) → {str(result)[:200]}")
    return json.dumps(result, ensure_ascii=False)