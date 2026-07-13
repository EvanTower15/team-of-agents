# Capabilities Overview — How the Recovery Team Actually Works

> **Who this is for:** every teammate, and especially whoever builds the presentation.
> [PROJECT_PLAN.md](PROJECT_PLAN.md) tracks *what* was built, in what order, and what's next.
> This document explains *how* each part works and *why* it was designed that way, in enough
> depth that you can confidently explain (and demo) the parts you didn't personally build.
> Everything below reflects the system as of Phase 4 (2026-07-12): both specialists live and
> orchestrated end-to-end. Update this document when a phase changes how something works.

---

## 1. The product in one paragraph

A user recovering from an injury asks one chat interface a question. Behind it, a **router**
decides which specialist(s) should answer — a **Physical Therapist agent**, a **Gym Trainer
agent**, or both in sequence. Each specialist answers **only from its own curated library of
vetted documents** (this is Retrieval-Augmented Generation — RAG), and a **synthesizer**
merges their drafts into one coherent "care team" response with source citations and a
standing disclaimer. Questions that look like medical emergencies never reach an AI model at
all — they get a fixed safety response. The core thesis: one general-purpose LLM hallucinates
and can't credibly be two experts at once; two narrow agents, each grounded in its own
knowledge base and coordinated by an orchestrator, can.

```
                            ┌──────────────────────────┐
        user question ────► │   router (src/router.py) │
                            └────────────┬─────────────┘
        ┌──────────────┬─────────────────┼───────────────┬──────────────┐
        ▼              ▼                 ▼               ▼              ▼
     PT_ONLY      TRAINER_ONLY         TEAM          RED_FLAG        CLARIFY
        │              │          PT first, then        │              │
        ▼              ▼          trainer w/ PT's       ▼              ▼
   PT agent      Trainer agent    draft as context   canned safety  one focused
   (pt_docs)     (trainer_docs)   (agent-to-agent)   response       follow-up ?
        │              │                 │           (no LLM ever)     │
        └──────────────┴───────┬─────────┘               │             │
                               ▼                         │             │
                    synthesize_team_answer               │             │
                    (attributes each specialist,         │             │
                     PT wins on safety conflicts)        │             │
                               │                         │             │
                               ▼                         ▼             ▼
                        final answer + [source: ...] citations + disclaimer
```

---

## 2. A question's journey (real, observed run)

The fastest way to understand the system is to follow one question through it. This is the
actual execution trace from Phase 4 testing, not a mock-up:

**Question:** *"I'm 8 weeks post-meniscus surgery — how do I get back into lifting safely?"*

```
route_question:    TEAM (0.90, rules) - Both rehab (4) and training (2) cues present.
consult_pt:        5 source(s)
consult_trainer:   4 source(s), with PT draft as peer_context
synthesize_team_answer: merged 2 draft(s)
```

What happened at each step:

1. **Routing.** The router's keyword scorer found rehab cues ("post-…surgery" and "meniscus",
   weight 2 each = 4) and training cues ("lifting", weight 2). Both specialists signalled and
   neither dominated, so the route is **TEAM** with confidence 0.90 — decided by
   deterministic rules in microseconds, no LLM call.
2. **PT consults first.** The PT agent embedded the question, pulled its 6 most relevant
   passages from the `pt_docs` collection (they came from 5 distinct documents), and wrote a
   draft in its licensed-DPT persona — grounded ONLY in those passages.
3. **Trainer consults second, constrained.** The trainer agent got the same question PLUS the
   PT's entire draft as `peer_context`, which its prompt treats as **binding restrictions**.
   It retrieved from its own `trainer_docs` collection and programmed around the PT's
   constraints.
