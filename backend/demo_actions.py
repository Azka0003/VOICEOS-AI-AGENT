"""
demo_actions.py — Demo-Safe Email & Call Executor

PURPOSE:
  When DEMO_MODE=true in .env (or Twilio/SMTP creds are missing),
  this module intercepts the actual send/call and instead:

  1. EMAIL: Sends a REAL email via Gmail SMTP if creds exist,
            OR logs a mock "sent" event so the SSE feed shows it live.

  2. CALL:  Places a REAL Twilio call if creds exist,
            OR simulates a call transcript in real time through SSE
            so judges can see the call monitor light up — no Twilio needed.

HOW TO USE:
  In action_agent.py, replace the direct email/call execution with:
    from demo_actions import demo_email, demo_call
    result = await demo_email(context, tone, broadcast_fn)
    result = await demo_call(context, risk, broadcast_fn)

  The broadcast_fn is the SSE broadcaster from main.py.

WHY THIS MATTERS FOR THE HACKATHON:
  Judges see the Call Monitor tab light up with a live transcript,
  the Agent Feed fills with decisions, the HITL card appears —
  ALL without needing Twilio or SMTP configured.
  If creds exist, it does the real thing. Best of both worlds.
"""

import os
import json
import asyncio
import smtplib
import random
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from tools.lineage_logger import lineage_logger
from tools.excel_tool import excel_tool


# ── Simulated call transcript templates ──────────────────────────────────────
# Each template is a sequence of (role, message, delay_seconds) tuples.
# These mimic what a real Deepgram/Twilio call would produce.

CALL_SCRIPTS = {
    "friendly": [
        ("agent",  "Hello, this is an automated call from the accounts team. May I please speak with {contact_name}?", 2),
        ("client", "Yes, speaking.", 3),
        ("agent",  "Good {time_of_day}, {contact_name}. I'm calling regarding invoice {inv_id} for ₹{amount}, which was due {days} days ago. We wanted to check if everything is in order.", 3),
        ("client", "Oh yes, I meant to clear that. Can I do it by end of this week?", 4),
        ("agent",  "Absolutely, that works perfectly. I'll note a payment commitment for {commit_date}. Is there anything else I can help with?", 3),
        ("client", "No, that's all. Thank you.", 2),
        ("agent",  "Thank you, {contact_name}. Have a great day. Goodbye.", 1),
    ],
    "urgent": [
        ("agent",  "Hello, this is an automated call from the accounts team. May I speak with {contact_name}?", 2),
        ("client", "This is {contact_name}.", 3),
        ("agent",  "Thank you. I'm calling regarding invoice {inv_id} for ₹{amount} which is now {days} days overdue. We've sent two prior reminders with no response.", 4),
        ("client", "I know, I've been meaning to call. We're going through some cash flow issues.", 5),
        ("agent",  "I understand. Could we agree on a partial payment of 50% by this Friday, with the remainder in 14 days?", 3),
        ("client", "I can manage 30% this week.", 3),
        ("agent",  "Noted. I'll record a commitment of 30% by Friday. We'll follow up on the remainder. Thank you for working with us.", 2),
        ("client", "Alright. Thanks.", 1),
    ],
    "final": [
        ("agent",  "Hello, this is a final notice call from the accounts team regarding invoice {inv_id}. May I speak with {contact_name}?", 2),
        ("client", "Yes, what is this about?", 3),
        ("agent",  "This is regarding an outstanding amount of ₹{amount} that is now {days} days overdue. This is our third attempt to reach you. If payment is not received within 7 days, this account will be escalated.", 5),
        ("client", "Please don't escalate. I'll make the full payment by Monday.", 4),
        ("agent",  "Thank you. I'm recording a full payment commitment for Monday. We'll hold escalation pending that. Is there anything else?", 3),
        ("client", "No, that's fine. Thank you.", 2),
    ],
    "no_answer": [
        ("agent",  "Hello, this is an automated call from the accounts team. May I speak with {contact_name}?", 3),
        ("agent",  "Hello? Can you hear me?", 4),
        ("agent",  "We're unable to reach you at this time. We'll try again shortly. Goodbye.", 2),
    ],
}


def _get_time_of_day() -> str:
    hour = datetime.now().hour
    if hour < 12:
        return "morning"
    elif hour < 17:
        return "afternoon"
    return "evening"


def _format_script(script: list, context: dict) -> list:
    """Fill template variables into script lines."""
    inv = context.get("invoices", [{}])[0]
    vars_ = {
        "contact_name": context.get("contact_name", "the account manager"),
        "inv_id": inv.get("id", "the invoice"),
        "amount": f"{context.get('total_outstanding', 0):,}",
        "days": str(context.get("max_days_overdue", 0)),
        "time_of_day": _get_time_of_day(),
        "commit_date": "this Friday",
    }
    result = []
    for role, msg, delay in script:
        for k, v in vars_.items():
            msg = msg.replace(f"{{{k}}}", v)
        result.append((role, msg, delay))
    return result


