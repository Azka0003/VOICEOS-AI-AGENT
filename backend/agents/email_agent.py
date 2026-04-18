"""
email_agent.py — Email Generator
Always reads ChromaDB briefing before writing a single word.
LLM generates subject + body from the briefing — no hardcoded templates.
Applies days-overdue tone override before generation.
Writes outcomes to both Excel and ChromaDB after sending.
"""

import json
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from tools.excel_tool import excel_tool
from tools.chroma_tool import ChromaTool
from tools.comms_logger import comms_logger
from tools.lineage_logger import lineage_logger
from tools.llm_router import LLMRouter

chroma_tool = ChromaTool()
llm_router = LLMRouter()

# Replace with env-sourced SMTP config in production
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "your@email.com"
SMTP_PASS = "your_app_password"
FROM_ADDRESS = "ar@yourcompany.com"

TONE_RANK = {
    "friendly_reminder": 1,
    "urgent_followup": 2,
    "final_notice": 3,
    "dispute_acknowledgment": 0,  # Always stays — never upgraded or downgraded
    "legal": 4
}


class EmailAgent:
    """
    Generates and sends collections emails.
    ChromaDB briefing is the primary input — never uses hardcoded templates.
    """

    async def send_collection_email(self, context: dict, requested_tone: str) -> dict:
        """
        Main entry. Resolves final tone, drafts email via LLM, sends, then updates both stores.
        """

        # ── Step 1: Resolve final tone (may be upgraded by days_overdue) ─────
        tone = self._resolve_final_tone(context, requested_tone)

        # ── Step 2: Build the LLM generation prompt from ChromaDB briefing ───
        invoice_list = [
            {"id": inv["id"], "amount": inv["amount"], "due_date": inv["due_date"]}
            for inv in context["invoices"]
        ]

        generation_prompt = f"""
You are writing a professional collections email on behalf of [Company Name]'s accounts team.

CLIENT BRIEFING:
{context["briefing_text"]}

TONE REQUIRED: {tone}
Tone definitions:
- friendly_reminder: Polite, assumes good faith, no pressure language
- urgent_followup: Firm, references prior unanswered contact, sets a 7-day deadline
- final_notice: Serious, references multiple prior contacts, mentions further steps will
  be considered. Do NOT use the word "legal" unless tone is explicitly "legal".
- dispute_acknowledgment: Never demands payment. Acknowledges the dispute.
  Asks only for a status update.

INVOICE DETAILS:
Total Outstanding: ₹{context["total_outstanding"]:,}
Invoices: {json.dumps(invoice_list, indent=2)}
Days Overdue (max): {context["max_days_overdue"]}
Prior contacts made: {context["contact_count"]}
Contact person: {context.get("contact_name", "Accounts Team")}

OUTPUT FORMAT — return ONLY valid JSON, no markdown:
{{
    "subject": "specific subject line referencing invoice ID and amount",
    "body": "complete professional email body",
    "tone_used": "{tone}",
    "key_message": "one sentence summary of the email's core ask"
}}
"""

        # ── Step 3: Generate via high-quality LLM ────────────────────────────
        try:
            raw = await llm_router.invoke_quality(generation_prompt)
            email_data = json.loads(raw)
        except Exception as e:
            print(f"[EMAIL AGENT] LLM generation failed for {context['client']}: {e}")
            await self._post_email_update(context, {}, sent=False)
            return {"status": "failed", "reason": str(e)}

        # ── Step 4: Send the email ────────────────────────────────────────────
        sent = await self._send_smtp(
            to_address=context.get("contact_email", ""),
            subject=email_data["subject"],
            body=email_data["body"]
        )

        # ── Step 5: Update both data stores ──────────────────────────────────
        await self._post_email_update(context, email_data, sent=sent)

        return {
            "status": "sent" if sent else "failed",
            "tone_used": tone,
            "subject": email_data.get("subject"),
            "key_message": email_data.get("key_message")
        }

    # ── Tone resolution ───────────────────────────────────────────────────────

    def _resolve_final_tone(self, context: dict, requested_tone: str) -> str:
        """
        Applies the days-overdue minimum tone rule.
        Never downgrades a tone — only upgrades if days_overdue demands it.
        Dispute always locks tone to dispute_acknowledgment.
        """
        if context.get("dispute_flag"):
            return "dispute_acknowledgment"

        days = context.get("max_days_overdue", 0)
        contact_count = context.get("contact_count", 0)

        minimum_tone = "friendly_reminder"
        if days > 75 and contact_count >= 1:
            minimum_tone = "final_notice"
        elif days > 60:
            minimum_tone = "urgent_followup"

        if TONE_RANK.get(minimum_tone, 0) > TONE_RANK.get(requested_tone, 0):
            return minimum_tone
        return requested_tone

    # ── SMTP delivery ─────────────────────────────────────────────────────────

    async def _send_smtp(self, to_address: str, subject: str, body: str) -> bool:
        """
        Sends the email via SMTP. Returns True on success.
        """
        if not to_address:
            print("[EMAIL AGENT] No email address — skipping send.")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = FROM_ADDRESS
            msg["To"] = to_address
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                server.send_message(msg)

            print(f"[EMAIL AGENT] Sent to {to_address}: {subject}")
            return True
        except Exception as e:
            print(f"[EMAIL AGENT] SMTP error: {e}")
            return False

    # ── Post-send dual-store update ───────────────────────────────────────────

    async def _post_email_update(self, context: dict, email_data: dict, sent: bool):
        """
        Writes outcomes to Excel (Next Action + contact log) and ChromaDB (metadata).
        Called after every email attempt — success or failure.
        """
        outcome = "sent" if sent else "failed"
        new_contact_count = context["contact_count"] + (1 if sent else 0)

        tone = email_data.get("tone_used", "unknown")
        days = context.get("max_days_overdue", 0)

        # Determine next action from tone + days_overdue
        if tone == "final_notice":
            next_action = "escalate_to_legal" if days > 75 else "schedule_call"
        elif tone == "urgent_followup":
            next_action = "send_final_notice"
        elif tone == "dispute_acknowledgment":
            next_action = "disputed_under_review"
        else:
            next_action = "send_urgent_followup"

        # Update Excel — every invoice for this client
        for inv in context["invoices"]:
            excel_tool.update_next_action(inv["id"], next_action, "email_agent")
            if sent:
                excel_tool.log_contact_made(
                    invoice_id=inv["id"],
                    contact_type="email",
                    outcome=outcome,
                    agent_name="email_agent"
                )

        # Update ChromaDB metadata fields
        chroma_tool.update_client_metadata(context["client"], {
            "contact_count": new_contact_count,
            "last_contact_date": datetime.now().isoformat(),
            "last_contact_type": "email",
            "next_action": next_action
        })

        # Persist full contact record to comms log
        comms_logger.log(context["client"], {
            "type": "email",
            "timestamp": datetime.now().isoformat(),
            "tone": tone,
            "subject": email_data.get("subject", ""),
            "email_body_summary": email_data.get("key_message", ""),
            "outcome": outcome,
            "next_action_suggested": next_action
        })

        lineage_logger.log({
            "agent": "email_agent",
            "client": context["client"],
            "tone": tone,
            "sent": sent,
            "next_action": next_action
        })
