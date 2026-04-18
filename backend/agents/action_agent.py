from pydantic import BaseModel, Field
from tools.llm_router import get_llm
from langchain_core.prompts import ChatPromptTemplate

class ActionDecision(BaseModel):
    action: str = Field(description="'send_email', 'make_call', or 'escalate_hitl'")
    tone: str = Field(description="'friendly_reminder', 'urgent_followup', or 'final_notice'")
    hitl_reason: str = Field(description="Why HITL was triggered, or 'None'")

class ActionAgent:
    def __init__(self):
        self.llm = get_llm(temperature=0.0).with_structured_output(ActionDecision)
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", """You are the Action Decision Engine.
            
            HITL (Human-in-the-loop) Triggers ('escalate_hitl'):
            1. Total Due > ₹50,000 AND > 30 days overdue.
            2. Risk Label is 'High'.
            3. Contact name is missing (None).
            
            Tone Rules (if not HITL):
            - < 30 days overdue = 'friendly_reminder'
            - 30-60 days overdue = 'urgent_followup'
            - > 60 days OR Disputed = 'final_notice'
            
            If a phone number exists and it's urgent, prefer 'make_call'. Otherwise 'send_email'."""),
            ("human", "Data: Due: ₹{amount}, Max Overdue: {days} days, Risk: {risk}, Phone: {phone}, Name: {name}")
        ])

    def decide_action(self, client_data: dict, risk_data: dict) -> dict:
        chain = self.prompt | self.llm
        result = chain.invoke({
            "amount": client_data["total_due"],
            "days": client_data["max_days_overdue"],
            "risk": risk_data["risk_label"],
            "phone": "Yes" if client_data["contact_info"]["phone"] else "No",
            "name": client_data["contact_info"]["name"] or "Missing"
        })
        return result.dict()