"""
startup.py — Boot-time initialisation
UPDATED: Also seeds demo client ChromaDB docs + runs demo_engine on startup.
"""

import os
from tools.chroma_tool import chroma_tool

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CHROMADB_DOCS_PATH = os.path.join(DATA_DIR, "chromadb_documents.json")

DEMO_CLIENT_DOCS = [
    {
        "doc_id": "demo_sunrise_retail",
        "metadata": {
            "client": "Sunrise Retail", "contact_name": "Ananya Sharma",
            "contact_email": "farazstudy112@gmail.com", "contact_phone": "",
            "risk_score": 28, "risk_label": "Low", "dispute_flag": False,
            "contact_count": 0, "last_contact_date": "Never", "last_contact_type": "none",
            "next_action": "send_friendly_reminder", "hitl_required": False,
        },
        "page_content": "You are contacting Sunrise Retail regarding a recently overdue invoice. Ananya Sharma is the accounts contact. First overdue invoice — treat with a friendly, non-threatening tone. Goal is a simple payment confirmation. The client has a clean payment record and likely just needs a nudge.",
    },
    {
        "doc_id": "demo_patel_industries",
        "metadata": {
            "client": "Patel Industries", "contact_name": "Kiran Patel",
            "contact_email": "farazstudy112@gmail.com", "contact_phone": "",
            "risk_score": 55, "risk_label": "Medium", "dispute_flag": False,
            "contact_count": 1, "last_contact_date": "Never", "last_contact_type": "email",
            "next_action": "send_urgent_followup", "hitl_required": False,
        },
        "page_content": "Patel Industries has one outstanding invoice now 38 days overdue. Kiran Patel is the decision-maker. One prior reminder email was sent with no response. Tone should be firm but professional — second contact attempt. Request a specific payment date and mention escalation if no response within 7 days.",
    },
    {
        "doc_id": "demo_gupta_wholesale",
        "metadata": {
            "client": "Gupta Wholesale", "contact_name": "Deepak Gupta",
            "contact_email": "farazstudy112@gmail.com", "contact_phone": "",
            "risk_score": 72, "risk_label": "High", "dispute_flag": False,
            "contact_count": 2, "last_contact_date": "Never", "last_contact_type": "email",
            "next_action": "send_final_notice", "hitl_required": False,
        },
        "page_content": "Gupta Wholesale has a high-value invoice 65 days overdue. Two prior contacts ignored. Deepak Gupta is the owner. Final notice before escalation — be direct and serious. Mention that failure to respond will result in legal review. Only say what will actually happen.",
    },
    {
        "doc_id": "demo_verma_exports",
        "metadata": {
            "client": "Verma Exports", "contact_name": "Suresh Verma",
            "contact_email": "farazstudy112@gmail.com", "contact_phone": "+919634143593",
            "risk_score": 82, "risk_label": "High", "dispute_flag": False,
            "contact_count": 2, "last_contact_date": "Never", "last_contact_type": "call",
            "next_action": "schedule_call", "hitl_required": False,
        },
        "page_content": "Verma Exports has a large outstanding balance, 72 days overdue. Suresh Verma is the proprietor. Two emails unanswered. Prior call attempt went unanswered. Tone should be urgent and firm. Goal: get a payment commitment with a specific date. If client mentions difficulty, offer 50% now / 50% in 14 days plan.",
    },
    {
        "doc_id": "demo_khan_brothers",
        "metadata": {
            "client": "Khan & Brothers", "contact_name": "",
            "contact_email": "", "contact_phone": "",
            "risk_score": 61, "risk_label": "Medium", "dispute_flag": False,
            "contact_count": 0, "last_contact_date": "Never", "last_contact_type": "none",
            "next_action": "resolve_contact_details", "hitl_required": True,
        },
        "page_content": "Khan & Brothers has an overdue invoice but contact details are incomplete. No verified contact on file. Human review is required to source the correct contact before any outreach. Flag for HITL immediately — do not attempt automated contact.",
    },
    {
        "doc_id": "demo_reddy_logistics",
        "metadata": {
            "client": "Reddy Logistics", "contact_name": "Priya Reddy",
            "contact_email": "farazstudy112@gmail.com", "contact_phone": "",
            "risk_score": 88, "risk_label": "High", "dispute_flag": True,
            "contact_count": 1, "last_contact_date": "Never", "last_contact_type": "email",
            "next_action": "send_urgent_followup", "hitl_required": False,
        },
        "page_content": "Reddy Logistics raised a dispute on a delivery quality issue. Priya Reddy is the accounts manager. Invoice is 55 days overdue with active dispute flag. Do NOT demand payment. Acknowledge the dispute respectfully. Ask for status update on their internal review. Offer delivery documentation if needed. Keep the relationship intact.",
    },
]


def seed_chromadb():
    """Idempotent seed — safe to call on every startup."""
    chroma_tool.load_from_json(CHROMADB_DOCS_PATH)
    _seed_demo_clients()
    _run_demo_engine()
    clients = chroma_tool.list_all_clients()
    print(f"[STARTUP] ChromaDB ready. {len(clients)} client(s) loaded: {clients}")


def _seed_demo_clients():
    existing = set(chroma_tool.list_all_clients())
    seeded = 0
    for doc in DEMO_CLIENT_DOCS:
        client_name = doc["metadata"]["client"]
        if client_name not in existing:
            try:
                chroma_tool.collection.add(
                    ids=[doc["doc_id"]],
                    documents=[doc["page_content"]],
                    metadatas=[doc["metadata"]],
                )
                seeded += 1
                print(f"[STARTUP] Seeded demo client: {client_name}")
            except Exception as e:
                print(f"[STARTUP] Failed to seed {client_name}: {e}")
    if seeded:
        print(f"[STARTUP] {seeded} demo client(s) added to ChromaDB.")
    else:
        print(f"[STARTUP] Demo clients already in ChromaDB — skipping.")


def _run_demo_engine():
    try:
        from demo_engine import inject_demo_entries
        injected = inject_demo_entries(count=2)
        if injected:
            print(f"[STARTUP] Demo engine injected {len(injected)} new invoice(s):")
            for entry in injected:
                print(f"  → {entry['id']} | {entry['client']} | {entry['next_action']}")
        else:
            print("[STARTUP] Demo engine: no new entries to inject.")
    except Exception as e:
        print(f"[STARTUP] Demo engine skipped (non-fatal): {e}")
