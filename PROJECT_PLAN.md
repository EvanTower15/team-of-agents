# Recovery Team — Implementation Plan (Phase A: PT + Gym Trainer agents)

> **Living working document.** This file is the single source of truth for project state.
> It IS committed to the repo (unlike a scratch plan) because the whole team — humans and
> AI coding agents — works from it on GitHub. Read [§0 How to use this document](#0-how-to-use-this-document)
> before making changes anywhere in the repo.
>
> **Status: PHASE 4c COMPLETE (2026-07-14) — router redesigned to be LLM-primary; Orthopedic
> Surgeon agent (Phase B, §11) pulled forward in 4b; TEAM is a three-way Surgeon→PT→Trainer
> chain with structured constraint handoff. Next up: Phase 5 (Streamlit app, owner TBD —
> suggest Ben), then Phase 6 (eval + demo assets). Open leftover: each teammate needs their
> own free Groq key at console.groq.com in their local `.env` — **this is now a harder
> blocker than before**, since routing itself needs Groq (see Phase 4c results).**
>
> *(As each phase completes, append a dated "Phase N results" block directly below this
> line, newest first. Keep every result block forever — they are the project memory.)*
>
> **Phase 4c results (2026-07-14)** — Ben, same day as 4b, in response to feedback that the
> hand-tuned regex cue lists were brittle (a real bug surfaced mid-review: "when do my
> stitches come out" didn't match the "stitches out" pattern) and getting harder to maintain
> as the specialist roster grew. **`router.py` is now LLM-primary (D11), superseding 4b's
> 3-way weighted-regex scorer entirely** — `_PT_CUES`/`_TRAINER_CUES`/`_SURGEON_CUES`/
> `_VAGUE_CUES`/`_score_rules`/`_decide_from_scores`/`RULES_CONFIDENCE_THRESHOLD` are all
> deleted, not just deprecated. RED_FLAG is the **only** regex left (D5 still holds: safety
> can't depend on LLM behavior) — every other question now goes straight to one Groq call
> that returns both the route label AND which specialist(s) apply (parsed into the same
> `RouteDecision.scores` shape `{"pt","trainer","surgeon"}` the orchestrator already reads,
> so **no changes were needed in `orchestrator.py`** — the TEAM conditional-chain logic from
> 4b is untouched). Low-confidence or unavailable-LLM responses still collapse to CLARIFY,
> never crash (`classify()` degrades the same way `consult()` always has).
> **Trade-off, explicit:** routing is no longer free — every non-RED_FLAG question now costs
> a Groq call, and (verified live) **the router returns CLARIFY for everything if
> `GROQ_API_KEY` isn't set**, since there's no regex fallback left to resolve PT/TRAINER/
> SURGEON/TEAM. This makes each teammate's Groq key a harder blocker than it was in Phase 4.
> **Verified without a Groq key available in this environment** (none configured yet for
> Ben or James): `_parse_llm_response` unit-tested directly against 8 synthetic
> `LABEL | confidence | specialists | reason` strings (including malformed ones) — all
> parsed to the right label/scores, including the "TEAM but <2 specialists named" repair
> path; `classify()` confirmed to return RED_FLAG correctly (still regex, unaffected) and to
> degrade to CLARIFY (not crash) on both an empty question and a missing API key;
> `python -m src.ingest --agent surgeon --fresh` ingests the real 18-doc corpus into 121
> chunks cleanly; the three-way orchestrator chain topology was verified structurally by
> monkeypatching `classify()` to return canned TEAM/SURGEON decisions with different
> `scores` combinations and confirming `execution_trace` shows `consult_surgeon →
> consult_pt → consult_trainer` firing in the right order and only for specialists whose
> score was 1 (e.g. `{pt:1,trainer:1,surgeon:0}` skips `consult_surgeon` entirely). **Not
> verified — needs a real Groq key**: actual LLM routing accuracy against the §9 battery,
> and the full three-way chain producing real grounded answers end-to-end. Whoever adds
> their key first should re-run the battery for real and paste results into a follow-up
> phase-results block.
>
> **Phase 4b results (2026-07-14)** — Ben, extending his Phase 4 ownership. Two additions
> to the agent-to-agent framework: (1) **structured constraint extraction**
> (`src/agents/constraints.py`, `extract_constraints()`/`format_constraints_block()`) — an
> LLM call pulls `{body_part, restriction, duration}` out of a specialist's draft instead of
> making the downstream specialist parse restrictions out of prose; never raises, degrades
> to `[]` (D8). (2) **Orthopedic Surgeon agent** (Phase B, §11, pulled forward): corpus of
> 18 docs in `data/surgeon/` (14 MedlinePlus encyclopedia/patient-instructions pages, NIAMS
> hip-replacement page, 3 NHS recovery pages), `src/agents/orthopedic_surgeon.py`, and (at
> the time this block was written) a `SURGEON` route label with its own weighted regex cue
> set generalized from the existing `(pt, trainer)` dominance scorer to a `(pt, trainer,
> surgeon)` triple (D9). **This regex cue-scoring approach was superseded same-day by Phase
> 4c** (see above) — kept here for the historical record per this doc's own rule of never
> deleting result blocks. **TEAM is a conditional chain**: `route_scores` (from the router)
> tells the graph which of surgeon/PT/trainer actually apply, and only those are consulted,
> in most-restrictive-first order (Surgeon → PT → Trainer, generalizing D4) — a plain
> PT+trainer TEAM question never touches the surgeon agent. This chaining logic in
> `orchestrator.py` did NOT change in Phase 4c — only how `route_scores` gets computed did.
> Each downstream specialist gets the upstream drafts *and* their structured constraints as
> `peer_context`. Synthesis now attributes the surgeon and defers to it on
> post-op/hardware/weight-bearing conflicts, PT on everything else (D10). `answer_question()`
> gained one additive field, `constraints: dict[agent -> list]` — no existing field changed,
> so Phase 5 is unaffected. RED_FLAG deliberately NOT wired to the surgeon this pass (§11's
> other idea) — stays deterministic/no-LLM per D5; that's a separate decision, not bundled in
> silently. Two candidate corpus URLs (CDC SSI page, one NIAMS overview page) 403'd the
> fetcher and were dropped, same as prior phases' dead-URL gotchas — coverage held up fine
> without them. Verified at the time: `python -m src.ingest --agent surgeon --fresh` ingests
> clean (121 chunks); standalone surgeon CLI plumbing sound. **Correction, added during
> Phase 4c:** this block originally claimed "existing §9 battery re-run at parity, still
> 12/12" — that was not actually run against live data (no Groq key was available in the
> dev environment) and should not have been stated as verified; see Phase 4c's results for
> what was and wasn't actually confirmed.
>
> **Phase 4 results (2026-07-12)** — `src/router.py` + `src/orchestrator.py` live (run by
> Evan+Claude; phase was Ben's — he should review the merged PR to own it going forward).
> Routing battery **12/12 (100%)**, all via rules, ZERO LLM router calls:
> | # | expected | got | conf | method |
> |---|---|---|---|---|
> | 1 | PT_ONLY | PT_ONLY | 0.82 | rules |
> | 2 | TRAINER_ONLY | TRAINER_ONLY | 0.95 | rules |
> | 3 | TEAM | TEAM | 0.90 | rules |
> | 4 | RED_FLAG | RED_FLAG | 0.97 | rules |
> | 5 | CLARIFY | CLARIFY | 0.70 | rules |
> | 6 | TEAM (or PT_ONLY) | TEAM | 0.90 | rules |
> | 7 | TRAINER_ONLY (or TEAM) | TRAINER_ONLY | 0.95 | rules |
> | 8 | TRAINER_ONLY | TRAINER_ONLY | 0.95 | rules |
> | 9 | PT_ONLY | PT_ONLY | 0.95 | rules |
> | 10 | RED_FLAG | RED_FLAG | 0.97 | rules |
> | 11 | CLARIFY | CLARIFY | 0.70 | rules |
> | 12 | TEAM | TEAM | 0.90 | rules |
>
> E2E verified: TEAM run consulted PT then trainer **with the PT draft as peer_context**
> (trace proves it), synthesized answer attributes both specialists and keeps both source
> sets; RED_FLAG produced exactly 2 trace lines (route + canned safety response — no agent,
> no LLM, per D5); CLARIFY returns one focused follow-up; PT_ONLY flows through synthesis
> for consistent voice + disclaimer. **Kill-chroma test passed**: with `chroma_db/` renamed
> away, the graph returned the fallback answer with rebuild instructions — no stack trace.
> Implementation notes for Phase 5: import ONLY `answer_question()` from
> `src.orchestrator`; it returns the §5.4 dict verbatim. The disclaimer/red-flag/fallback
> texts are code constants in orchestrator.py (§7.2/§7.3). Router vague-cue guard: subjective
> words only force CLARIFY when total cue weight <= 2, so "best exercises for a sprained
> knee" still routes. CLI: `python -m src.orchestrator "question"` (stdout reconfigured to
> UTF-8 — LLM output may be non-ASCII; the ASCII-only rule applies to our own prints).
>
> **Phase 3 results (2026-07-12)** — Trainer agent live (run by Evan+Claude; owner slot was
> TBD). Corpus: **22 docs in `data/trainer/`** (19 txt + 3 PDF), anchored by the 118-page
> HHS Physical Activity Guidelines 2nd ed.; CDC physical-activity-basics, NIA, MedlinePlus,
> 8 NHS practical exercise pages (OGL), Move Your Way older-adults fact sheet. Three files
> deliberately duplicated from `data/pt/` (collections are siloed per D3 and the
> elderly-onboarding docs belong in both). Ingest: **536 chunks**. US Army FM 7-22 dropped —
> armypubs.army.mil blocks scripted downloads (returns HTML, not the PDF); fetch manually
> if ever wanted. Battery 5/5 grounded + cited: concrete 3-day program (days/sets/reps),
> age-70 conservative on-ramp, progressive-overload guidance, the exact 150/75-minute PAG
> aerobic guideline, and protein question → honest "no material on nutrition" (§9 #8's
> expected behavior). **peer_context test PASSED**: given a fake PT draft (no loaded knee
> flexion past 90°, no impact for 4 weeks), the trainer opened by restating the restrictions
> and programmed around them — cycling warm-up, hip thrusts, seated calf raises,
> reduced-flexion machine positioning, zero impact. Pain trap ("knee swelled after squats")
> → "That's the physical therapist's call" deferral. Phase 4 note: both agents construct
> with zero args (`PhysicalTherapistAgent()`, `GymTrainerAgent()`) — import and call
> `consult()` directly in the graph nodes.
>
> **Phase 2 results (2026-07-12)** — PT agent live. Corpus: **29 docs in `data/pt/`**
> (25 txt + 4 PDF — three CDC STEADI brochures + the 34-page NIA "Exercise and Physical
> Activity for Older Adults" guide), all public-domain except 4 NHS pages under OGL;
> provenance in `data/SOURCES.md`. Ingest: **203 chunks**; PDF page-level loading verified
> (NIA guide → 34 Documents). `PhysicalTherapistAgent` uses `k=6` (larger corpus). Battery:
> 5 in-scope questions answered grounded + persona-consistent + source-cited (stage-aware
> PRICE-then-progress answers; the age-70 question cited NIA PDF **page numbers**);
> "best protein powder?" → honest not-my-area deferral to a dietitian. Fetch gotchas for
> Phase 3's corpus run (fetch script pattern in Evan's scratchpad, not committed — corpus
> files are committed pre-curated per §2): (1) NIAMS redirected sprains/tendinitis/bursitis
> URLs to ONE consolidated sports-injuries page — dedupe before committing; (2) NINDS
> back-pain URL now redirects to their general "Pain" page (kept as `ninds_pain.txt`);
> (3) MedlinePlus: extract only the `#topic-summary` div, the rest is link nav; (4) NIA
> PDF's current URL is `order.nia.nih.gov/sites/default/files/2025-04/…` (2018 URL 404s);
> (5) every corpus txt carries a title/source/license/date header — keep that convention.
>
> **Phase 1 results (2026-07-12)** — `src/rag_core.py`, `src/ingest.py`, `src/agents/base.py`
> landed (run by Evan+Claude; James picks up at Phase 2). Facts the next phases need:
> (1) `CHROMA_PERSIST_DIR` is anchored to the **repo root** (absolute path), not the process
> cwd — §5.1 contract updated to match, so Streamlit/CLI agree on one store location.
> (2) The §7.1 grounding rule is baked into `base.py`'s prompt template — personas do NOT
> need to repeat it; concrete agents only set `name` / `display_name` / `collection_name` /
> `persona_prompt` and call `run_cli()` for their `__main__` (§5.2 note added).
> (3) **Console prints must stay ASCII-only** — Windows cp1252 terminals crash on `→`/`§`
> (hit this twice; use `->` and `section`). (4) First embedding run downloads MiniLM (~90 MB)
> to the HF cache; the HF symlink warning on Windows is harmless. (5) Verified on Python
> 3.13.5 + torch 2.13.0+cpu. Done-when evidence: fictional ZQX-7 protocol doc → ingest
> (2 chunks) → grounded answer citing `[source: _smoke_test.txt]` with correct `sources`
> list; out-of-corpus question ("swimming?") got an honest "I don't have material on that";
> unbuilt collection returned `error` field (no raise) with a fix-it message; missing
> GROQ_API_KEY raises EnvironmentError naming `.env.example`. Smoke fixtures + `chroma_db/`
> deleted after verification — Phase 2 starts from a clean store.
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
   > ⚠️ **Prerequisite for Ben & James (or any agent working on their behalf):** you need
   > your own free Groq API key before any agent code will actually run — the router, all
   > three specialist agents, and synthesis all call Groq's `llama-3.3-70b-versatile`. Sign up
   > at https://console.groq.com, create a key, copy `.env.example` → `.env`, and paste it in
   > as `GROQ_API_KEY=`. `.env` is gitignored — never commit it. **As of Phase 4c this is a
   > harder blocker than before:** the router itself is now LLM-primary, so without a key
   > `classify()` returns CLARIFY for every question (verified) — there's no regex fallback
   > left except RED_FLAG. Delete this notice once both of you have confirmed your keys work
   > (e.g. a phase-results block says so).
2. **While working:** follow the interface contracts in [§5](#5-module-contracts--work-in-parallel-safely)
   exactly. They exist so phases can proceed in parallel without merge pain. If you must
   change a contract, update this file in the same PR and flag it in the PR description.
3. **When you finish a phase:**
   - Tick the checkboxes in your phase's task list ([§8](#8-phase-plan)).
   - If your phase changed **how** something works (not just added to it), update the
     matching section of [Capabilities_Overview.md](Capabilities_Overview.md) — that document
     is the team's deep-dive explainer and the presentation's source of truth.
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
| Hybrid router | `src/router.py`: weighted regex cue scorer → confidence; below threshold, fall back to a Groq LLM classifier; below that, CLARIFY. Returns a `RouteDecision` dataclass (label, confidence, reasoning, method, scores) | Diverged in Phase 4c: RED_FLAG is still regex, but everything else is LLM-primary now, not hybrid ([§6.2](#62-router), D11) |
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
│   ├── surgeon/                # Surgeon corpus (Phase 4b, pulled forward from Phase B)
│   └── SOURCES.md             # per-file provenance + license note (Phases 2–3, 4b)
├── src/
│   ├── __init__.py
│   ├── rag_core.py            # shared load/chunk/embed/retrieve, per-collection (Phase 1)
│   ├── ingest.py              # CLI: python -m src.ingest --agent pt|trainer|surgeon (Phase 1, 4b)
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py            # SpecialistAgent base class (Phase 1)
│   │   ├── physical_therapist.py   # persona + collection binding (Phase 2)
│   │   ├── gym_trainer.py          # persona + collection binding (Phase 3)
│   │   ├── orthopedic_surgeon.py   # persona + collection binding (Phase 4b)
│   │   └── constraints.py          # structured constraint extraction (Phase 4b)
│   ├── router.py              # hybrid rules→LLM route classifier (Phase 4, 4b)
│   └── orchestrator.py        # LangGraph team workflow (Phase 4, 4b)
└── chroma_db/                 # generated, gitignored
```

---

## 5. Module contracts — work in parallel safely

These signatures are **frozen** once Phase 0 merges. Build to them; stub what you depend on.

### 5.1 `src/rag_core.py` (Phase 1)

```python
CHROMA_PERSIST_DIR = str(<repo_root> / "chroma_db")   # anchored to repo root, cwd-independent

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
its persona and collection, and adds a `__main__` CLI so it is testable standalone
(`base.py` ships a `run_cli(agent, default_question)` helper — the `__main__` block is two
lines; the §7.1 grounding rule is already baked into the base prompt, don't repeat it):

```
python -m src.agents.physical_therapist "My knee aches after squats — normal?"
```

### 5.3 `src/router.py` (Phase 4, extended 4b, redesigned 4c) — route labels

```python
PT_ONLY = "PT_ONLY"; TRAINER_ONLY = "TRAINER_ONLY"; SURGEON = "SURGEON"
TEAM = "TEAM"; CLARIFY = "CLARIFY"; RED_FLAG = "RED_FLAG"

def classify(question: str) -> RouteDecision:
    """RouteDecision(label, confidence: float, reasoning: str,
    method: 'rules'|'llm', scores: dict). scores is {"pt", "trainer", "surgeon"}
    (0/1 per specialist since Phase 4c). RED_FLAG is regex, checked first,
    always wins (D5) -- everything else goes straight to the Groq classifier
    (D11); confidence < 0.50 collapses to CLARIFY. method is 'rules' only for
    RED_FLAG/empty-question/LLM-unavailable; 'llm' otherwise."""
```

### 5.4 `src/orchestrator.py` (Phase 4, extended Phase 4b)

```python
def answer_question(question: str) -> dict:
    """Runs the LangGraph. Returns: {
      "final_answer": str,
      "route": str, "route_confidence": float,
      "agents_consulted": list[str],
      "sources": dict[str, list[str]],   # agent name -> source files
      "constraints": dict[str, list[dict]],  # Phase 4b, additive: agent -> extract_constraints() output
      "execution_trace": list[str],
    }"""
```

`app.py` calls **only** `answer_question()`. Nothing in the UI touches agents directly.

---

## 6. Orchestration design

### 6.1 Flow

```
START → route_question ─┬─ PT_ONLY      → consult_pt ─────────────────────────────────────┐
                        ├─ TRAINER_ONLY → consult_trainer ─────────────────────────────────┤
                        ├─ SURGEON      → consult_surgeon ──────────────────────────────────┤
                        ├─ TEAM  → [consult_surgeon] → [consult_pt] → [consult_trainer] ────┤
                        ├─ RED_FLAG     → safety_response → END                             │
                        └─ CLARIFY      → ask_clarification → END                           ▼
                                                            synthesize_team_answer → END
                 (agent error / zero passages retrieved) → fallback_handler → END
```

- **The TEAM route is the agent-to-agent framework from the sketch, generalized to three
  agents in Phase 4b.** Specialists chain most-restrictive-first — Surgeon, then PT, then
  Trainer (D4, D9) — but only the specialists whose cues actually fired (per
  `RouteDecision.scores`) are consulted: a plain PT+trainer TEAM question skips the surgeon
  entirely. Each downstream specialist receives the upstream drafts as `peer_context`,
  prefixed with their *structured* constraints (Phase 4b, `src/agents/constraints.py`, D8)
  so restrictions don't depend on an LLM parsing prose correctly (e.g. "PT says no loaded
  knee flexion past 90° — so we substitute box squats"). This ordering is a deliberate
  safety property: document it in the report.
- The graph is a DAG — no cycles, cannot loop.
- Empty retrieval **with no error** still flows to synthesis (which honestly says the team
  doesn't have material on that); only hard errors hit `fallback_handler`. (opim-5517
  convention, proven out in its HW6.)

### 6.2 Router

**Redesigned in Phase 4c (D11) to be LLM-primary.** Phase 4/4b used opim-5517's hybrid
strategy (weighted regex cues → confidence score → Groq LLM only when rules were unsure).
That regex layer proved brittle as the specialist roster grew — e.g. a cue meant to catch
"stitches out" missed the equally natural "stitches come out" — and needed constant patching
per phrasing. Phase 4c deleted the weighted cue lists and the dominance-scoring math
entirely; the **only** regex left is RED_FLAG (checked first, always wins — D5 still holds,
a safety gate can't depend on LLM behavior). Every other question goes straight to one Groq
call that returns both the route label and which specialist(s) apply, parsed into the same
`RouteDecision.scores` shape (`{"pt", "trainer", "surgeon"}`, now 0/1 rather than a weighted
count) that the orchestrator's TEAM conditional-chain logic already consumed — so
`orchestrator.py` needed zero changes for this redesign.

**Trade-off, explicit:** routing is no longer free. Every non-RED_FLAG question now costs a
Groq call instead of resolving instantly via keyword weights, and if `GROQ_API_KEY` isn't
set there is no rules fallback left — `classify()` degrades straight to CLARIFY (verified
live in Phase 4c). Each teammate's own Groq key (§0) is now a harder blocker than before.

- **RED_FLAG (checked FIRST, before the LLM — always wins):** severe/sharp/unbearable pain,
  numbness/tingling, can't bear weight, visible deformity, fever + joint, calf swelling,
  chest pain, surgical wound/incision issues. → canned safety response ([§7](#7-safety--scope-guardrails)), no LLM.
- **Everything else (PT_ONLY / TRAINER_ONLY / SURGEON / TEAM / CLARIFY):** decided by the LLM
  classifier in one call, which also names which specialist(s) apply — see the prompt in
  `router.py` for the exact category definitions given to the model.

### 6.3 LangGraph workflow

`TypedDict` state, all fields optional, mirroring opim-5517's `AgentState`:

```python
class TeamState(TypedDict, total=False):
    question: str
    route: str; route_confidence: float; route_reasoning: str; route_method: str
    route_scores: dict        # {"pt", "trainer", "surgeon"} -> 0|1 (Phase 4b, values 4c)
    surgeon_result: dict      # SpecialistAgent.consult() output (Phase 4b)
    pt_result: dict
    trainer_result: dict
    surgeon_constraints: list; pt_constraints: list  # extract_constraints() output (Phase 4b)
    final_answer: str
    sources: dict            # agent -> [filenames]
    needs_clarification: bool; clarification_question: str
    fallback_reason: str
    execution_trace: Annotated[list, operator.add]   # one line per node
```

**Synthesis node** ("care coordinator") prompt requirements: merge the specialist drafts
into one answer that (a) uses ONLY the drafts as evidence, (b) attributes advice —
"Your surgeon advises… Your physical therapist advises… Your trainer suggests…",
(c) surfaces conflicts instead of averaging them — surgeon wins on post-op/hardware/
weight-bearing precautions, PT wins on everything else involving pain/safety/rehab
restrictions (Phase 4b two-tier priority, generalizing D4's PT-wins rule), (d) ends with
the standing disclaimer ([§7](#7-safety--scope-guardrails)). Single-agent routes still pass
through synthesis for consistent voice + disclaimer.

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
   contact your surgeon/doctor or urgent care. Phase 4b added the surgeon agent but
   deliberately did NOT wire RED_FLAG to consult it (§11's other idea) — it stays
   deterministic/no-LLM per D5; blending in a surgeon lookup there is a separate decision
   for later, not bundled in silently.
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
~~⚠️ The Gym Trainer agent (Phase 3) has no owner in the sketch~~ — resolved: Evan ran
Phase 3 (2026-07-12). **Phase 5 (Streamlit app) still needs an owner** — suggest Ben,
who owns the `answer_question()` API it calls.

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

- [x] `src/rag_core.py` per contract §5.1 (port opim-5517 `retrieval.py` flow: loaders for
      pdf/txt/md → `RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150,
      add_start_index=True)` → `HuggingFaceEmbeddings("sentence-transformers/all-MiniLM-L6-v2")`
      → `Chroma(persist_directory, collection_name)`)
- [x] `src/ingest.py` CLI: `python -m src.ingest --agent pt` ingests `data/pt/` →
      collection `pt_docs` (and `--agent trainer` → `trainer_docs`); `--fresh` flag clears first
- [x] `src/agents/base.py` per contract §5.2 (retrieve → persona prompt → `get_llm()` →
      answer; never raises; `peer_context` injected into the prompt when present)
- **Done when:** a throwaway txt file in `data/pt/` can be ingested and a base-class agent
  answers a question about it with correct source attribution, and a deliberately broken
  case (no collection built) returns `error` instead of raising.

### Phase 2 — Physical Therapist agent — **James**

- [x] Corpus into `data/pt/` (~10–30 documents is plenty). Suggested public-domain-first
      sources: MedlinePlus rehab/injury pages (public domain), NIH/NIA "Exercise & Physical
      Activity" guides, CDC injury-basics pages; NHS rehab leaflets are OGL-licensed
      (reuse with attribution) — log everything in `data/SOURCES.md`
- [x] `src/agents/physical_therapist.py`: persona = licensed-DPT voice; scope = rehab
      progression, pain vs. soreness, ROM/mobility, when to regress an exercise; explicitly
      instructed to defer diagnosis to clinicians; grounding rule verbatim (§7.1)
- [x] CLI smoke test (§5.2) on ≥ 5 questions from the §9 battery; paste transcript
      highlights into the phase-results block
- **Done when:** PT battery questions get grounded, persona-consistent, source-cited
  answers, and an out-of-scope question ("best protein powder?") gets an honest
  "not my area" rather than an improvised answer.

### Phase 3 — Gym Trainer agent — **OWNER TBD** *(can run parallel with Phase 2)*

- [x] Corpus into `data/trainer/`. Suggested: **HHS Physical Activity Guidelines for
      Americans, 2nd ed.** (public domain, excellent), CDC physical-activity pages, NIA
      exercise guides for older adults (nails the "elderly getting active" persona from the
      sketch), ~~US Army FM 7-22~~ (dropped — armypubs blocks scripted downloads)
- [x] `src/agents/gym_trainer.py`: persona = certified-trainer voice; scope = programming,
      progressive overload, form cues, beginner/elderly modifications; explicitly defers
      pain/injury questions to the PT; grounding rule verbatim
- [x] CLI smoke test on ≥ 5 battery questions, incl. one with `peer_context` set to a fake
      PT draft with a restriction — verify the trainer's answer respects it
- **Done when:** same bar as Phase 2, plus the `peer_context`-respect test passes.

### Phase 4 — Router + orchestrator — **Ben** *(contracts allow starting right after Phase 0 with stub agents)*

- [x] `src/router.py` per §5.3/§6.2: RED_FLAG regex check first; weighted cue scorer;
      Groq LLM fallback (port opim-5517's robust `LABEL | confidence | reason` parser —
      it tolerates messy LLM output); thresholds 0.62 rules / 0.50 clarify as starting values
- [x] `src/orchestrator.py` per §5.4/§6.3: LangGraph nodes `route_question`, `consult_pt`,
      `consult_trainer`, `synthesize_team_answer`, `safety_response`, `ask_clarification`,
      `fallback_handler`; conditional edges per §6.1; TEAM route passes PT draft as trainer's
      `peer_context`; disclaimer constant appended in code
- [x] `__main__` CLI: `python -m src.orchestrator "question"` prints route, trace, answer
- [x] Run the FULL §9 battery; record route + confidence + method for every question in
      the phase-results block; tune cue weights until routing table is ≥ 90% correct
- **Done when:** battery routing ≥ 90%, TEAM questions produce answers citing both agents,
  a RED_FLAG question never reaches an LLM, and killing the Chroma dir produces a graceful
  fallback answer, not a stack trace.

### Phase 4b — Structured constraints + Orthopedic Surgeon agent — **Ben** *(Phase B, §11, pulled forward)*

- [x] `src/agents/constraints.py`: `extract_constraints()` (LLM pulls
      `{body_part, restriction, duration}` out of a specialist draft) + `format_constraints_block()`;
      never raises, degrades to `[]`; no change to `SpecialistAgent.consult()`'s frozen §5.2 signature
- [x] Corpus into `data/surgeon/` (18 docs: MedlinePlus post-op/wound-care/discharge pages,
      NIAMS hip-replacement, NHS recovery pages) logged in `data/SOURCES.md`
- [x] `src/agents/orthopedic_surgeon.py`: persona = post-op protocols, recovery timelines,
      hardware/wound precautions; defers to the patient's own surgeon's individual orders;
      states its restrictions are binding on PT/trainer plans
- [x] `src/ingest.py`: `--agent surgeon` → `surgeon_docs`
- [x] `src/router.py`: `SURGEON` label + weighted cue set; 3-way dominance scoring
      (generalized from `(pt, trainer)` to `(pt, trainer, surgeon)`) — **superseded same-day
      by Phase 4c's LLM-primary redesign; see below**
- [x] `src/orchestrator.py`: `consult_surgeon` node; TEAM route chains whichever of
      surgeon/PT/trainer actually scored, most-restrictive-first, each hop receiving upstream
      constraints + drafts as `peer_context`; synthesis attributes and prioritizes accordingly
- [ ] ~~Re-run the FULL §9 battery (parity check) plus new surgeon/three-way rows~~ — not
      actually run against live data (no Groq key in the dev environment); left unchecked
      honestly rather than claimed done. Blocked on a real key (§0); see Phase 4c note.
- **Done when:** a post-op-only question routes SURGEON and answers grounded+cited; a
  three-cue TEAM question chains `consult_surgeon → consult_pt → consult_trainer` in order
  with constraints visible in the trace; killing `surgeon_docs` before it's built degrades to
  `fallback_handler`, not a stack trace. (Structural chain topology verified via monkeypatch
  in Phase 4c; battery routing accuracy still needs a live Groq key.)

### Phase 4c — Router redesign: LLM-primary classification — **Ben** *(same-day follow-up to 4b)*

- [x] `src/router.py` rewritten: delete the weighted regex cue lists and dominance scorer;
      RED_FLAG remains the only regex (D5); every other question goes to one Groq call that
      returns the route label AND which specialist(s) apply, parsed into the same
      `RouteDecision.scores` shape the orchestrator already reads (D11)
- [x] No changes needed in `orchestrator.py` — the TEAM conditional-chain logic already
      consumed `route_scores` generically
- [x] Unit-tested `_parse_llm_response` against synthetic responses (incl. malformed ones);
      confirmed `classify()` degrades to CLARIFY (not a crash) with no API key or empty input
- [ ] Run the FULL §9 battery for real against live Groq responses — **blocked on a Groq key**
      being configured in a dev environment; do this before Phase 5 if possible
- **Done when:** the battery has actually been run against a real Groq key and routing
  accuracy is recorded in a follow-up phase-results block (not just structural/parser tests).

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
| 13 | "How long until I can put weight on my knee after knee arthroscopy?" | SURGEON | post-op weight-bearing timeline, cited surgeon sources |
| 14 | "My surgeon cleared me for full weight-bearing 6 weeks after ACL reconstruction — how do I safely get back into leg training?" | TEAM (surgeon+PT+trainer) | surgeon's weight-bearing clearance honored by both PT and trainer plans, all three attributed |
| 15 | "When do my stitches come out?" | SURGEON | discharge/wound-care timeline, cited surgeon sources |

---

## 10. Decision log

| # | Date | Decision | Why |
|---|---|---|---|
| D1 | 2026-07-12 | Mirror opim-5517 architecture (RAG core / hybrid router / LangGraph / Streamlit), simplified | Proven in coursework; team already understands it; battle-tested error-handling conventions |
| D2 | 2026-07-12 | Local sentence-transformers embeddings instead of Gemini/OpenAI | Zero cost, zero keys, zero rate limits (Gemini free tier forced 60 s sleeps per 100 chunks in opim-5517); corpus small enough that quality difference is immaterial |
| D3 | 2026-07-12 | One Chroma dir, one collection per agent | Knowledge siloing per specialist is the core product thesis; also lets agents rebuild independently |
| D4 | 2026-07-12 | PT runs before Trainer on TEAM route; trainer receives PT draft as `peer_context` | Clinical constraints must bound the training plan, not vice versa — this IS the agent-to-agent story for the report |
| D5 | 2026-07-12 | RED_FLAG is deterministic + canned, checked before everything | Health safety must not depend on LLM behavior; becomes the surgeon agent's entry point in Phase B |
| D6 | 2026-07-12 | Surgeon agent deferred to Phase B | Sketch: "won't be much input from the ortho"; keep Phase A shippable — **superseded by D9** (pulled forward in Phase 4b once Ben was ready to extend his own phase) |
| D7 | 2026-07-12 | Branch protection kept minimal: no force-push/deletion, but no required PR review | Small team wants to move fast without review bottlenecks; force-push/deletion protection still guards against accidental history loss |
| D8 | 2026-07-14 | Structured constraint extraction (`src/agents/constraints.py`) layered on top of the existing free-text `peer_context`, not replacing it | Free-text peer_context made the downstream specialist's LLM parse restrictions out of prose and hope it caught them all; a small structured list is unambiguous and can later be surfaced to the UI — but §5.2's `consult()` signature stays frozen, so the structured block just gets prepended into the same string parameter |
| D9 | 2026-07-14 | Orthopedic Surgeon agent (Phase B, §11) pulled forward into Phase 4b, with TEAM generalized to a conditional Surgeon→PT→Trainer chain | Ben's Phase 4 ownership naturally extends to the rest of the agent-to-agent framework; the cue-scoring dominance math already generalized cleanly from 2 to 3 buckets, and gating each hop on `route_scores` avoids consulting the surgeon on questions that never mention surgery |
| D10 | 2026-07-14 | Synthesis conflict priority: surgeon wins on post-op/hardware/weight-bearing precautions, PT wins on everything else involving pain/safety/rehab | Generalizes D4's "PT wins on safety" rule now that there are two clinical voices instead of one; each has a distinct area where its restriction should override the others |
| D11 | 2026-07-14 | Router redesigned to be LLM-primary (deletes D9's weighted-regex 3-way scorer, same day); RED_FLAG remains the sole regex | The hand-tuned cue lists were brittle and needed constant patching per phrasing (a real bug: "stitches come out" missed a cue meant to catch "stitches out") and would only get worse as more specialists/phrasings are added; a classifier generalizes without new patterns. Trade-off accepted deliberately: routing is no longer free (one Groq call per non-RED_FLAG question) and now hard-depends on `GROQ_API_KEY` being set — a safety gate (RED_FLAG) is the one thing that must never depend on that, so it alone stays regex (D5 unchanged) |

---

## 11. Phase B preview — adding the Orthopedic Surgeon agent

> **Completed in Phase 4b (2026-07-14)**, ahead of the original Phase B schedule — see the
> Phase 4b results block and D9. Kept below as the historical record of the original design;
> the RED_FLAG hand-off idea in point 3 was **not** implemented (see §7 point 3 and D5) and
> remains open for a future, deliberate decision.

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