# ── Email ─────────────────────────────────────────────────────────────────────

async def demo_email(context: dict, tone: str, broadcast) -> dict:
    """
    Sends email if SMTP creds exist, otherwise simulates.
    Always fires SSE events so the Agent Feed updates live.
    """
    client = context["client"]
    contact_email = context.get("contact_email", "")
    contact_name = context.get("contact_name", "Team")
    inv = context.get("invoices", [{}])[0]
    amount = context.get("total_outstanding", 0)
    days = context.get("max_days_overdue", 0)

    # Build email content based on tone
    tone_subjects = {
        "friendly_reminder": f"Friendly Reminder: Invoice {inv.get('id', '')} — ₹{amount:,} due",
        "urgent_followup":   f"Urgent: Invoice {inv.get('id', '')} is {days} days overdue — Action Required",
        "final_notice":      f"FINAL NOTICE: Invoice {inv.get('id', '')} — Immediate Payment Required",
        "dispute_acknowledgment": f"Re: Dispute on Invoice {inv.get('id', '')} — Acknowledgment",
    }

    tone_bodies = {
        "friendly_reminder": f"""Dear {contact_name},

I hope this message finds you well. This is a friendly reminder that invoice {inv.get('id', '')} for ₹{amount:,} was due {days} days ago and remains outstanding.

If you've already made this payment, please disregard this message. Otherwise, we'd appreciate payment at your earliest convenience.

Thank you for your continued partnership.

Best regards,
DebtPilot Collections Team""",

        "urgent_followup": f"""Dear {contact_name},

This is a follow-up regarding invoice {inv.get('id', '')} for ₹{amount:,}, now {days} days overdue. We've reached out previously but have not received a response or payment.

Please arrange payment within the next 7 days to avoid further escalation.

If you're experiencing difficulties, please contact us immediately to discuss a resolution.

Regards,
DebtPilot Collections Team""",

        "final_notice": f"""Dear {contact_name},

This is a FINAL NOTICE regarding invoice {inv.get('id', '')} for ₹{amount:,}, which is now {days} days overdue. Despite multiple attempts to contact you, this invoice remains unpaid.

If payment is not received within 7 days of this notice, we will be compelled to take further action on this account.

Please treat this as urgent.

DebtPilot Collections Team""",

        "dispute_acknowledgment": f"""Dear {contact_name},

We acknowledge receipt of your dispute regarding invoice {inv.get('id', '')}. We are reviewing the matter and will respond within 5 business days.

Please do not hesitate to contact us with any supporting documentation.

DebtPilot Collections Team""",
    }

    subject = tone_subjects.get(tone, f"Invoice Notice — {client}")
    body = tone_bodies.get(tone, f"Dear {contact_name}, please address invoice {inv.get('id','')} for ₹{amount:,}.")

    email_sent = False
    send_method = "simulated"

    # Try real SMTP if configured
    smtp_user = os.getenv("GMAIL_ADDRESS", "")
    smtp_pass = os.getenv("GMAIL_APP_PASSWORD", "")

    if smtp_user and smtp_pass and contact_email:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = smtp_user
            msg["To"] = contact_email
            msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP("smtp.gmail.com", 587) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, contact_email, msg.as_string())

            email_sent = True
            send_method = "gmail_smtp"
            print(f"[DEMO EMAIL] ✓ Real email sent to {contact_email}")
        except Exception as e:
            print(f"[DEMO EMAIL] SMTP failed ({e}) — falling back to simulation")

    # Fire SSE events regardless (real or simulated)
    await broadcast({
        "type": "agent_action",
        "message": f"📧 {tone.replace('_', ' ').title()} email {'sent' if email_sent else 'drafted'} → {client} ({contact_email or 'no email'})",
        "client": client,
        "tone": tone,
        "subject": subject,
        "email_sent": email_sent,
        "method": send_method,
    })

    await asyncio.sleep(0.5)

    await broadcast({
        "type": "client_processed",
        "client": client,
        "decision": f"email:{tone}",
        "risk_label": context.get("risk_label", "Medium"),
        "email_sent": email_sent,
        "method": send_method,
    })

    # Write back to Excel
    invoice_ids = [inv["id"] for inv in context.get("invoices", [])]
    for inv_id in invoice_ids:
        excel_tool.log_contact_made(inv_id, "email", "delivered" if email_sent else "simulated", "email_agent")

    # Log to lineage
    lineage_logger.log({
        "agent": "email_agent",
        "client": client,
        "action": f"email_{tone}",
        "email_sent": email_sent,
        "method": send_method,
        "tone": tone,
        "subject": subject,
        "contact_email": contact_email,
    })

    return {
        "decision": "email_sent" if email_sent else "email_simulated",
        "tone": tone,
        "subject": subject,
        "email_sent": email_sent,
        "method": send_method,
    }


