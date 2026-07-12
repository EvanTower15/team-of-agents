# Recovery Team — Implementation Plan (Phase A: PT + Gym Trainer agents)

> **Living working document.** This file is the single source of truth for project state.
> It IS committed to the repo (unlike a scratch plan) because the whole team — humans and
> AI coding agents — works from it on GitHub. Read [§0 How to use this document](#0-how-to-use-this-document)
> before making changes anywhere in the repo.
>
> **Status: PHASE 0 COMPLETE (2026-07-12). Next up: Phase 1 (shared RAG core + agent base, James) — Phase 4 (Ben) may also start now against stub agents. Open leftover: each teammate needs their own free Groq key at console.groq.com in their local `.env`.**
>
> *(As each phase completes, append a dated "Phase N results" block directly below this
> line, newest first. Keep every result block forever — they are the project memory.)*
>
> **Phase 0 results (2026-07-12)** — Scaffolding on `main` (commit `8413faf`): README stub,
> `.gitignore`, `.env.example` (GROQ_API_KEY only), `requirements.txt` (§3 verbatim), package
> skeleton (`src/`, `src/agents/`, `data/pt/`, `data/trainer/`). Verified
> `pip install --dry-run -r requirements.txt` resolves clean on Python 3.13.5 / Windows.
> Branch protection ON for `main`: force-pushes and branch deletion blocked; PR review
> requirement was enabled then turned back OFF same day per team preference (decision D7).
> Note: `rough_sketch_ideas` was deleted pre-commit — its content is preserved in §1 and in
> `recovery_team_rag_architecture.svg` (committed in `2dda496`). Ben & James invited as
> collaborators (2026-07-12, Evan). **REMAINING USER ACTION:** share the console.groq.com
> signup link with Ben & James (each needs their own free key in their local `.env` — the
> router, both specialist agents, and synthesis all call Groq's `llama-3.3-70b-versatile`);
> each teammate should verify a fresh-venv install per Phase 0's done-when.

---

## 0. How to use this document

**For every teammate and every AI agent working in this repo:**

1. **Before starting work:** read the Status block above, find your phase in [§8](#8-phase-plan),
   and confirm its dependencies are marked complete.
2. **While working:** follow the interface contracts in [§5](#5-module-contracts--work-in-parallel-safely)
   exactly. They exist so phases can proceed in parallel without merge pain. If you must
   change a contract, update this file in the same PR and flag it in the PR description.
3. **When you finish a phase:**
   - Tick the checkboxes in your phase's task list ([§8](#8-phase-plan)).
   - Append a **"Phase N results (YYYY-MM-DD)"** block under the Status line at the top:
     what was built, key facts discovered (gotchas, versions, data quirks), anything the
     next phase needs to know. Model: 3–10 dense lines. Never delete old result blocks.
   - Update the **Status:** line itself to point at the next phase.
   - Log any decision that deviates from this plan in [§10 Decision log](#10-decision-log).
4. **Branch & PR workflow:** branch from `main` as `feat/<phase-short-name>`
   (e.g. `feat/pt-agent`), open a PR to `main`, request one teammate review. Never commit
   directly to `main` after Phase 0. Never commit `.env`, `chroma_db/`, or raw scraped data
   that has licensing question marks.

---

## 1. What we are building

A **team of specialist RAG agents** that helps someone recover from an injury and get back
to activity. One chat interface; behind it, an orchestrator routes each question to the
right specialist(s), the specialists answer **only from their own curated knowledge base**
(RAG — no free-wheeling LLM answers), and a synthesizer merges their inputs into one
coherent "care team" response.

From the original brainstorm (`rough_sketch_ideas`, since deleted — key points preserved here):

- **Problem:** single LLMs hallucinate, forget instructions, and can't credibly impersonate
  multiple experts simultaneously. Separate agents with separate grounded corpora fix all three.
- **Target users:** people with physical-therapy needs; elderly people who just need to get active.
- **Value:** cheaper than a DPT visit, cheaper than a gym trainer who doesn't know PT, more
  versatile than siloed providers, customized to the individual.
- **Course deliverables this feeds:** product report (800–1500 words, James), high-level
  design sketch, video demonstration.

### Scope of Phase A (this plan)

| Agent | In Phase A? | Notes |
|---|---|---|
| 🩺 Physical Therapist | **YES** | Rehab protocols, pain-vs-soreness guidance, mobility/ROM work |
| 🏋️ Gym Trainer | **YES** | Programming, progressive overload, form, general fitness for beginners/elderly |
| 🦴 Orthopedic Surgeon | **NO — Phase B** | Deferred. In Phase A, "red-flag" medical questions get a safety response advising a clinician visit (see [§7](#7-safety--scope-guardrails)). §11 documents exactly how the surgeon slots in later. |

---

## 2. Reference architecture (what we copy from `opim-5517`)

The UConn OPIM 5517 CT-business RAG project is our architectural template. Our version is
deliberately **smaller** (no SQL chain, no property graph, no eval framework in Phase A),
but the same layered pattern. Everything a builder needs is described in this plan — you do
**not** need access to that repo. The borrowed patterns:

| Pattern | opim-5517 original | Our version |
|---|---|---|
| RAG core module | `src/retrieval.py`: load → `RecursiveCharacterTextSplitter(1000, 150)` → embed → Chroma persist → `retrieve_context(q, k=4)` retrieval-only entry point separate from synthesis | `src/rag_core.py`, identical flow, but **parameterized by collection name** so each agent owns a collection in one Chroma dir |
| Hybrid router | `src/router.py`: weighted regex cue scorer → confidence; below threshold, fall back to a Groq LLM classifier; below that, CLARIFY. Returns a `RouteDecision` dataclass (label, confidence, reasoning, method, scores) | Same design, different cue sets ([§6.2](#62-router)) |
| Orchestrator | `src/agentic_workflow.py`: LangGraph `StateGraph` over a `TypedDict` state; one node per tool; conditional edges; every node captures its own errors into state (never raises); `synthesize_answer` merges evidence; `fallback_handler` for dead ends; additive `execution_trace` for debugging | Same design; specialist agents are the "tools" ([§6.3](#63-langgraph-workflow)) |
| Front-end | `app.py` Streamlit: chat UI + sources expander + sidebar controls | Same, plus per-agent attribution badges ([§8 Phase 5](#phase-5--streamlit-app)) |
| Config | `.env` via python-dotenv, `.env.example` committed, keys never committed | Same |

Key simplifications vs opim-5517: one LLM provider (Groq) instead of Gemini+Groq; **local
embeddings** instead of a rate-limited embeddings API (see decision log D2); pre-curated
corpus files committed to `data/` instead of live ingestion scripts hitting APIs.

---

## 3. Tech stack

| Layer | Choice | Why |
|---|---|---|
| LLM | **Groq** `llama-3.3-70b-versatile`, `temperature=0.2` | Free tier, fast; named in the rough sketch; same model opim-5517 uses for routing/synthesis |
| Embeddings | **`sentence-transformers/all-MiniLM-L6-v2`** via `langchain-huggingface` | Free, runs locally, zero API keys/rate limits. opim-5517's Gemini embeddings needed 60-second sleeps between batches — we skip that whole class of problem. Corpus is small; quality is fine. (Decision D2) |
| Vector DB | **ChromaDB**, embedded, persisted to `./chroma_db/`, one **collection per agent** (`pt_docs`, `trainer_docs`) | Same as opim-5517; per-agent collections keep each specialist's knowledge cleanly siloed — that siloing IS the product thesis |
| Orchestration | **LangGraph** `StateGraph` | Same as opim-5517; gives us the agent-to-agent handoff for free via shared state |
| UI | **Streamlit** chat | Same as opim-5517 |
| Secrets | `.env` + `python-dotenv`; only key needed: `GROQ_API_KEY` (free at console.groq.com) | |

`requirements.txt` (Phase 0 creates this; pin looser only if installs fail):

```
streamlit>=1.35.0
langchain>=0.2.0
langchain-community>=0.2.0
langchain-groq>=0.1.0
langchain-huggingface>=0.1.0
sentence-transformers>=3.0.0
langchain-chroma>=0.1.0
chromadb>=0.5.0
langgraph>=1.0.0
langchain-text-splitters>=0.2.0
python-dotenv>=1.0.0
pypdf>=4.0.0
```

---

## 4. Repository layout (target state, end of Phase A)

```
team-of-agents/
├── PROJECT_PLAN.md            # ← this file (living doc)
├── README.md                  # short: what it is, setup, run (Phase 0 stub, Phase 6 polish)
├── app.py                     # Streamlit chat UI (Phase 5)
├── requirements.txt           # (Phase 0)
├── .env.example               # GROQ_API_KEY=  (Phase 0)
├── .gitignore                 # .env, chroma_db/, __pycache__, .venv (Phase 0)
├── recovery_team_rag_architecture.svg  # high-level design sketch (course deliverable)
├── data/
│   ├── pt/                    # PT corpus: .pdf/.txt/.md files (Phase 2)
│   ├── trainer/               # Trainer corpus (Phase 3)
│   └── SOURCES.md             # per-file provenance + license note (Phases 2–3)
├── src/
│   ├── __init__.py
│   ├── rag_core.py            # shared load/chunk/embed/retrieve, per-collection (Phase 1)
│   ├── ingest.py              # CLI: python -m src.ingest --agent pt|trainer (Phase 1)
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py            # SpecialistAgent base class (Phase 1)
│   │   ├── physical_therapist.py   # persona + collection binding (Phase 2)
│   │   └── gym_trainer.py          # persona + collection binding (Phase 3)
│   ├── router.py              # hybrid rules→LLM route classifier (Phase 4)
│   └── orchestrator.py        # LangGraph team workflow (Phase 4)
└── chroma_db/                 # generated, gitignored
```

---

## 5. Module contracts — work in parallel safely

These signatures are **frozen** once Phase 0 merges. Build to them; stub what you depend on.

### 5.1 `src/rag_core.py` (Phase 1)

```python
CHROMA_PERSIST_DIR = "chroma_db"

def ingest_folder(folder: str, collection_name: str) -> int:
    """Load all .pdf/.txt/.md in folder, chunk (1000 chars / 150 overlap),
    embed locally, persist to the named Chroma collection. Returns chunk count.
    Re-running re-adds; use clear_collection() first for a fresh build."""

def retrieve(question: str, collection_name: str, k: int = 4) -> list:
    """Top-k similarity search. Returns list[Document]. Raises FileNotFoundError
    with a helpful message if the collection has never been built."""

def clear_collection(collection_name: str) -> None: ...
def get_llm():
    """Cached ChatGroq(model='llama-3.3-70b-versatile', temperature=0.2).
    Raises EnvironmentError naming .env.example if GROQ_API_KEY is missing."""
```

### 5.2 `src/agents/base.py` (Phase 1)

```python
class SpecialistAgent:
    name: str              # "physical_therapist"
    display_name: str      # "Physical Therapist"
    collection_name: str   # "pt_docs"
    persona_prompt: str    # system prompt; MUST include the grounding rule (§7)

    def consult(self, question: str, peer_context: str | None = None) -> dict:
        """Retrieve from own collection, answer in persona from ONLY that context.
        peer_context = another agent's draft answer (agent-to-agent handoff).
        NEVER raises — errors go in the 'error' field (opim-5517 convention:
        one failing tool must not crash the graph).

        Returns: {
          "agent":   str,             # self.name
          "answer":  str,             # specialist draft, or "" on error
          "sources": list[str],       # de-duped source filenames used
          "error":   str | None,
        }"""
```

Each concrete agent file (`physical_therapist.py`, `gym_trainer.py`) just subclasses with
its persona and collection, and adds a `__main__` CLI so it is testable standalone:

```
python -m src.agents.physical_therapist "My knee aches after squats — normal?"
```

### 5.3 `src/router.py` (Phase 4) — route labels

```python
PT_ONLY = "PT_ONLY"; TRAINER_ONLY = "TRAINER_ONLY"; TEAM = "TEAM"
CLARIFY = "CLARIFY"; RED_FLAG = "RED_FLAG"
# Phase B adds: SURGEON = "SURGEON"

def classify(question: str) -> RouteDecision:
    """RouteDecision(label, confidence: float, reasoning: str,
    method: 'rules'|'llm', scores: dict). Rules first; Groq LLM fallback when
    rules confidence < 0.62; LLM confidence < 0.50 collapses to CLARIFY."""
```

### 5.4 `src/orchestrator.py` (Phase 4)

```python
def answer_question(question: str) -> dict:
    """Runs the LangGraph. Returns: {
      "final_answer": str,
      "route": str, "route_confidence": float,
      "agents_consulted": list[str],
      "sources": dict[str, list[str]],   # agent name -> source files
      "execution_trace": list[str],
    }"""
```

`app.py` calls **only** `answer_question()`. Nothing in the UI touches agents directly.

---

## 6. Orchestration design

### 6.1 Flow

```
START → route_question ─┬─ PT_ONLY      → consult_pt ─────────────────────────┐
                        ├─ TRAINER_ONLY → consult_trainer ─────────────────────┤
                        ├─ TEAM         → consult_pt → consult_trainer(+pt) ───┤
                        ├─ RED_FLAG     → safety_response → END                │
                        └─ CLARIFY      → ask_clarification → END              ▼
                                                            synthesize_team_answer → END
                 (agent error / zero passages retrieved) → fallback_handler → END
```

- **The TEAM route is the agent-to-agent framework from the sketch.** PT runs **first**
  (clinical constraints outrank programming preferences); the trainer node receives the
  PT's draft as `peer_context` and must respect its restrictions (e.g. "PT says no loaded
  knee flexion past 90° — so we substitute box squats"). This ordering is a deliberate
  safety property: document it in the report.
- The graph is a DAG — no cycles, cannot loop.
- Empty retrieval **with no error** still flows to synthesis (which honestly says the team
  doesn't have material on that); only hard errors hit `fallback_handler`. (opim-5517
  convention, proven out in its HW6.)

### 6.2 Router

Same hybrid strategy as opim-5517's `router.py`: weighted case-insensitive regex cues →
confidence score → Groq LLM classifier only when rules are unsure → CLARIFY when even the
LLM is unsure. Most queries never hit the LLM; the rules path is fully debuggable via
`RouteDecision.scores`.

Starting cue sets (Phase 4 tunes weights against the [§9](#9-evaluation-battery) battery):

- **PT cues:** pain, hurt/aches, injury/injured, rehab, recovery, physical therapy/PT,
  post-op / after surgery, range of motion, stretch, sprain/strain, swelling, stiff,
  mobility, tendon/ligament/meniscus/rotator cuff
- **Trainer cues:** workout, gym, program/plan/routine, sets, reps, strength, cardio,
  progressive overload, dumbbell/barbell/machine, form/technique, warm-up, beginner,
  get active / get in shape
- **TEAM:** both sides score ≥ 1 and neither dominates ≥ 70% (opim-5517's HYBRID logic) —
  e.g. "8 weeks post-meniscus-repair, how do I get back into lifting safely?"
- **RED_FLAG (checked FIRST, before scoring — always wins):** severe/sharp/unbearable pain,
  numbness/tingling, can't bear weight, visible deformity, fever + joint, calf swelling,
  chest pain, surgical wound/incision issues. → canned safety response ([§7](#7-safety--scope-guardrails)), no LLM.
- **CLARIFY:** no cues and the question is short/subjective ("what's best?", "help").

### 6.3 LangGraph workflow

`TypedDict` state, all fields optional, mirroring opim-5517's `AgentState`:

```python
class TeamState(TypedDict, total=False):
    question: str
    route: str; route_confidence: float; route_reasoning: str; route_method: str
    pt_result: dict          # SpecialistAgent.consult() output
    trainer_result: dict
    final_answer: str
    sources: dict            # agent -> [filenames]
    needs_clarification: bool; clarification_question: str
    fallback_reason: str
    execution_trace: Annotated[list, operator.add]   # one line per node
```

**Synthesis node** ("care coordinator") prompt requirements: merge the specialist drafts
into one answer that (a) uses ONLY the drafts as evidence, (b) attributes advice —
"Your physical therapist advises… Your trainer suggests…", (c) surfaces conflicts instead
of averaging them, PT wins on safety, (d) ends with the standing disclaimer ([§7](#7-safety--scope-guardrails)).
Single-agent routes still pass through synthesis for consistent voice + disclaimer.

---

## 7. Safety & scope guardrails

This is health-adjacent software. Non-negotiables, enforced in code, not vibes:

1. **Grounding rule** — every persona prompt contains: *"Use ONLY the provided context.
   If the context does not cover the question, say you don't have material on it and do
   not improvise."* (Same rule as opim-5517's `_SYSTEM_PROMPT`; it is the anti-hallucination
   backbone of the whole product.)
2. **Standing disclaimer** — every final answer ends with a fixed one-liner: educational
   support, not a substitute for a licensed clinician's advice. Lives in one constant in
   `orchestrator.py`, appended by the synthesis/safety/clarify nodes — not left to the LLM.
3. **RED_FLAG short-circuit** — deterministic, canned, no-LLM response: stop activity,
   contact your surgeon/doctor or urgent care. In Phase B this route becomes the surgeon
   agent's front door.
4. **No memory of the user in Phase A** — no PII stored; each question stands alone.
   (Chat history in the Streamlit session is display-only.) Personalization is a Phase B+
   discussion.
5. **Corpus licensing** — prefer US-government public-domain sources (see §8 Phases 2–3);
   every file in `data/` gets a line in `data/SOURCES.md` (URL, date fetched, license).
   No pirated textbooks, no wholesale scraping of copyrighted commercial sites.

---

## 8. Phase plan

Ownership from `rough_sketch_ideas`: **Evan** — Git/repo; **Ben** — Groq + agent-to-agent +
orchestrator; **James** — PT agent + PT vector DB/RAG (+ product report).
⚠️ **The Gym Trainer agent (Phase 3) has no owner in the sketch — assign at next team sync**
(suggestion: Evan, since Phase 0 is light; it's also the best template-follower task).

Dependency shape: `0 → 1 → {2 ∥ 3} → 4 → 5 → 6`, **but** contracts in §5 let Phase 4 start
against stubbed agents any time after Phase 0, in parallel with 1–3.

### Phase 0 — Repo scaffolding — **Evan**

- [x] First commit on `main`: this file + design sketch SVG + `README.md` stub +
      `.gitignore` (`.env`, `chroma_db/`, `__pycache__/`, `.venv/`, `*.pyc`) +
      `.env.example` (`GROQ_API_KEY=`) + `requirements.txt` (§3) + empty package skeleton
      (`src/__init__.py`, `src/agents/__init__.py`, `data/pt/.gitkeep`, `data/trainer/.gitkeep`)
- [x] Push `main`; enable branch protection on GitHub (no force-push/deletion; PR review
      requirement toggled off per team preference — see D7)
- [x] Invite Ben & James as collaborators
- [ ] Share Groq key-signup link (console.groq.com — free) with Ben & James
- **Done when:** all three teammates can clone, `pip install -r requirements.txt` succeeds
  on a fresh venv (Python 3.11+), and a PR from a test branch shows the review requirement.

### Phase 1 — Shared RAG core + agent base — **James**

- [ ] `src/rag_core.py` per contract §5.1 (port opim-5517 `retrieval.py` flow: loaders for
      pdf/txt/md → `RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150,
      add_start_index=True)` → `HuggingFaceEmbeddings("sentence-transformers/all-MiniLM-L6-v2")`
      → `Chroma(persist_directory, collection_name)`)
- [ ] `src/ingest.py` CLI: `python -m src.ingest --agent pt` ingests `data/pt/` →
      collection `pt_docs` (and `--agent trainer` → `trainer_docs`); `--fresh` flag clears first
- [ ] `src/agents/base.py` per contract §5.2 (retrieve → persona prompt → `get_llm()` →
      answer; never raises; `peer_context` injected into the prompt when present)
- **Done when:** a throwaway txt file in `data/pt/` can be ingested and a base-class agent
  answers a question about it with correct source attribution, and a deliberately broken
  case (no collection built) returns `error` instead of raising.

### Phase 2 — Physical Therapist agent — **James**

- [ ] Corpus into `data/pt/` (~10–30 documents is plenty). Suggested public-domain-first
      sources: MedlinePlus rehab/injury pages (public domain), NIH/NIA "Exercise & Physical
      Activity" guides, CDC injury-basics pages; NHS rehab leaflets are OGL-licensed
      (reuse with attribution) — log everything in `data/SOURCES.md`
- [ ] `src/agents/physical_therapist.py`: persona = licensed-DPT voice; scope = rehab
      progression, pain vs. soreness, ROM/mobility, when to regress an exercise; explicitly
      instructed to defer diagnosis to clinicians; grounding rule verbatim (§7.1)
- [ ] CLI smoke test (§5.2) on ≥ 5 questions from the §9 battery; paste transcript
      highlights into the phase-results block
- **Done when:** PT battery questions get grounded, persona-consistent, source-cited
  answers, and an out-of-scope question ("best protein powder?") gets an honest
  "not my area" rather than an improvised answer.

### Phase 3 — Gym Trainer agent — **OWNER TBD** *(can run parallel with Phase 2)*

- [ ] Corpus into `data/trainer/`. Suggested: **HHS Physical Activity Guidelines for
      Americans, 2nd ed.** (public domain, excellent), CDC physical-activity pages, NIA
      exercise guides for older adults (nails the "elderly getting active" persona from the
      sketch), **US Army FM 7-22** strength/conditioning chapters (public domain)
- [ ] `src/agents/gym_trainer.py`: persona = certified-trainer voice; scope = programming,
      progressive overload, form cues, beginner/elderly modifications; explicitly defers
      pain/injury questions to the PT; grounding rule verbatim
- [ ] CLI smoke test on ≥ 5 battery questions, incl. one with `peer_context` set to a fake
      PT draft with a restriction — verify the trainer's answer respects it
- **Done when:** same bar as Phase 2, plus the `peer_context`-respect test passes.

### Phase 4 — Router + orchestrator — **Ben** *(contracts allow starting right after Phase 0 with stub agents)*

- [ ] `src/router.py` per §5.3/§6.2: RED_FLAG regex check first; weighted cue scorer;
      Groq LLM fallback (port opim-5517's robust `LABEL | confidence | reason` parser —
      it tolerates messy LLM output); thresholds 0.62 rules / 0.50 clarify as starting values
- [ ] `src/orchestrator.py` per §5.4/§6.3: LangGraph nodes `route_question`, `consult_pt`,
      `consult_trainer`, `synthesize_team_answer`, `safety_response`, `ask_clarification`,
      `fallback_handler`; conditional edges per §6.1; TEAM route passes PT draft as trainer's
      `peer_context`; disclaimer constant appended in code
- [ ] `__main__` CLI: `python -m src.orchestrator "question"` prints route, trace, answer
- [ ] Run the FULL §9 battery; record route + confidence + method for every question in
      the phase-results block; tune cue weights until routing table is ≥ 90% correct
- **Done when:** battery routing ≥ 90%, TEAM questions produce answers citing both agents,
  a RED_FLAG question never reaches an LLM, and killing the Chroma dir produces a graceful
  fallback answer, not a stack trace.

### Phase 5 — Streamlit app — **OWNER TBD (suggest Ben, owns the API it calls)**

- [ ] `app.py`: chat UI over `answer_question()`; per-message badge showing which
      specialist(s) contributed (🩺/🏋️); expander with per-agent source files; sidebar:
      route + confidence + execution trace (debug view), "rebuild knowledge bases" button
      shelling to the two ingest commands
- [ ] README: setup → ingest → run, with screenshots
- **Done when:** fresh clone → `.env` → ingest both agents → `streamlit run app.py` →
  a TEAM question shows both badges and both source lists. This exact flow is the video-demo
  script.

### Phase 6 — Evaluation & demo assets — **whole team; James leads report**

- [ ] Freeze the §9 battery results as a table (question → route → agents → verdict) —
      this is the report's evidence section
- [ ] 3 killer comparison artifacts for the report/video: (1) TEAM question where trainer
      visibly defers to PT constraint; (2) RED_FLAG safety short-circuit; (3) out-of-corpus
      question answered honestly with "no material" instead of hallucination — screenshot all three
- [ ] Record video demo (Phase 5 flow); export design sketch (§6.1 diagram, prettified)
- [ ] Product report drafted (800–1500 words) mapping to the rough-sketch bullets
- **Done when:** report, sketch, and video are in the repo (or linked from README) and the
  Status block at the top of this file says **PHASE A COMPLETE**.

---

## 9. Evaluation battery

The shared routing/answer test set. Phases 2–4 test against it; Phase 6 freezes results.
Add rows as edge cases emerge (log the addition in §10).

| # | Question | Expected route | Expect in answer |
|---|---|---|---|
| 1 | "My knee aches going down stairs since I sprained it — which exercises help?" | PT_ONLY | rehab progression, cited PT sources |
| 2 | "Give me a 3-day beginner strength program." | TRAINER_ONLY | structured program, cited trainer sources |
| 3 | "I'm 8 weeks post-meniscus surgery — how do I get back into lifting safely?" | TEAM | PT constraints + trainer plan that respects them |
| 4 | "My calf is swollen, hot, and I have sharp pain when I stand." | RED_FLAG | canned urgent-care response, no LLM |
| 5 | "Help" | CLARIFY | one focused follow-up question |
| 6 | "Is soreness two days after a workout normal or an injury?" | TEAM (accept PT_ONLY) | pain-vs-soreness explanation |
| 7 | "I'm 70 and haven't exercised in years. Where do I start?" | TRAINER_ONLY (accept TEAM) | elderly-appropriate on-ramp |
| 8 | "How much protein should I eat to build muscle?" | TRAINER_ONLY | honest scope-limits if corpus is thin |
| 9 | "My shoulder ROM is limited after rotator cuff rehab — stretches?" | PT_ONLY | ROM/mobility guidance |
| 10 | "I felt a pop in my knee at the gym and now it buckles." | RED_FLAG | urgent evaluation advice |
| 11 | "What's the best gym?" | CLARIFY | clarifying question |
| 12 | "Can I do cardio while rehabbing an ankle sprain?" | TEAM | PT clearance framing + trainer alternatives |

---

## 10. Decision log

| # | Date | Decision | Why |
|---|---|---|---|
| D1 | 2026-07-12 | Mirror opim-5517 architecture (RAG core / hybrid router / LangGraph / Streamlit), simplified | Proven in coursework; team already understands it; battle-tested error-handling conventions |
| D2 | 2026-07-12 | Local sentence-transformers embeddings instead of Gemini/OpenAI | Zero cost, zero keys, zero rate limits (Gemini free tier forced 60 s sleeps per 100 chunks in opim-5517); corpus small enough that quality difference is immaterial |
| D3 | 2026-07-12 | One Chroma dir, one collection per agent | Knowledge siloing per specialist is the core product thesis; also lets agents rebuild independently |
| D4 | 2026-07-12 | PT runs before Trainer on TEAM route; trainer receives PT draft as `peer_context` | Clinical constraints must bound the training plan, not vice versa — this IS the agent-to-agent story for the report |
| D5 | 2026-07-12 | RED_FLAG is deterministic + canned, checked before everything | Health safety must not depend on LLM behavior; becomes the surgeon agent's entry point in Phase B |
| D6 | 2026-07-12 | Surgeon agent deferred to Phase B | Sketch: "won't be much input from the ortho"; keep Phase A shippable |
| D7 | 2026-07-12 | Branch protection kept minimal: no force-push/deletion, but no required PR review | Small team wants to move fast without review bottlenecks; force-push/deletion protection still guards against accidental history loss |

---

## 11. Phase B preview — adding the Orthopedic Surgeon agent

Designed-in extension points; when Phase B starts, promote this section to a full phase plan:

1. `data/surgeon/` corpus + `src/agents/orthopedic_surgeon.py` (subclass `base.py` — the
   pattern is already there; scope: post-op protocols, surgical-recovery timelines,
   when-to-call-your-surgeon guidance).
2. `router.py`: add `SURGEON` label + cues (post-op, incision, hardware, weeks-since-surgery
   phrasing); the LLM-classifier prompt gains one category line.
3. `orchestrator.py`: `consult_surgeon` node; RED_FLAG route can then hand off to the
   surgeon agent for context before its urgent-care advice; TEAM ordering becomes
   Surgeon → PT → Trainer (most-restrictive first — D4's principle generalizes).
4. Battery: add surgeon rows (post-op timeline questions, red-flag-vs-normal-healing).

Everything else — state fields, synthesis attribution, UI badges — already supports N agents.
