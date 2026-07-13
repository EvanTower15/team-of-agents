# Recovery Team 🩺🏋️

A team of specialist RAG agents that helps someone recover from an injury and get back to
activity. One chat interface; behind it, an orchestrator routes each question to the right
specialist — a **Physical Therapist agent** and a **Gym Trainer agent** (an Orthopedic
Surgeon agent arrives in Phase B) — each answering only from its own curated knowledge base.

> **Start here → [PROJECT_PLAN.md](PROJECT_PLAN.md)** — the living working document with
> current status, architecture, module contracts, and the phase plan. Read its §0 before
> making changes.
>
> **Then read → [Capabilities_Overview.md](Capabilities_Overview.md)** — an in-depth
> explanation of how every built part works and why (RAG core, agents, router,
> orchestrator, safety design), written for teammates and for whoever builds the
> presentation.

## Setup

```bash
git clone https://github.com/EvanTower15/team-of-agents.git
cd team-of-agents
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1   |   macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then paste your free Groq key (console.groq.com)
```

## Run

*(Available after Phase 5 — see PROJECT_PLAN.md §8 for what exists right now.)*

```bash
python -m src.ingest --agent pt
python -m src.ingest --agent trainer
streamlit run app.py
```

---

*OPIM 5517 team project — Evan, Ben, James. Educational support tool; not a substitute for
advice from a licensed clinician.*
