# DebtPilot — Autonomous AR Collections Agent

> *"Because chasing payments shouldn't need a human co-pilot."*

DebtPilot is a fully autonomous, multi-agent AI system that calls overdue clients, emails them with escalating urgency, scores their risk, and updates your books — all without a human lifting a finger, unless the situation genuinely demands it.

---

## The Problem

B2B accounts receivable is one of the most manually intensive operations in any business. A collections team spends hours making awkward calls, drafting follow-up emails, tracking responses in spreadsheets, and deciding when to escalate. Most of this work is repetitive, rule-driven, and doesn't need a human — yet every business does it manually by default.

DebtPilot automates the entire cycle. The human is not removed from the loop. They are just no longer the default.

---

## The DICE Challenge — Real-Time AI Constraint

The hackathon's DICE constraint required AI responses within **5 seconds**, with sub-second latency for live voice interactions. This is the hardest constraint to satisfy in an agentic voice system because every millisecond of silence in a live phone call feels like a failure.

### How We Solved It: Cloud-Primary, Local-Fallback Architecture

**Groq as the Primary Engine**

For live calls, silence is the enemy. We use Groq's LPU (Language Processing Unit) infrastructure as our primary inference layer. Unlike GPU-based cloud providers, Groq's hardware is purpose-built for token generation throughput.

- Live call turns use `llama-3.1-8b-instant` via Groq — Time To First Token under 300ms consistently
- Risk scoring and email drafting use `llama-3.3-70b-versatile` — higher quality, still well within 5 seconds
- This split means a debtor on a live call never hears a pause; background agents get the smarter model

**Ollama as the Local Fallback**

A production system cannot fail because of an API rate limit or a network blip. We integrated Ollama running locally so that if Groq fails or slows down, the LLM Router silently reroutes the request to a locally-hosted model (`phi3` or `llama3.2`) with zero network latency. The debtor on the other end of the call never hears an error — they only hear the agent continuing the conversation.

**The LLM Router**

The bridge between these two layers is our custom `LLMRouter` class in `tools/llm_router.py`. It:

- Selects `speed` mode (Groq 8B) vs `generation` mode (Groq 70B) automatically based on which agent is calling it
- Detects Groq failures and falls back to Ollama within milliseconds
- Logs every call with `latency_ms` to `lineage_log.json` so the dashboard shows real performance data
- Means every agent in the system shares one LLM interface — no duplicated API logic anywhere

The result: we don't just meet the 5-second constraint. For live voice turns we average under 400ms end-to-end. For background tasks like risk scoring, we stay under 2 seconds. The constraint is structurally solved, not just optimistically hoped for.

---

## What the System Does, End to End

```
Batch trigger fires
        ↓
Supervisor wakes up, reads invoice Excel for actionable clients
        ↓
invoice_agent fetches unified context (Excel + ChromaDB)
        ↓
risk_agent scores each client 0–100 with transparent point breakdown
        ↓
action_agent routes each client:

  Raj Traders       → Live call  (high risk, phone available, 70+ days overdue)
  Mehta Enterprises → Final Notice email  (dispute on record, 2 prior contacts)
  Sharma Logistics  → Urgent Followup email  (60+ days, first contact)
  Noor Supplies     → Friendly Reminder email  (low risk, first contact)
  Apex Solutions    → HITL PAUSE  (contact details missing, ₹72k at stake)
  Crescent Tech     → Friendly Reminder email  (recently overdue, low risk)
        ↓
All outcomes written to invoices.xlsx in real time
All decisions logged to lineage_log.json with full reasoning
Frontend dashboard updates live via SSE
        ↓
One HITL card appears for Apex Solutions
Human approves with corrected contact name
Agent resumes and sends the email
        ↓
6 clients processed. 1 human decision made.
```

That last line is the pitch.

---

## Architecture

