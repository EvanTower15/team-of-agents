# Recovery Team 🩹

A team of 4 specialist RAG agents that helps patients safely recover from an injury and return to full physical activity. One unified chat interface; behind it, an LLM router and LangGraph orchestrator route each question to the right specialist:
- **Orthopedic Surgeon agent** 🦴
- **Physical Therapist agent** 🩺
- **Gym Trainer agent** 🏋️
- **Sports Nutritionist agent** 🥗

Each agent answers from its own domain-siloed knowledge base, augmented by **GraphRAG multi-hop clinical knowledge graphs**, **CLIP multimodal visual exercise matching**, **Security Guardrail scanners**, and **Business Unit Economics tracking**.

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
# Rebuild all 4 specialist vector store indexes
python -m src.ingest --agent all

# Launch Streamlit web interface
streamlit run app.py
```

## E2E CLI & Automated Test Suite

```bash
# Run a question end-to-end directly in your terminal
python -m src.cli "How do I safely recover from an ACL knee surgery with PT exercises and post-op protein nutrition?"

# Run automated unit, E2E, GraphRAG, and High-Risk Patient Safety test suite
python -m pytest tests/ -v
```

---

*OPIM 5517 team project — Evan, Ben, James. Educational support tool; not a substitute for advice from a licensed clinician.*
