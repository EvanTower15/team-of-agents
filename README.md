# Recovery Team 🩹

A team of 4 specialist RAG agents that helps patients safely recover from an injury and return to full physical activity. One unified chat interface; behind it, an LLM router and LangGraph orchestrator route each question to the right specialist:
- **Orthopedic Surgeon agent** 🦴
- **Physical Therapist agent** 🩺
- **Gym Trainer agent** 🏋️
- **Sports Nutritionist agent** 🥗

Each agent answers from its own domain-siloed knowledge base, augmented by **GraphRAG multi-hop clinical knowledge graphs**, **CLIP multimodal visual exercise matching**, **Security Guardrail scanners**, and **metered unit-economics tracking**.

Conversations are **persisted to a local SQLite database**, so you can keep several recovery scenarios going at once and reopen any of them from the sidebar after a reload — each one comes back with its specialist badges, sources, and binding restrictions.

The app runs behind a **login**, meters what every question actually costs from Groq's own token counts, bills it against a **subscription-plus-overage plan**, and reports the economics to an **admin-only business console**. **Nothing is charged** — this is coursework, and the only missing piece of a real product is the payment processor.

> **Start here → [PROJECT_PLAN.md](PROJECT_PLAN.md)** — living status, architecture, module contracts, and phase plan.
>
> **Capabilities Overview → [Capabilities_Overview.md](Capabilities_Overview.md)** — in-depth technical explanation of GraphRAG, Multimodal Visual RAG, Security, and Unit Economics.

---

## Setup

```bash
git clone https://github.com/EvanTower15/team-of-agents.git
cd team-of-agents
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1   |   macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then paste your free Groq key (console.groq.com)
```

## Ingest & Run

```bash
# Build the 4 specialist vector store indexes (one agent per invocation)
python -m src.ingest --agent pt
python -m src.ingest --agent trainer
python -m src.ingest --agent surgeon
python -m src.ingest --agent nutrition

# Launch Streamlit web interface
streamlit run app.py
```

### Signing in

The app requires an account. Demo accounts are seeded automatically on first launch and shown on the sign-in screen — **nobody is charged**, so these are safe to share:

| Email | Password | What it shows |
|---|---|---|
| `demo@recoveryteam.app` | `recovery2026` | Free plan — 15 questions/month, 2 specialists, hits the upgrade wall |
| `paid@recoveryteam.app` | `recovery2026` | Recovery plan — all 4 specialists, 250 questions, then metered overage |
| `admin@recoveryteam.app` | `recovery2026` | Admin — adds the **📈 Business console** page (MRR, margin, capacity) |

You can also create your own account; new accounts start on Free.

Chat history is written to `data/chat_history.db` (gitignored) the first time you ask a question, scoped to the signed-in account. Use the sidebar's **Conversations** block to start a new chat, reopen a past one, or delete one; set `CHAT_DB_URL` to point the app at a different database file.

### Cost tracking

Two views over the same metered data, for two audiences:

- **📊 Observability tab** (everyone) — real per-call token counts, latency, and throttling by pipeline stage.
- **📈 Business console** (admin only) — revenue, per-route gross margin, and the capacity ceiling.

Prices live in one place, `src/business/pricing.py`, verified against Groq's published rates.

## E2E CLI & Automated Test Suite

```bash
# Run a question end-to-end directly in your terminal
python -m src.cli "How do I safely recover from an ACL knee surgery with PT exercises and post-op protein nutrition?"

# Run automated unit, E2E, GraphRAG, and High-Risk Patient Safety test suite
python -m pytest tests/ -v
```

---

*OPIM 5517 team project — Evan, Ben, James. Educational support tool; not a substitute for advice from a licensed clinician.*
