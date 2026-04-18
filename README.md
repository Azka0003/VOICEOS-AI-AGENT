Here is a comprehensive `README.md` specifically tailored for **DebtPilot**. It reflects the multi-agent architecture, the smart HITL system, and the dynamic Voice AI capabilities we've built.

***

# 🏦 DebtPilot: Autonomous AI Collections Agent

DebtPilot is an agentic AI system designed to manage B2B accounts receivable for the Indian market. It combines multi-agent orchestration with real-time Voice AI to handle overdue invoice reminders, risk assessment, and human-in-the-loop (HITL) escalations.

![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)
![React](https://img.shields.io/badge/React-18-61DAFB.svg)
![Groq](https://img.shields.io/badge/LLM-Groq_Llama_3.3-orange.svg)

---

## 🚀 Key Features

*   **🎙️ Dynamic Voice AI:** Real-time, low-latency phone calls via **Twilio** and **Deepgram Voice Agent**. The AI greets clients by name and discusses specific invoice amounts fetched from the database.
*   **🤖 Multi-Agent Orchestration:**
    *   `InvoiceAgent`: Queries and aggregates portfolio data.
    *   `RiskAgent`: Scores clients (0-100) based on payment history and disputes.
    *   `ActionAgent`: Decides between automated email, phone call, or HITL escalation.
    *   `EmailAgent`: Drafts professional, context-aware reminders.
*   **⚖️ Smart HITL (Human-in-the-Loop):** A threshold-based safety system that pauses execution only for high-risk scenarios, large amounts (>₹50k), or missing contact data.
*   **📊 Real-time Excel Sync:** Every agent action is synced between a `mock_invoices.json` source and a formatted `invoices.xlsx` for executive reporting.
*   **📜 Audit Lineage:** Every thought, LLM call, and human decision is logged in `lineage_log.json` for total transparency.
*   **🔄 LLM Router:** Smart failover between **Groq** (Primary) and **Ollama** (Local Fallback).

---

## 📂 Project Structure

```text
debtpilot/
├── backend/
│   ├── agents/           # Specialized AI Agents (Supervisor, Risk, etc.)
│   ├── data/             # JSON Database, Excel Sheets, and Lineage Logs
│   ├── tools/            # Logic for Twilio, Deepgram, Excel, and LLM Routing
│   ├── main.py           # FastAPI Server & WebSocket Handler
│   └── requirements.txt  # Python Dependencies
├── frontend/             # React + Vite Dashboard (Dashboard, HITL Panel)
├── .env                  # API Keys and Configuration
└── README.md
```

---

## 🛠️ Setup Instructions

### 1. Prerequisites
*   Python 3.11+
*   Node.js & npm (for Frontend)
*   [Ngrok](https://ngrok.com/) (for Twilio Webhook testing)
*   Ollama (optional, for local LLM fallback)

### 2. Environment Configuration
Create a `.env` file in the root directory:

```env
# LLM Providers
GROQ_API_KEY=gsk_your_key_here
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_SPEED_MODEL=llama-3.1-8b-instant

# Optional Ollama Fallback
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=phi3

# Voice & Communication
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=+1...
DEEPGRAM_API_KEY=...

# Infrastructure
BASE_URL=https://your-ngrok-url.ngrok-free.app
```

### 3. Backend Installation
```bash
cd backend
pip install -r requirements.txt
python main.py
```

### 4. Frontend Installation
```bash
cd frontend
npm install
npm run dev
```

---

## 📞 Testing the Voice Flow

1.  **Expose Port 8000:** Run `ngrok http 8000`.
2.  **Update BASE_URL:** Paste the ngrok URL into your `.env`.
3.  **Start Call:** Trigger a call via API:
    `GET http://localhost:8000/call/start?to_number=+91XXXXXXXXXX&client_name=Raj+Traders`
4.  **Approve HITL:** 
    *   Check `GET /hitl/pending`.
    *   Post approval: `POST /hitl/approve/{id}` with `{"approved": true}`.
5.  **Talk:** Answer your phone and interact with the AI.

---

## 🧠 Smart HITL Logic
The system automatically pauses for human review if:
*   Contact name is missing in the database.
*   The Risk Score is **≥ 71**.
*   Invoice amount is **> ₹50,000** AND **> 30 days overdue**.
*   An active **Dispute Flag** is detected.

---

## 🛡️ LLM Routing Policy
*   **Generation Mode:** Uses `llama-3.3-70b-versatile` for high-quality email drafting and risk analysis.
*   **Speed Mode:** Uses `llama-3.1-8b-instant` for sub-500ms voice latencies.
*   **Fallback:** If Groq limits are hit or the API is down, the system silently switches to **Ollama (Phi3)** to maintain service availability.

---

## 📝 License
Proprietary Demo - Developed for VoiceOS/DebtPilot.

***

### 💡 Pro Tip
Check `backend/data/lineage_log.json` after every run to see the "hidden" reasoning behind every agent decision!