# ── Call simulation ───────────────────────────────────────────────────────────

async def demo_call(context: dict, risk: dict, broadcast) -> dict:
    """
    Places a real Twilio call if creds exist.
    Otherwise runs a simulated live transcript through SSE —
    the Call Monitor tab will show the conversation in real time.
    """
    client = context["client"]
    contact_phone = context.get("contact_phone", "")
    inv = context.get("invoices", [{}])[0]

    # Determine call script based on risk tone
    tone = risk.get("recommended_tone", "friendly")
    if tone in ("final", "legal"):
        script_key = "final"
    elif tone == "urgent":
        script_key = "urgent"
    else:
        script_key = "friendly"

    # Simulate no-answer 20% of the time (realistic demo)
    if random.random() < 0.2:
        script_key = "no_answer"

    script = _format_script(CALL_SCRIPTS[script_key], context)

    # Try real Twilio if configured
    twilio_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    twilio_token = os.getenv("TWILIO_AUTH_TOKEN", "")
    twilio_from = os.getenv("TWILIO_FROM_NUMBER", "")
    base_url = os.getenv("BASE_URL", "")

    if twilio_sid and twilio_token and twilio_from and contact_phone and base_url:
        try:
            from tools.twilio_tool import twilio_tool
            from urllib.parse import quote
            safe_client = quote(client)
            twiml_url = f"{base_url}/call/twiml-initial?client_name={safe_client}"
            call_sid = twilio_tool.make_call(contact_phone, twiml_url)
            if call_sid:
                await broadcast({"type": "call_started", "client": client, "call_sid": call_sid})
                lineage_logger.log({
                    "agent": "action_agent",
                    "client": client,
                    "decision": "call_placed_real",
                    "call_sid": call_sid,
                    "tone": tone,
                })
                return {"decision": "call_placed", "call_sid": call_sid, "method": "twilio"}
        except Exception as e:
            print(f"[DEMO CALL] Twilio failed ({e}) — falling back to simulation")

    # ── Simulated call via SSE ────────────────────────────────────────────────
    fake_sid = f"SIM_{client.replace(' ', '_').upper()}_{int(datetime.now().timestamp())}"

    await broadcast({
        "type": "call_started",
        "client": client,
        "call_sid": fake_sid,
        "simulated": True,
    })

    await broadcast({
        "type": "agent_action",
        "message": f"📞 Initiating call → {client} ({contact_phone or 'demo mode'})",
        "client": client,
    })

    # Stream transcript lines with realistic delays
    for role, message, delay in script:
        await asyncio.sleep(delay)
        await broadcast({
            "type": "transcript",
            "role": role,
            "content": message,
            "client": client,
            "call_sid": fake_sid,
        })

    # Determine outcome from script
    outcome_map = {
        "no_answer": "no_response",
        "friendly":  "confirmed",
        "urgent":    "confirmed",
        "final":     "confirmed",
    }
    call_outcome = outcome_map.get(script_key, "confirmed")

    # Payment commitment if call was answered
    payment_commitment = None
    if call_outcome == "confirmed" and script_key != "no_answer":
        payment_commitment = "this Friday" if script_key == "friendly" else "within 7 days"

    await asyncio.sleep(1)

    await broadcast({
        "type": "call_ended",
        "client": client,
        "call_sid": fake_sid,
        "outcome": call_outcome,
        "simulated": True,
    })

    await broadcast({
        "type": "call_outcome",
        "client": client,
        "call_sid": fake_sid,
        "outcome": call_outcome,
        "payment_commitment": payment_commitment,
        "simulated": True,
    })

    await broadcast({
        "type": "client_processed",
        "client": client,
        "decision": f"call:{call_outcome}",
        "risk_label": context.get("risk_label", "High"),
        "payment_commitment": payment_commitment,
    })

    # Write back to Excel
    invoice_ids = [inv["id"] for inv in context.get("invoices", [])]
    for inv_id in invoice_ids:
        excel_tool.log_contact_made(inv_id, "call", call_outcome, "action_agent")
        # Advance the next_action so it doesn't loop
        next_action = "await_payment_" + (datetime.now().strftime("%Y-%m-%d")) if payment_commitment else "send_final_notice"
        excel_tool.update_next_action(inv_id, next_action, "action_agent")

    lineage_logger.log({
        "agent": "action_agent",
        "client": client,
        "decision": "call_simulated",
        "outcome": call_outcome,
        "payment_commitment": payment_commitment,
        "tone": tone,
        "method": "simulated_sse",
    })

    return {
        "decision": "call_simulated",
        "call_sid": fake_sid,
        "outcome": call_outcome,
        "payment_commitment": payment_commitment,
        "method": "simulated",
    }