```
debtpilot/
│
├── backend/
│   ├── agents/
│   │   ├── supervisor.py        # Orchestrates the full batch pipeline
│   │   ├── invoice_agent.py     # Assembles unified context from Excel + ChromaDB
│   │   ├── risk_agent.py        # Scores clients 0–100, transparent point system
│   │   ├── action_agent.py      # Decision engine: call / email / escalate / HITL
│   │   └── email_agent.py       # Generates and sends context-aware emails
│   │
│   ├── tools/
│   │   ├── llm_router.py        # Groq → Ollama fallback, shared by all agents
│   │   ├── excel_tool.py        # Reads & writes invoices.xlsx with file locking
│   │   ├── chroma_tool.py       # ChromaDB client identity and history layer
│   │   ├── hitl_tool.py         # Smart HITL — pauses only when genuinely needed
│   │   ├── twilio_tool.py       # Places outbound calls via Twilio
│   │   ├── deepgram_tool.py     # Deepgram Voice Agent WebSocket bridge
│   │   └── lineage_logger.py    # Append-only audit log for every agent decision
│   │
│   ├── demo_engine.py           # Injects fresh demo invoices on every startup
│   ├── demo_actions.py          # Demo-safe call/email: real if creds exist, simulated via SSE if not
│   ├── startup.py               # Seeds ChromaDB + runs demo engine at boot
│   ├── main.py                  # FastAPI app — all routes, SSE stream, WebSocket
│   │
│   └── data/
│       ├── invoices.xlsx        # Live Excel sheet (agent reads and writes here)
│       ├── mock_invoices.json   # Source invoice data
│       ├── chromadb_documents.json  # Client identity and briefing documents
│       └── lineage_log.json     # Full audit trail of every agent action
│
└── frontend/
    └── src/
        ├── components/
        │   ├── Dashboard.jsx    # Portfolio view with agent decision preview
        │   ├── HITLPanel.jsx    # Pending approvals + decision log
        │   ├── AgentFeed.jsx    # Live stream of agent events
        │   ├── CallMonitor.jsx  # Live call transcript
        │   └── ExcelSync.jsx    # Real-time Excel row view
        └── App.jsx
```

---

## Agent Pipeline Detail

### Supervisor
Reads the Excel task queue, sorts clients by a composite priority score (risk × days overdue × amount), and routes each through the full pipeline. Holds a concurrency lock per invoice to prevent double-processing in parallel batch runs.

### Invoice Agent
The data assembler. Pulls from two mandatory sources: ChromaDB (client identity, payment history briefing, contact details) and Excel (current amounts, days overdue, next action code). Merges both into a single unified context object. If either source returns nothing, it triggers HITL rather than proceeding blind.

### Risk Agent
Scores each client 0–100 using a transparent point-based system:
- Days overdue component (up to 40 points)
- Active dispute flag (up to 35 points)
- Missing contact penalty (15 points)
- Repeated unanswered contact history (5 points)
- LLM qualitative assessment of payment history narrative (up to 10 points)

Returns a structured verdict with `risk_label`, `recommended_tone`, `confidence`, and `hitl_scenario` if applicable. Never decides what action to take — that is the Action Agent's job.

### Action Agent
The decision engine. Reads the `Next Action` column from Excel and routes:

| Next Action | What Happens |
|---|---|
| `schedule_call` | Places Twilio call (or simulates live via SSE in demo mode) |
| `send_friendly_reminder` | Generates and sends email, tone: friendly |
| `send_urgent_followup` | Generates and sends email, tone: firm |
| `send_final_notice` | Generates and sends email, tone: final notice |
| `escalate_to_legal` | Protected — flags for human, never auto-escalates |
| `resolve_contact_details` | Triggers HITL — missing contact blocks all outreach |

Protections: `escalate_to_legal` and `disputed_under_review` are read-only for agents. Only a human can set or clear these values.

### Email Agent
Reads the ChromaDB client briefing before writing a single word. Generates subject and body via LLM — no hardcoded templates. Applies a tone upgrade guard: if days overdue have crossed a threshold since the tone was originally set, it upgrades automatically (e.g. `friendly` → `urgent` if now 45+ days overdue). Writes outcomes back to both Excel and ChromaDB after sending.

---

## HITL — Human-in-the-Loop

HITL is not a fallback. It is a deliberate gate for situations that genuinely require human judgment:

- Contact details are missing (can't contact = can't automate)
- Active dispute + risk score ≥ 70 (human should own disputed high-risk accounts)
- Agent confidence below 0.5 (contradictory signals, score doesn't match days overdue)
- Amount over ₹50,000 + 45+ days overdue (high-stakes, human sign-off before escalation)

When HITL triggers, the agent pauses, a card appears on the HITL tab in the dashboard with full context (risk breakdown, decision tree, recommended options), and the human approves or overrides. The agent then resumes exactly where it left off.

---

## Demo Engine

On every backend startup, `demo_engine.py` injects 1–2 fresh invoice entries into the Excel and JSON data with today-relative due dates. This keeps `days_overdue` always real and gives the batch pipeline new actionable rows on every run. Six scenario templates are included covering every agent path (friendly email, urgent email, final notice, call trigger, missing contact HITL, dispute acknowledgment). After all six are used, the tracker resets for the next demo cycle.

---

## Demo-Safe Actions

`demo_actions.py` intercepts call and email execution with a two-path approach:

**If real credentials exist** — places an actual Twilio call or sends a real Gmail email to the addresses in the invoice data.

**If no credentials** — doesn't fail silently. Instead:
- For calls: streams a realistic back-and-forth transcript line by line through the SSE bus with natural delays, lighting up the Call Monitor tab in real time. The agent speaks, the client responds, a payment commitment is recorded.
- For emails: fires SSE events showing the subject line, tone, and delivery status in the Agent Feed.

After every action — real or simulated — outcomes are written back to Excel and logged to lineage, so the next batch run sees updated state and doesn't loop.

---

## Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- A Groq API key (free tier works fine for demos)

### Backend

```bash
cd voiceos/backend
pip install -r requirements.txt

# Copy and fill in your credentials
cp ../.env.example ../.env
```

`.env` keys:

```
GROQ_API_KEY=          # Required — get free at console.groq.com
LLM_PROVIDER=groq      # Use 'ollama' if running locally only

# Optional — system works in demo mode without these
GMAIL_ADDRESS=
GMAIL_APP_PASSWORD=
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_FROM_NUMBER=
DEEPGRAM_API_KEY=
BASE_URL=              # Your ngrok URL if using real Twilio calls

# Optional local fallback
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
```

Start the backend:

```bash
cd voiceos/backend
uvicorn main:app --reload --port 8000
```

On startup you will see the demo engine inject fresh invoice entries and ChromaDB seed confirmations in the terminal.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`

---

## Running the Demo

1. Start backend → watch terminal for demo engine injection logs
2. Open dashboard → Portfolio tab shows all clients with risk scores and agent decision previews
3. Click **Run Full Batch** → Agent Feed starts filling with decisions in real time
4. If a `schedule_call` client is processed → Call Monitor tab activates, transcript streams line by line
5. Email clients → Agent Feed shows subject line, tone, and sent/simulated status
6. Khan & Brothers (missing contact) → HITL badge appears on the HITL tab
7. Click into HITL tab → see the full risk breakdown and decision tree for the paused client
8. Approve with corrected contact info → agent resumes and sends the email

---

## Tech Stack

| Layer | Technology |
|---|---|
| LLM Primary | Groq (`llama-3.3-70b-versatile`, `llama-3.1-8b-instant`) |
| LLM Fallback | Ollama (`phi3`, `llama3.2`) |
| Voice Calls | Twilio + Deepgram Voice Agent |
| Email | Gmail SMTP |
| Backend | FastAPI, Python 3.11+ |
| Vector Store | ChromaDB |
| Live Updates | Server-Sent Events (SSE) |
| Data Store | openpyxl (Excel), JSON |
| Frontend | React 18, Vite |

---

## Key Design Decisions

**Excel as the state machine** — Every agent action writes back to `invoices.xlsx`. The Next Action column is the task queue. Days overdue are recalculated live on every read, never trusted from stored values. This means the system stays in sync with reality even if the backend restarts.

**ChromaDB for identity, Excel for numbers** — Client contact details and payment history narrative live in ChromaDB. Current amounts and task status live in Excel. Neither source is used blind — if either returns nothing, HITL triggers before any action is taken.

**No hardcoded email templates** — The Email Agent reads the ChromaDB client briefing before generating any email. The LLM writes fresh, context-specific content every time. The only constraint is the tone code (`friendly_reminder`, `urgent_followup`, `final_notice`).

**One LLM interface for all agents** — Every agent calls `llm_router.invoke()`. No agent imports an LLM library directly. This means fallback logic, logging, and model selection are handled in one place.

**Protected fields** — `escalate_to_legal` and `disputed_under_review` in the Next Action column cannot be overwritten by any agent. Only a human (via HITL approval or direct Excel edit) can set or clear these values. This is enforced at the `excel_tool` layer, not just in agent logic.