"""
risk_agent.py — Risk Assessor
Takes the unified context from Invoice Agent and produces a structured verdict.
Uses ChromaDB briefing text for qualitative payment history signals.
Uses a transparent point-based scoring system with a full audit trail.
"""

import json
from tools.llm_router import LLMRouter

llm_router = LLMRouter()


class RiskAgent:
    """
    Produces a fully structured risk verdict.
    Never decides what action to take — that is Action Agent's job.
    """

    async def evaluate(self, context: dict) -> dict:
        """
        Main entry point. Returns a structured risk verdict dict that
        Action Agent uses to make its routing decision.
        """
        score, flags, primary_driver = self._calculate_risk_score(context)

        # Qualitative history assessment from ChromaDB briefing
        history_points = await self._assess_payment_history(context.get("briefing_text", ""))
        score = min(score + history_points, 100)

        risk_label = self._score_to_label(score)
        tone = self._recommend_tone(context, score, flags)
        confidence = self._compute_confidence(context, score, flags)
        hitl_recommendation, hitl_scenario = self._check_hitl(context, score, flags, confidence)

        reasoning = await self._generate_reasoning(context, score, flags, primary_driver)

        return {
            "client": context["client"],
            "risk_score": score,
            "risk_label": risk_label,
            "confidence": confidence,
            "primary_risk_driver": primary_driver,
            "hitl_recommendation": hitl_recommendation,
            "hitl_scenario": hitl_scenario,
            "flags": flags,
            "safe_to_call": not hitl_recommendation and bool(context.get("contact_phone")),
            "safe_to_email": not hitl_recommendation and bool(context.get("contact_email")),
            "recommended_tone": tone,
            "reasoning": reasoning
        }

    # ── Scoring ───────────────────────────────────────────────────────────────

    def _calculate_risk_score(self, context: dict) -> tuple[int, list[str], str]:
        """
        Point-based scoring with a transparent audit trail.
        Returns (score, flags, primary_driver).
        """
        score = 0
        flags = []
        drivers = []

        # Days overdue component (max 40 points)
        days = context.get("max_days_overdue", 0)
        if days > 75:
            score += 40; drivers.append("critically_overdue")
        elif days > 60:
            score += 32; drivers.append("severely_overdue")
        elif days > 45:
            score += 24; drivers.append("significantly_overdue")
        elif days > 30:
            score += 16; drivers.append("moderately_overdue")
        elif days > 15:
            score += 8;  drivers.append("recently_overdue")
        else:
            score += 3;  drivers.append("minimally_overdue")

        # Dispute component (max 35 points)
        if context.get("dispute_flag"):
            score += 35
            flags.append("ACTIVE_DISPUTE")
            drivers.append("dispute_flag")

        # Missing contact component (max 15 points)
        if not context.get("contact_name"):
            score += 15
            flags.append("MISSING_CONTACT")
            drivers.append("missing_contact")

        # Contact history — multiple unanswered contacts signal avoidance
        contact_count = context.get("contact_count", 0)
        if contact_count >= 3:
            score += 5
            flags.append("REPEATED_CONTACT")

        # Score contradiction guard — days > 60 should never produce a score < 40
        if days > 60 and score < 40:
            flags.append("SCORE_CONTRADICTION")
            score = max(score, 58)

        primary_driver = drivers[0] if drivers else "unknown"
        return min(score, 100), flags, primary_driver

    async def _assess_payment_history(self, briefing_text: str) -> int:
        """
        Sends the ChromaDB briefing to the LLM for qualitative history scoring.
        Returns 0–10 additional risk points based on payment behaviour narrative.
        """
        if not briefing_text or len(briefing_text.strip()) < 20:
            return 3  # Unknown history = modest default risk

        prompt = f"""
Read this client briefing and assess their payment behaviour history.
Return ONLY a JSON object with one field: "history_risk_points" (integer 0–10).

Scoring guide:
0–2: Excellent history, consistent on-time payer
3–5: Generally good but some delays
6–8: Pattern of late payments
9–10: Chronic late payer or went silent on previous contacts

Briefing:
{briefing_text}
"""
        try:
            result = await llm_router.invoke_fast(prompt)
            parsed = json.loads(result)
            points = int(parsed.get("history_risk_points", 3))
            return max(0, min(points, 10))  # Clamp 0–10
        except Exception as e:
            print(f"[RISK AGENT] History scoring failed: {e} — defaulting to 3")
            return 3

    # ── Label and tone helpers ────────────────────────────────────────────────

    def _score_to_label(self, score: int) -> str:
        if score >= 71:
            return "High"
        elif score >= 41:
            return "Medium"
        return "Low"

    def _recommend_tone(self, context: dict, score: int, flags: list) -> str:
        """
        Determines the communication tone.
        Dispute always wins — never recommend aggressive tone during a dispute.
        """
        contact_count = context.get("contact_count", 0)
        days = context.get("max_days_overdue", 0)

        # Dispute always overrides — acknowledge, never demand
        if "ACTIVE_DISPUTE" in flags:
            return "dispute_acknowledgment"

        # First contact: days_overdue drives tone
        if contact_count == 0:
            if days > 60:
                return "urgent"
            elif days > 30:
                return "firm"
            return "friendly"

        # Escalation ladder for repeat contacts
        if contact_count == 1:
            return "urgent"
        elif contact_count >= 2:
            return "final" if score >= 70 else "urgent"

        return "friendly"

    # ── Confidence and HITL ───────────────────────────────────────────────────

    def _compute_confidence(self, context: dict, score: int, flags: list) -> float:
        """
        Confidence in the risk assessment.
        Missing data reduces confidence; clear signals raise it.
        """
        confidence = 0.85  # Baseline

        if "MISSING_CONTACT" in flags:
            confidence -= 0.25
        if "SCORE_CONTRADICTION" in flags:
            confidence -= 0.15
        if not context.get("briefing_text"):
            confidence -= 0.20
        if context.get("dispute_flag"):
            confidence -= 0.10  # Disputes introduce uncertainty

        return round(max(0.0, min(confidence, 1.0)), 2)

    def _check_hitl(
        self, context: dict, score: int, flags: list, confidence: float
    ) -> tuple[bool, str | None]:
        """
        Returns (hitl_recommendation, hitl_scenario_code).
        HITL is recommended if any hard trigger is met OR confidence is too low.
        """
        if "MISSING_CONTACT" in flags:
            return True, "MISSING_CONTACT"
        if "ACTIVE_DISPUTE" in flags and score >= 70:
            return True, "HIGH_RISK_DISPUTE"
        if context.get("hitl_required"):
            return True, "FLAGGED_IN_CHROMADB"
        if confidence < 0.5:
            return True, "LOW_CONFIDENCE"
        return False, None

    # ── Reasoning ─────────────────────────────────────────────────────────────

    async def _generate_reasoning(
        self, context: dict, score: int, flags: list, primary_driver: str
    ) -> str:
        """
        Generates a plain-English 2–3 sentence explanation of the score.
        Uses invoke_fast for speed.
        """
        prompt = f"""
Write a 2–3 sentence plain English explanation of this debt collections risk score.
Be concise and factual. No bullet points.

Client: {context['client']}
Risk Score: {score}/100
Primary Driver: {primary_driver}
Days Overdue: {context.get('max_days_overdue', 0)}
Dispute Flag: {context.get('dispute_flag', False)}
Active Flags: {flags}
Contact Count: {context.get('contact_count', 0)}
"""
        try:
            return await llm_router.invoke_fast(prompt)
        except Exception:
            return (
                f"{context['client']} has a risk score of {score}/100, "
                f"primarily driven by {primary_driver}. "
                f"Invoice is {context.get('max_days_overdue', 0)} days overdue."
            )
