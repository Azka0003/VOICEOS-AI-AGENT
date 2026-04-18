from pydantic import BaseModel, Field
from tools.llm_router import get_llm
from langchain_core.prompts import ChatPromptTemplate

class EmailDraft(BaseModel):
    subject: str = Field(description="The email subject line")
    body: str = Field(description="The full email body content")

class EmailAgent:
    def __init__(self):
        self.llm = get_llm(temperature=0.3).with_structured_output(EmailDraft)
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an expert B2B collections agent for an Indian firm. Write professional emails."),
            ("human", """Draft an email.
            Client Name: {client_name}
            Contact Person: {contact_name}
            Amount Due: ₹{amount}
            Tone: {tone}
            
            Keep it professional, legally compliant, and concise (under 4 sentences).""")
        ])

    def draft_email(self, client_data: dict, action_data: dict) -> dict:
        chain = self.prompt | self.llm
        result = chain.invoke({
            "client_name": client_data["client_name"],
            "contact_name": client_data["contact_info"]["name"],
            "amount": client_data["total_due"],
            "tone": action_data["tone"]
        })
        return result.dict()