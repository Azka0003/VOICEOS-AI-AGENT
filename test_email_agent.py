"""
VoiceOS — Standalone Email Agent (Groq Edition)
-----------------------------------------------
Run: python test_email_agent.py

Requires:
    pip install langchain-groq python-dotenv

In .env:
    GROQ_API_KEY=gsk_...
    GMAIL_ADDRESS=...
    GMAIL_APP_PASSWORD=...
"""

import os
import json
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from dotenv import load_dotenv
from langchain_groq import ChatGroq

load_dotenv()

# ─── CONFIG ───────────────────────────────────────────────────────────────────

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

COMMS_LOG = "data/client_comms.json"

# ─── MOCK DATA ────────────────────────────────────────────────────────────────

MOCK_INVOICES = [
    {"id": "INV001", "client": "Raj Traders",   "amount": 45000, "due_date": "2025-03-01", "status": "overdue", "days_overdue": 47},
    {"id": "INV002", "client": "Raj Traders",   "amount": 12000, "due_date": "2025-03-15", "status": "overdue", "days_overdue": 33},
    {"id": "INV005", "client": "Noor Supplies", "amount": 15000, "due_date": "2025-03-20", "status": "overdue", "days_overdue": 28},
]

# ─── LLM (GROQ) ───────────────────────────────────────────────────────────────

# Using Llama 3.3 70B - it's incredibly fast and follows instructions perfectly
llm = ChatGroq(
    model_name="llama-3.3-70b-versatile",
    groq_api_key=GROQ_API_KEY,
    temperature=0.7
)

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def get_client_invoices(client_name: str) -> list:
    return [inv for inv in MOCK_INVOICES if inv["client"].lower() == client_name.lower()]


def get_contact_history(client_name: str) -> list:
    if not os.path.exists(COMMS_LOG):
        return []
    try:
        with open(COMMS_LOG) as f:
            data = json.load(f)
        return data.get(client_name, {}).get("contacts", [])
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def determine_tone(contact_count: int) -> str:
    """Escalates tone based on number of prior emails sent."""
    if contact_count == 0:
        return "friendly_reminder"
    elif contact_count == 1:
        return "urgent_followup"
    else:
        return "final_notice"


TONE_LABELS = {
    "friendly_reminder": "Friendly Payment Reminder",
    "urgent_followup":   "Urgent: Payment Required - Action Needed",
    "final_notice":      "Final Notice Before Legal Action",
}

TONE_PROMPTS = {
    "friendly_reminder": "Write a polite, professional payment reminder email.",
    "urgent_followup":   "Write a firm, professional payment demand email. Mention a 7-day deadline.",
    "final_notice":      "Write a serious final notice email. Mention that if not resolved in 3 days, legal action may be considered.",
}


def generate_email_body(client: str, invoices: list, tone: str) -> str:
    total = sum(inv["amount"] for inv in invoices)
    invoice_lines = "\n".join(
        f"  - {inv['id']}: ₹{inv['amount']:,} (due {inv['due_date']}, {inv['days_overdue']} days overdue)"
        for inv in invoices
    )

    prompt = f"""
{TONE_PROMPTS[tone]}

Client name: {client}
Total outstanding: ₹{total:,}
Invoices list:
{invoice_lines}

Instructions:
1. Address the client by name.
2. Be professional and clear.
3. Provide ONLY the email body (no subject line, no extra chatter).
4. Sign off as: VoiceOS Collections Team
"""
    # Groq is usually 10x faster than Gemini
    response = llm.invoke(prompt)
    return response.content.strip()


def send_email(to_address: str, subject: str, body: str) -> bool:
    try:
        msg = MIMEMultipart()
        msg["From"] = GMAIL_ADDRESS
        msg["To"] = to_address
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, to_address, msg.as_string())
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False


def log_to_comms(client: str, subject: str, body: str, tone: str, sent: bool):
    os.makedirs("data", exist_ok=True)
    data = {}
    if os.path.exists(COMMS_LOG):
        try:
            with open(COMMS_LOG) as f:
                data = json.load(f)
        except json.JSONDecodeError:
            data = {}

    if client not in data:
        data[client] = {"contacts": []}

    data[client]["contacts"].append({
        "type": "email",
        "timestamp": datetime.now().isoformat(),
        "tone": tone,
        "subject": subject,
        "email_body": body,
        "outcome": "sent" if sent else "failed"
    })

    with open(COMMS_LOG, "w") as f:
        json.dump(data, f, indent=2)


# ─── MAIN AGENT FUNCTION ──────────────────────────────────────────────────────

def run_email_agent(client_name: str, to_address: str):
    print(f"\n{'='*60}")
    print(f"GROQ EMAIL AGENT — TARGET: {client_name}")
    print(f"{'='*60}")

    # 1. Fetch invoices
    invoices = get_client_invoices(client_name)
    if not invoices:
        print(f"[!] No overdue invoices found for {client_name}")
        return

    # 2. Check contact history to escalate tone
    history = get_contact_history(client_name)
    email_count = sum(1 for c in history if c["type"] == "email" and c["outcome"] == "sent")
    tone = determine_tone(email_count)
    subject = TONE_LABELS[tone]

    print(f"[✓] History: {email_count} sent email(s).")
    print(f"[✓] Current Strategy: {tone.upper()}")

    # 3. Generate email body via Groq
    print("[...] Generating professional draft via Groq...")
    try:
        body = generate_email_body(client_name, invoices, tone)
    except Exception as e:
        print(f"[✗] LLM Error: {e}")
        return

    # 4. HUMAN IN THE LOOP — preview before sending
    print(f"\n{'─'*60}")
    print(f"SUBJECT: {subject}")
    print(f"TO:      {to_address}")
    print(f"{'─'*60}")
    print(body)
    print(f"{'─'*60}")

    confirm = input("\n[HITL] Send this email? (yes / no / edit): ").strip().lower()

    if confirm == "edit":
        print("\nPaste your edited body below. Type 'DONE' on a new line when finished:")
        lines = []
        while True:
            line = input()
            if line.strip().upper() == "DONE":
                break
            lines.append(line)
        body = "\n".join(lines)
        confirm = "yes"

    if confirm != "yes":
        print("[✗] Action cancelled by user.")
        return

    # 5. Send
    print("[...] Sending via SMTP...")
    sent = send_email(to_address, subject, body)

    if sent:
        print(f"[✓] SUCCESS: Email delivered to {to_address}")
    else:
        print(f"[✗] FAILURE: Could not send email. Check credentials.")

    # 6. Log
    log_to_comms(client_name, subject, body, tone, sent)
    print(f"[✓] Progress saved to {COMMS_LOG}")


# ─── RUN ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Test with Raj Traders
    run_email_agent(
        client_name="Raj Traders",
        to_address="farazstudy112@gmail.com" # <--- Change this to your test email
    )