4. **Synthesis.** A "care coordinator" LLM call merged the two drafts into one answer that
   attributes advice to each specialist ("Your physical therapist advises… Your trainer
   suggests…"), keeps every `[source: filename]` citation, and would surface any conflict
   with the PT winning on safety. The fixed disclaimer is appended **by code**, not by the
   model.

The PT-before-trainer ordering is deliberate and is the "agent-to-agent framework" from our
product sketch: clinical constraints bound the training plan, never the reverse. In the
observed run, the trainer visibly obeyed — it proposed chair-based, low-load exercises
consistent with the PT's post-op caution.

---

## 3. Layer 1 — The knowledge bases (`data/`)

Each specialist has its own corpus folder and its own vector-database collection. They are
**deliberately siloed** (decision D3 in the plan): the PT physically cannot retrieve trainer
documents and vice versa. The silo is the anti-"jack of all trades" mechanism — each agent's
expertise boundary is enforced by what it can see, not by prompt promises.

| | Physical Therapist | Gym Trainer |
|---|---|---|
| Folder → collection | `data/pt/` → `pt_docs` | `data/trainer/` → `trainer_docs` |
| Size | 29 documents (25 txt + 4 PDF), 203 chunks | 22 documents (19 txt + 3 PDF), 536 chunks |
| Anchor documents | NIA "Exercise & Physical Activity for Older Adults" guide (34-page PDF), 3 CDC STEADI fall-prevention brochures | HHS "Physical Activity Guidelines for Americans, 2nd ed." (118-page PDF) |
| Text sources | MedlinePlus injury topics, NIAMS fact sheets, NINDS pain page, NHS rehab pages | CDC physical-activity-basics, NIA get-started guides, MedlinePlus, 8 practical NHS exercise pages (strength/balance/flexibility/sitting/Couch-to-5K) |

Sourcing rules (§7.5 of the plan): US-government content is public domain; NHS pages are
under the Open Government Licence v3.0 (reuse with attribution). Every file's URL, license,
and fetch date is logged in [data/SOURCES.md](data/SOURCES.md), and every text file carries a
title/source/license/date header — which also gives the LLM provenance context when a chunk
is retrieved. Three elderly-onboarding documents appear in BOTH corpora on purpose: the
collections are siloed, so content both specialists need must exist in both.

**Why the corpora are "pre-curated" files in git** rather than live-scraped at runtime:
reproducibility (everyone ingests identical bytes), licensing review happens once at commit
time, and teammates without network quirks can rebuild identically.

---

## 4. Layer 2 — The RAG core (`src/rag_core.py`)

This module is the shared plumbing both agents use. It does two jobs: **ingestion** (build a
knowledge base) and **retrieval** (fetch relevant passages at question time).

### Ingestion: `python -m src.ingest --agent pt|trainer [--fresh]`

1. **Load.** Every `.pdf`, `.txt`, and `.md` in the agent's folder is read. PDFs load
   page-by-page (the 34-page NIA guide becomes 34 documents), so citations can carry page
   numbers. Text files load whole.
2. **Chunk.** Documents are split into ~1,000-character pieces with 150 characters of
   overlap (`RecursiveCharacterTextSplitter`). Why chunk: the LLM answers from a handful of
   *passages*, not whole books — retrieval needs pieces small enough to be specific but big
   enough to carry a complete thought. Why overlap: so a sentence straddling a boundary
   survives intact in at least one chunk.
3. **Embed.** Each chunk is converted to a 384-dimensional vector by a local
   sentence-transformers model (`all-MiniLM-L6-v2`, ~90 MB, runs on CPU). An embedding is a
   numeric fingerprint of *meaning*: chunks about "knee swelling after exercise" land near
   each other in vector space even if they share no exact words. Running it locally
   (decision D2) means zero API cost, zero rate limits, and ingestion that works offline —
   the reference course project used a cloud embeddings API and had to sleep 60 seconds per
   batch to dodge rate limits.
4. **Store.** Vectors + chunk text + metadata persist in **ChromaDB**, an embedded database
   that lives in `chroma_db/` at the repo root (gitignored — everyone builds their own from
   the committed corpus). One named collection per agent.

### Retrieval: `retrieve(question, collection_name, k)`

At question time the question itself is embedded with the same model, and Chroma returns the
`k` nearest chunks (both agents use `k=6`). Those chunks — each tagged with its source
filename — become the only material the agent may answer from. If a collection has never
been built, `retrieve` raises a `FileNotFoundError` whose message contains the exact fix-it
command; the agent layer converts that into a polite error instead of a crash.

**Honest limitation to know for Q&A:** this is naive top-k similarity search — no keyword
(BM25) hybrid, no reranking, no metadata filtering. Fine at our corpus size; listed as
future work.

---

## 5. Layer 3 — The specialist agents (`src/agents/`)

### The base class (`base.py`)

`SpecialistAgent` is ~100 lines and both specialists are tiny subclasses of it. A concrete
agent defines only four things: `name`, `display_name`, `collection_name`, and a
`persona_prompt`. Everything mechanical lives in the base:

```
consult(question, peer_context=None) ->
    {"agent": ..., "answer": ..., "sources": [filenames], "error": None-or-str}
```

The `consult()` lifecycle: retrieve top-k chunks from the agent's own collection → build a
context block where every passage is labeled `[source: filename]` → fill the prompt template
(persona + grounding rule + optional peer block + context + question) → one Groq LLM call
(`llama-3.3-70b-versatile`, temperature 0.2) → return the draft plus the de-duplicated list
of source files.

Three design properties matter more than the plumbing:

1. **The grounding rule is structural.** The instruction *"Use ONLY the provided context…
   do not improvise an answer from general knowledge"* is baked into the base class's prompt
   template. A subclass persona cannot forget it — every consult carries it. This is the
   single most important anti-hallucination mechanism in the product. Verified behavior:
   asked about swimming (absent from the corpus), the PT answered "I don't have material on
   swimming in my knowledge base" instead of inventing a protocol.
2. **`consult()` never raises.** All failures — missing knowledge base, network error, LLM
   outage — land in the returned `error` field. This is what lets the orchestrator graph
   treat a broken agent as a routing condition instead of a crash.
3. **`peer_context` is the agent-to-agent channel.** When present, the base injects the
   teammate's draft with the framing *"Treat any restrictions or safety constraints in their
   draft as binding — build on them, never contradict them."* The orchestrator uses this on
   the TEAM route (PT draft → trainer).

### The two personas

- **`physical_therapist.py`** — licensed-DPT voice. Scope: rehab progressions, normal
  soreness vs. warning-sign pain, range-of-motion/mobility work, when to regress an
  exercise. Hard rules: never diagnose (explain what the context says, refer to a
  clinician); refuse out-of-scope topics plainly (tested: "best protein powder?" → honest
  not-my-area + dietitian referral); make advice stage-aware ("in the first 72 hours…" vs
  "once swelling has settled…").
- **`gym_trainer.py`** — certified-trainer voice. Scope: programming (days/sets/reps),
  progressive overload, form cues, beginner and older-adult modifications. Hard rules:
  pain/injury assessment is "the physical therapist's call" (tested with a swollen-knee
  question — it deferred); any PT guidance provided is binding and substitutions must be
  named; start conservatively and state how to progress.

Each agent is independently testable from the command line, which is the fastest demo of a
single specialist:

```
python -m src.agents.physical_therapist "My knee aches after squats - normal?"
python -m src.agents.gym_trainer "Give me a simple 3-day beginner strength program."
```

---

## 6. Layer 4 — The router (`src/router.py`)

The router answers one question: *which specialist(s), if any, should see this?* It returns
a `RouteDecision` — label, confidence (0–1), a human-readable reason, which method decided
(`rules` or `llm`), and the raw cue scores for debugging.

It works in three stages, cheapest first:

**Stage 1 — RED_FLAG regexes, checked before everything.** A fixed list of urgent-care
patterns: severe/sharp pain, numbness or tingling, can't bear weight, visible deformity,
fever, chest pain, a hot or swollen calf (the DVT signature), "felt a pop", a joint that
buckles or gives way, wound/incision problems. Any match ends routing immediately at
confidence 0.97. This stage is deliberately **not** an LLM (decision D5): a safety gate must
behave identically every single time.

**Stage 2 — weighted keyword scoring.** Two cue lists — rehab/pain words for the PT
(sprain, rehab, post-op, range of motion, meniscus…) and training words for the trainer
(program, sets, reps, cardio, beginner, progressive overload…) — each with a weight of 1–3.
The scores decide:

- Only one side scored → that specialist, confidence scaled by cue strength.
- **Both sides scored and neither holds more than 70% of the total → TEAM.** Worked
  example: "Can I do cardio while rehabbing an ankle sprain?" scores PT 4 (rehab 2,
  sprain 2) vs trainer 2 (cardio 2); dominance 4/6 ≈ 0.67 ≤ 0.70 → TEAM.
- One side scored but the other dominates → the dominant specialist alone.
- Nothing scored, or the question is ≤2 words, or it's subjective ("best", "help") with
  almost no domain signal → **CLARIFY**. The vague-word guard only fires when total cue
  weight is ≤2, so "What's the best gym?" clarifies but "best exercises for a sprained
  knee" still routes.

**Stage 3 — LLM fallback, rarely reached.** If the rules' confidence is below 0.62, a
Groq/Llama classifier picks the label. Its output is parsed by a deliberately tolerant
parser (scans for the first valid label token and the first in-range decimal, survives
messy output). If even the LLM's confidence is below 0.50, the route collapses to CLARIFY —
when in doubt, ask instead of guessing.

**Measured result (the plan's §9 battery):** 12/12 questions routed correctly, every one by
Stage 1 or 2 — zero LLM calls, all confidences ≥ 0.70. Routing is effectively free and fully
explainable, which is a good presentation talking point: `RouteDecision.scores` lets you
show exactly *why* any question went where it did. Try it live:

```
python -m src.router "Is soreness two days after a workout normal or an injury?"
```

---

## 7. Layer 5 — The orchestrator (`src/orchestrator.py`)

The orchestrator is a **LangGraph state machine**. Mental model: a flowchart where each box
(node) is a Python function that reads a shared state dictionary and returns updates to it,
and the arrows (edges) can branch on the state's contents.

**The shared state (`TeamState`)** carries the question, the routing decision, each
specialist's `consult()` result, the final answer, per-specialist sources, and
`execution_trace` — a list every node appends one line to, which is how we can always show
exactly which path a question took (the trace in §2 is this field, verbatim).

**The nodes:**

| Node | What it does |
|---|---|
| `route_question` | Calls the router; writes label/confidence/reasoning into state |
| `consult_pt` | `PhysicalTherapistAgent().consult(question)` |
| `consult_trainer` | Same for the trainer; **on the TEAM route it passes the PT's draft as `peer_context`** |
| `synthesize_team_answer` | One LLM call that merges the usable drafts: attribute each specialist, keep citations, surface conflicts with PT winning on safety, add nothing new. Single-agent routes also pass through here so every answer has a consistent voice |
| `safety_response` | Returns the fixed RED_FLAG text. No retrieval, no LLM — nothing in this node can fail or vary |
| `ask_clarification` | One focused follow-up question (LLM, with a canned fallback if the LLM is down) |
| `fallback_handler` | Terminal for dead ends: apologizes, says what went wrong, prints the rebuild commands |

**Error philosophy (inherited from the opim-5517 reference project):** nodes never raise.
Agents capture errors into their result dict; conditional edges inspect state and steer dead
ends to `fallback_handler`; even the synthesizer degrades gracefully (if its LLM call fails,
it returns the raw drafts with attribution headers rather than losing the specialists'
work). Measured: with the entire `chroma_db/` directory deleted, the system returned a
polite fallback answer with fix-it instructions — no stack trace. On the TEAM route, if the
PT errors the trainer still runs (just without peer context), so one broken knowledge base
degrades the answer instead of killing it.

**Fixed texts live in code, not prompts:** the standing disclaimer (appended to *every*
final answer by the terminal nodes), the RED_FLAG safety response, and the fallback message
are Python constants. An LLM cannot forget, rephrase, or drop them.

**The public API is one function** — everything the future Streamlit app (Phase 5) needs:

```python
from src.orchestrator import answer_question
result = answer_question("...")
# {"final_answer", "route", "route_confidence",
#  "agents_consulted", "sources": {agent: [files]}, "execution_trace"}
```

And the full-pipeline CLI: `python -m src.orchestrator "your question"`.

---

## 8. The safety architecture, layered

Worth presenting as a stack — each layer catches what the previous one can't:

| Layer | Mechanism | Where |
|---|---|---|
| 1. Emergency detection | Deterministic RED_FLAG regexes, checked before any AI involvement; canned response | `router.py` / `orchestrator.py` |
| 2. Expertise silos | Each agent can only retrieve from its own collection | `rag_core.py` collections (D3) |
| 3. Grounding rule | "Answer ONLY from provided context" baked into the base prompt — can't be omitted by a subclass | `agents/base.py` |
| 4. Persona deference | PT never diagnoses; trainer never assesses pain; both refuse out-of-scope plainly | persona prompts |
| 5. Constraint ordering | On TEAM, PT runs first and its draft binds the trainer (D4); synthesis lets PT win conflicts | `orchestrator.py` |
| 6. Fixed disclaimer | Appended by code to every final answer | `orchestrator.py` constant |
| 7. Graceful failure | Never-raise agents + fallback node — worst case is an apology with fix-it steps | `agents/base.py` + graph edges |

---

## 9. Demo guide

**Setup from a fresh clone** (each person needs their own free Groq key from
console.groq.com in `.env`):

```
pip install -r requirements.txt
python -m src.ingest --agent pt
python -m src.ingest --agent trainer
```

**The three killer artifacts** (Phase 6 will screenshot these; they demo the thesis):

1. **Constraint handoff (TEAM):** `python -m src.orchestrator "I'm 8 weeks post-meniscus
   surgery - how do I get back into lifting safely?"` — point at the trace line
   `with PT draft as peer_context`, then at the trainer's substitutions respecting the PT's
   restrictions.
2. **Safety short-circuit (RED_FLAG):** `python -m src.orchestrator "My calf is swollen,
   hot, and I have sharp pain when I stand."` — two trace lines, no agent, no LLM, fixed
   urgent-care response.
3. **Honest ignorance (grounding):** `python -m src.agents.gym_trainer "How much protein
   should I eat to build muscle?"` — "I don't have material on nutrition specifics" instead
   of a confident invented number. This is the anti-hallucination story in one screenshot.

The full 12-question expected-behavior table is §9 of PROJECT_PLAN.md; the measured routing
results are in its Phase 4 results block.

---

## 10. Current limitations (know these before Q&A)

- **Single-turn.** No memory of the user or prior questions; each question stands alone
  (privacy-by-design for Phase A; personalization is a Phase B discussion).
- **Naive retrieval.** Top-k vector similarity only — no hybrid keyword search, reranking,
  or metadata filters.
- **Routing is keyword-driven.** Excellent on the battery, but adversarial or oddly-phrased
  questions fall to the LLM classifier; RED_FLAG patterns can false-positive (by design —
  err toward safety).
- **No orthopedic surgeon agent yet** (Phase B). RED_FLAG's canned "contact your surgeon"
  response is its placeholder, and the plan's §11 documents exactly where the surgeon slots
  in (new corpus + subclass + route + graph node; synthesis and UI already handle N agents).
- **No web UI yet** (Phase 5) and **no frozen evaluation table yet** (Phase 6).
- **Corpus breadth ≠ clinical depth.** Public-domain patient-education material, not
  clinical protocols — appropriate for an educational support tool, and the disclaimer
  exists precisely because of this.

---

## 11. Glossary (for the presentation)

- **RAG (Retrieval-Augmented Generation):** answer questions by first *retrieving* relevant
  passages from a trusted library, then having the LLM write *only from those passages*.
  Grounding beats memory: the model cites documents instead of improvising.
- **Embedding:** a list of numbers (here, 384 of them) representing a text's meaning;
  similar meanings → nearby vectors. Produced here by a small local model, all-MiniLM-L6-v2.
- **Vector database / ChromaDB:** a store that finds "nearest" vectors fast. Embedded = runs
  inside our process from a folder on disk, like SQLite; no server.
- **Chunk:** a ~1,000-character slice of a document; the unit of retrieval.
- **Top-k retrieval:** fetch the k most similar chunks to the question (we use k=6).
- **LangGraph:** a library for building LLM workflows as explicit state machines — nodes
  (functions) + conditional edges (branching) over a shared state dict. Gives us the
  guaranteed-terminating flowchart in §1 and the execution trace.
- **Groq:** LLM API service (free tier) running Llama 3.3 70B; used for agent answers,
  synthesis, clarification, and the rare routing fallback.
- **Orchestrator:** the component that sequences router → specialists → synthesizer and
  handles every failure path.
- **peer_context:** our agent-to-agent handoff — one specialist's draft passed into
  another's prompt as binding constraints.
- **Red flag:** a symptom pattern that warrants urgent medical evaluation rather than
  advice from this tool.
