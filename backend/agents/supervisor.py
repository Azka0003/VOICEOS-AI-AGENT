import datetime
from agents.invoice_agent import InvoiceAgent
from agents.risk_agent import RiskAgent
from agents.action_agent import ActionAgent
from agents.email_agent import EmailAgent

class SupervisorAgent:
    def __init__(self):
        self.invoice_agent = InvoiceAgent()
        self.risk_agent = RiskAgent()
        self.action_agent = ActionAgent()
        self.email_agent = EmailAgent()

    def process_client(self, client_name: str) -> dict:
        """Runs the full agentic workflow for a single client."""
        
        # 1. Fetch Data
        client_data = self.invoice_agent.get_client_data(client_name)
        if not client_data:
            return {"error": f"Client '{client_name}' not found in database."}

        # 2. Assess Risk
        risk_data = self.risk_agent.assess_risk(client_data)

        # 3. Decide Action & Tone
        action_data = self.action_agent.decide_action(client_data, risk_data)

        # 4. Execute Action Routing
        final_output = {
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "client": client_name,
            "data_summary": {
                "total_due": client_data["total_due"],
                "max_days_overdue": client_data["max_days_overdue"]
            },
            "risk_assessment": risk_data,
            "action_decision": action_data,
            "execution": None
        }

        if action_data["action"] == "escalate_hitl":
            final_output["execution"] = {"status": "paused_for_human", "reason": action_data["hitl_reason"]}
            # Here you would trigger your hitl_tool.py
            
        elif action_data["action"] == "send_email":
            draft = self.email_agent.draft_email(client_data, action_data)
            final_output["execution"] = {"status": "email_drafted", "content": draft}
            
        elif action_data["action"] == "make_call":
            final_output["execution"] = {"status": "call_queued", "phone": client_data["contact_info"]["phone"]}
            # Here you would trigger twilio_tool.py / Deepgram

        return final_output

# --- TEST SCRIPT ---
if __name__ == "__main__":
    supervisor = SupervisorAgent()
    
    # Test 1: Raj Traders (High value, has phone -> Should trigger Call or HITL depending on days)
    print("--- Processing Raj Traders ---")
    print(supervisor.process_client("Raj Traders"))
    
    # Test 2: Apex Solutions (Missing contact name -> Should trigger HITL)
    print("\n--- Processing Apex Solutions ---")
    print(supervisor.process_client("Apex Solutions"))