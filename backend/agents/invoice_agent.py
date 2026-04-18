import json
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
MOCK_INVOICES_PATH = os.path.join(DATA_DIR, "mock_invoices.json")

class InvoiceAgent:
    def __init__(self):
        with open(MOCK_INVOICES_PATH, "r") as f:
            self.db = json.load(f)

    def get_client_data(self, client_name: str):
        """Fetches all invoices and contact info for a specific client."""
        client_invoices = [inv for inv in self.db if inv["client"].lower() == client_name.lower()]
        
        if not client_invoices:
            return None
            
        # Aggregate data
        total_due = sum(inv["amount"] for inv in client_invoices)
        max_days_overdue = max(inv["days_overdue"] for inv in client_invoices)
        has_dispute = any(inv.get("dispute_flag", False) for inv in client_invoices)
        
        # Assume contact info is same across a client's invoices
        contact_info = {
            "name": client_invoices[0].get("contact_name"),
            "email": client_invoices[0].get("contact_email"),
            "phone": client_invoices[0].get("contact_phone")
        }

        return {
            "client_name": client_invoices[0]["client"],
            "total_due": total_due,
            "max_days_overdue": max_days_overdue,
            "has_dispute": has_dispute,
            "contact_info": contact_info,
            "raw_invoices": client_invoices
        }