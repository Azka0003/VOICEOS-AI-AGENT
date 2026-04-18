from pydantic import BaseModel, Field
from tools.llm_router import get_llm
from langchain_core.prompts import ChatPromptTemplate

class RiskAssessment(BaseModel):
    risk_score: int = Field(description="Integer 0-100")
    risk_label: str = Field(description="Low (0-40), Medium (41-70), or High (71-100)")
    reasoning: str = Field(description="1-sentence explanation of the score")

class RiskAgent:
    def __init__(self):
        self.llm = get_llm(temperature=0.0).with_structured_output(RiskAssessment)
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a Financial Risk Assessor. Calculate risk based on these strict rules:
            - If dispute_flag is true -> risk_score MUST be 71-100 (High)
            - If days_overdue > 60 -> risk_score MUST be at least 60 (Medium to High)
            - If days_overdue < 20 AND no dispute -> risk_score MUST be < 45 (Low)
            Amount owed alone does not increase risk."""),
            ("human", "Assess this client:\nDays Overdue: {days}\nDispute: {dispute}")
        ])

    def assess_risk(self, client_data: dict) -> dict:
        chain = self.prompt | self.llm
        result = chain.invoke({
            "days": client_data["max_days_overdue"],
            "dispute": client_data["has_dispute"]
        })
        return result.dict()