# Capabilities Overview — How the Recovery Team Actually Works

> **Who this is for:** every teammate, and especially whoever builds the presentation.
> [PROJECT_PLAN.md](PROJECT_PLAN.md) tracks *what* was built, in what order, and what's next.
> This document explains *how* each part works and *why* it was designed that way, in enough
> depth that you can confidently explain (and demo) the parts you didn't personally build.
> Sections 1–11 describe the core system as of Phase 4c (2026-07-14), updated since for the
> **fourth specialist** (Sports Nutritionist) and for **multi-session chat persistence**
> (Phase 5b, 2026-07-31): four specialists live and orchestrated end-to-end with structured
> constraint handoff between them, an LLM-primary router with a deterministic keyword net
> under it, and chat history that survives a page reload. Section 12 covers the production
> extensions layered on top (GraphRAG, multimodal visual search, security scanners, unit
> economics, the evaluation harness, and persistence). Update this document when a phase
> changes how something works.

---

## 1. The product in one paragraph

A user recovering from an injury asks one chat interface a question. Behind it, a **router**
decides which specialist(s) should answer — an **Orthopedic Surgeon agent**, a **Physical
Therapist agent**, a **Gym Trainer agent**, a **Sports Nutritionist agent**, or a chain of
them. Each specialist answers **only from its own curated library of vetted documents** (this
is Retrieval-Augmented Generation — RAG), and a **synthesizer** merges their drafts into one
coherent "care team" response with source citations and a standing disclaimer. Questions that
look like medical emergencies never reach an AI model at all — they get a fixed safety
response. Every exchange is saved to a local database, so a user can run several recovery
conversations and come back to any of them (§12.7). The core thesis: one general-purpose LLM
hallucinates and can't credibly be four experts at once; narrow agents, each grounded in its
own knowledge base and coordinated by an orchestrator, can.

```
                            ┌──────────────────────────┐
        user question ────► │   router (src/router.py) │
                            └────────────┬─────────────┘
   ┌───────────┬─────────────┬───────────┴────┬─────────────┬───────────┬──────────┐
   ▼           ▼             ▼                ▼             ▼           ▼          ▼
PT_ONLY   TRAINER_ONLY    SURGEON      NUTRITION_ONLY      TEAM      RED_FLAG   CLARIFY
   │           │             │                │             │           │          │
   ▼           ▼             ▼                ▼             ▼           ▼          ▼
PT agent   Trainer       Surgeon        Nutritionist   surgeon → PT   canned     one
(pt_docs)  agent         agent          agent          → trainer →    safety     focused
           (trainer_     (surgeon_      (nutrition_    nutritionist,  response   follow-up
            docs)         docs)          kb)           whichever      (no LLM       │
   │           │             │                │        buckets fired,  ever)        │
   │           │             │                │        each passing      │          │
   │           │             │                │        structured        │          │
   │           │             │                │        constraints down  │          │
   └───────────┴──────┬──────┴────────────────┴─────────────┘             │          │
                      ▼                                                   │          │
           synthesize_team_answer                                         │          │
           (attributes each specialist consulted;                         │          │
            surgeon wins post-op/hardware conflicts,                      │          │
            PT wins everything else safety-related)                       │          │
                      │                                                   │          │
                      ▼                                                   ▼          ▼
               final answer + [source: ...] citations + disclaimer
                      │
                      ▼
        saved as one transcript row (src/database.py) → reopenable later
```

---

## 2. A question's journey (real, observed run)

The fastest way to understand the system is to follow one question through it. This is the
actual execution trace from Phase 4 testing, not a mock-up:

> **Note (Phase 4c, extended since):** this trace is from before the router redesign — at the
> time, routing was regex/rules-based, hence `method: rules` and "no LLM call" below. Since
> Phase 4c the router is LLM-primary (§6), so re-running this exact question today would show
> `method: llm` and cost one Groq call for the routing step itself. The chain is also longer
> now: Phase 4b put the **surgeon first** on TEAM, and the nutritionist was added at the end,
> so this same question today produces `consult_surgeon → consult_pt → consult_trainer →
> synthesize` (see §9 artifact 1 for the real three-way trace). What has *not* changed is the
> mechanism this section exists to explain — one specialist's draft becomes the next one's
> binding `peer_context`, and code appends the disclaimer. Kept as-is for the historical
> record rather than rewritten.

**Question:** *"I'm 8 weeks post-meniscus surgery — how do I get back into lifting safely?"*

```
route_question:    TEAM (0.90, rules) - Both rehab (4) and training (2) cues present.
consult_pt:        5 source(s)
consult_trainer:   4 source(s), with PT draft as peer_context
synthesize_team_answer: merged 2 draft(s)
```

What happened at each step:

1. **Routing (as it worked pre-Phase-4c — see the note above).** The router's keyword scorer
   found rehab cues ("post-…surgery" and "meniscus", weight 2 each = 4) and training cues
   ("lifting", weight 2). Both specialists signalled and neither dominated, so the route is
   **TEAM** with confidence 0.90 — decided by deterministic rules in microseconds, no LLM
   call.
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

| | Physical Therapist | Gym Trainer | Orthopedic Surgeon | Sports Nutritionist |
|---|---|---|---|---|
| Folder → collection | `data/pt/` → `pt_docs` | `data/trainer/` → `trainer_docs` | `data/surgeon/` → `surgeon_docs` | `data/nutrition/` → `nutrition_kb` |
| Size | 29 documents (25 txt + 4 PDF), 203 chunks | 22 documents (19 txt + 3 PDF), 536 chunks | 18 documents (all txt) | 10 documents (all markdown) |
| Anchor documents | NIA "Exercise & Physical Activity for Older Adults" guide (34-page PDF), 3 CDC STEADI fall-prevention brochures | HHS "Physical Activity Guidelines for Americans, 2nd ed." (118-page PDF) | MedlinePlus post-op/discharge instruction set (wound care, crutches, ACL/rotator-cuff/knee-arthroscopy discharge) | NIH Office of Dietary Supplements health-professional fact sheets (protein/vitamin C/D, zinc, calcium, omega-3, exercise & athletic performance) |
| Text sources | MedlinePlus injury topics, NIAMS fact sheets, NINDS pain page, NHS rehab pages | CDC physical-activity-basics, NIA get-started guides, MedlinePlus, 8 practical NHS exercise pages (strength/balance/flexibility/sitting/Couch-to-5K) | MedlinePlus encyclopedia/patient-instructions pages, NIAMS hip-replacement page, 3 NHS post-surgery recovery pages | MedlinePlus diet-and-wound-healing, protein, vitamins, and minerals pages |

The nutrition corpus is the one that is **scraper-built rather than hand-curated**
(`python -m src.ingest --agent nutrition --scrape`, see `src/scrapers/nutrition_scraper.py`);
it lands the same public-domain NIH/MedlinePlus material as files on disk, so ingestion and
licensing review work identically to the other three. Each corpus folder also has a
`visuals/` subfolder feeding the CLIP visual search (§12.3).

Sourcing rules (§7.5 of the plan): US-government content is public domain; NHS pages are
under the Open Government Licence v3.0 (reuse with attribution). Every file's URL, license,
and fetch date is logged in [data/SOURCES.md](data/SOURCES.md), and every text file carries a
title/source/license/date header — which also gives the LLM provenance context when a chunk
is retrieved. Three elderly-onboarding documents appear in BOTH the PT and trainer corpora on
purpose: the collections are siloed, so content both specialists need must exist in both. The
surgeon corpus deliberately uses MedlinePlus's *procedure/discharge-instruction* pages
(`ency/article/...`, `ency/patientinstructions/...`) rather than the *topic-summary* pages
(`kneereplacement.html`, etc.) already used in `data/pt/` — distinct content, no duplication.

**Why the corpora are "pre-curated" files in git** rather than live-scraped at runtime:
reproducibility (everyone ingests identical bytes), licensing review happens once at commit
time, and teammates without network quirks can rebuild identically.

---

## 4. Layer 2 — The RAG core (`src/rag_core.py`)

This module is the shared plumbing all four specialists use. It does two jobs: **ingestion**
(build a knowledge base) and **retrieval** (fetch relevant passages at question time).

### Ingestion: `python -m src.ingest --agent pt|trainer|surgeon|nutrition [--fresh] [--scrape]`

One agent per invocation — there is no `--agent all`. `--fresh` clears that agent's
collection first; `--scrape` re-fetches the corpus before ingesting (wired for `pt` and
`nutrition` only).

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
`k` nearest chunks (all four agents use `k=6`). Those chunks — each tagged with its source
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
   the TEAM route, chaining most-restrictive-first (surgeon → PT → trainer).

### Structured constraints (`constraints.py`, Phase 4b)

Free-text `peer_context` works, but it makes the downstream specialist's LLM parse
restrictions out of prose and hope it caught them all. `extract_constraints(answer)` makes
one extra LLM call to pull a short structured list —
`[{"body_part", "restriction", "duration"}, ...]` — out of a specialist's draft.
`format_constraints_block()` renders that list as a labeled bullet block ("BINDING
RESTRICTIONS FROM SURGEON: ...") that gets **prepended** to the same `peer_context` string
the next specialist already accepts — no change to the frozen `consult()` signature (§5.2).
Extraction never raises: a parse failure or LLM hiccup degrades to `[]`, and the raw draft
still carries the restriction in prose either way. The structured list also flows out through
`answer_question()`'s additive `constraints` field for a future UI to render as a checklist.

### The four personas

- **`orthopedic_surgeon.py`** (Phase 4b) — orthopedic-surgeon voice. Scope: post-operative
  protocols, weight-bearing status and mobility-aid timelines, hardware (pins/plates/screws)
  precautions, wound/incision care basics, recovery milestones by week or month. Hard rules:
  defers to the *patient's own surgeon's* individual orders when they conflict with general
  material; states plainly that its restrictions are binding on PT/trainer plans, not the
  reverse; declines programming/nutrition/day-to-day pain-management questions.
- **`physical_therapist.py`** — licensed-DPT voice. Scope: rehab progressions, normal
  soreness vs. warning-sign pain, range-of-motion/mobility work, when to regress an
  exercise. Hard rules: never diagnose (explain what the context says, refer to a
  clinician); refuse out-of-scope topics plainly (tested: "best protein powder?" → honest
  not-my-area + dietitian referral); make advice stage-aware ("in the first 72 hours…" vs
  "once swelling has settled…").
- **`gym_trainer.py`** — certified-trainer voice. Scope: programming (days/sets/reps),
  progressive overload, form cues, beginner and older-adult modifications. Hard rules:
  pain/injury assessment is "the physical therapist's call" (tested with a swollen-knee
  question — it deferred); any PT or surgeon guidance provided is binding and substitutions
  must be named; start conservatively and state how to progress.
- **`nutritionist.py`** — clinical sports/recovery-nutritionist voice, the fourth specialist.
  Scope: daily protein targets for muscle protein synthesis, anti-inflammatory micronutrients
  (omega-3, vitamin C, zinc), bone and tendon repair nutrients (collagen + vitamin C,
  calcium + vitamin D), hydration, and GI support for patients on post-op narcotics or
  antibiotics. Hard rules: respects every upstream surgical/PT/training restriction passed in
  `peer_context` (it is consulted **last** on TEAM, so it always has them), and stays out of
  diagnosis and programming. This agent is also what makes the trainer's "I don't have
  material on nutrition specifics" refusal (§9, artifact 3) a *routing* answer rather than a
  dead end — the same question now has a specialist who can actually answer it.

Each agent is independently testable from the command line, which is the fastest demo of a
single specialist:

```
python -m src.agents.physical_therapist "My knee aches after squats - normal?"
python -m src.agents.gym_trainer "Give me a simple 3-day beginner strength program."
python -m src.agents.orthopedic_surgeon "How long until I can put weight on my knee after knee arthroscopy?"
python -m src.agents.nutritionist "How much protein should I eat while recovering from ACL surgery?"
```

---

## 6. Layer 4 — The router (`src/router.py`)

The router answers one question: *which specialist(s), if any, should see this?* It returns
a `RouteDecision` — label, confidence (0–1), a human-readable reason, which method decided
(`rules` or `llm`), and `scores` — `{"pt", "trainer", "surgeon", "nutrition"}`, each 0 or 1,
marking which specialist(s) apply. This is what the orchestrator reads to decide who to chain
on TEAM. Adding the nutritionist meant one more label and one more score bucket; because the
`scores` dict is the contract, `orchestrator.py` needed no signature change.

**Redesigned in Phase 4c to be LLM-primary** (decision D11) — this supersedes the
Phase 4/4b design, which used a weighted regex keyword scorer (rehab words for the PT,
training words for the trainer, post-op words for the surgeon) and only fell back to an LLM
when the rules were unsure. That regex layer kept needing hand-patches as phrasing varied —
the bug that triggered the redesign: a cue meant to catch "stitches out" didn't match the
equally natural "when do my stitches come out." Rather than keep patching individual
patterns, the weighted scorer was deleted outright.

It now works in three stages (the third was added after the Phase 4c redesign — see the
"keyword net" note below):

**Stage 1 — RED_FLAG regexes, checked before everything, unchanged.** A fixed list of
urgent-care patterns: severe/sharp pain, numbness or tingling, can't bear weight, visible
deformity, fever, chest pain, a hot or swollen calf (the DVT signature), "felt a pop", a
joint that buckles or gives way, wound/incision problems. Any match ends routing immediately
at confidence 0.97. This is the **only** regex left in the router, deliberately (decision
D5): a safety gate must behave identically every single time, which an LLM can't guarantee.

**Stage 2 — one Groq/Llama call decides everything else.** The prompt asks the model for two
things at once: a single overall label (`PT_ONLY` / `TRAINER_ONLY` / `SURGEON` /
`NUTRITION_ONLY` / `TEAM` / `CLARIFY`) and which specialist(s) are relevant (any subset of
`pt`, `trainer`, `surgeon`, `nutrition`). The response is parsed by a deliberately tolerant
parser (scans the whole response for a valid label and an in-range confidence, survives messy
formatting) into the same `scores` shape the orchestrator's TEAM chain already consumed in
Phase 4b — so `orchestrator.py` needed **zero changes** for this redesign, only `router.py`
did. A model that says `TEAM` but names fewer than 2 specialists is treated as inconsistent
and defaults to consulting all of them, rather than silently under-chaining.

**Stage 3 — a deterministic keyword net catches what the LLM won't commit to.**
`keyword_route_fallback()` runs whenever the classifier is unsure (confidence below 0.50),
answers `CLARIFY`, or fails outright (no key, network error). It checks, in order: a short
list of high-risk phrases (`"starvation diet"` → nutritionist, `"heavy squatting"` → PT,
`"infection"` → RED_FLAG), then per-specialist keyword lists — two or more specialists
matched means `TEAM`. A match reports `method: "rules"` at confidence 0.85; only if nothing
matches does the route finally collapse to CLARIFY.

This stage was added *after* the Phase 4c redesign, and it walks back two of that redesign's
consequences. Explicit questions were collapsing to CLARIFY when the classifier hedged, and —
more operationally — **routing no longer dies without a Groq key**: an earlier version of this
document said `classify()` returned CLARIFY for every non-RED_FLAG question when no key was
set, and that is no longer true. Note the design ordering, which is the interesting part for
the presentation: the keyword list sits *under* the classifier as a safety net, not *in front
of* it as the primary decision-maker, which is exactly the arrangement D11 rejected. Regex
went from being the router to being the floor.

**Trade-off, explicit:** routing is no longer free. Every non-RED_FLAG question now costs a
Groq call and takes real latency, instead of resolving instantly from local keyword weights.
A teammate without a key still gets keyword-quality routing rather than nothing — but the
LLM classifier is what makes routing robust to phrasing, so a key remains the expectation.

**What's been verified:** the parser (`_parse_llm_response`) was unit-tested against
synthetic `LABEL | confidence | specialists | reason` strings — including malformed ones —
and confirmed to produce correct `scores`; `classify()` was confirmed to still resolve
RED_FLAG via regex and to degrade to CLARIFY (not crash) on an empty question or a missing
key. **The full §9 battery has now been run live** (2026-07-15, with a real Groq key):
**13/15 correct.** One real TEAM chain was run end-to-end and produced a real synthesized
answer that correctly said the surgeon's post-op guidance "takes precedence" — D10's
priority rule showing up in an actual model output.

**Two real accuracy gaps found, not yet fixed:**
1. "What's the best gym?" resolves to `TRAINER_ONLY` (0.90) instead of `CLARIFY`. The old
   regex router had an explicit vague-word guard for exactly this kind of question; the LLM
   is more willing to just answer a subjective/underspecified question than ask for
   clarification.
2. A question with explicit surgeon-relevant language ("my surgeon cleared me for full
   weight-bearing 6 weeks after ACL reconstruction...") under-chains to PT+trainer only,
   missing the surgeon — even though those are precisely the phrases the old
   `_SURGEON_CUES` regex list was built to catch.

Likely fix for both: prompt-level (few-shot examples, or an explicit instruction that
mentioning a specific surgery/clearance/post-op milestone should flag 'surgeon' even when
the question is really about returning to training) — not done yet, flagged for follow-up.

---

## 7. Layer 5 — The orchestrator (`src/orchestrator.py`)

The orchestrator is a **LangGraph state machine**. Mental model: a flowchart where each box
(node) is a Python function that reads a shared state dictionary and returns updates to it,
and the arrows (edges) can branch on the state's contents.

**The shared state (`TeamState`)** carries the question, the routing decision (including
`route_scores`, Phase 4b — the same `{"pt", "trainer", "surgeon", "nutrition"}` dict the
router produced), each specialist's `consult()` result and extracted constraints, the final
answer, per-specialist sources, and `execution_trace` — a list every node appends one line to,
which is how we can always show exactly which path a question took (the trace in §2 is this
field, verbatim).

**The nodes:**

| Node | What it does |
|---|---|
| `route_question` | Calls the router; writes label/confidence/reasoning/`route_scores` into state |
| `consult_surgeon` | `OrthopedicSurgeonAgent().consult(question)`, then `extract_constraints()` on its own draft (Phase 4b) |
| `consult_pt` | `PhysicalTherapistAgent().consult(question)`; **on TEAM, if the surgeon already ran, receives its structured constraints + draft as `peer_context`** |
| `consult_trainer` | Same for the trainer; **on TEAM, receives whichever upstream specialists ran (surgeon and/or PT), each as a constraints block + draft** |
| `consult_nutritionist` | `NutritionistAgent().consult(question)` against `nutrition_kb`; **last in the TEAM chain, so it receives every upstream draft + constraints block that ran** |
| `synthesize_team_answer` | One LLM call that merges the usable drafts: attribute each specialist, keep citations, surface conflicts — surgeon wins on post-op/hardware/weight-bearing, PT wins otherwise (Phase 4b) — add nothing new. Single-agent routes also pass through here so every answer has a consistent voice |
| `safety_response` | Returns the fixed RED_FLAG text. No retrieval, no LLM — nothing in this node can fail or vary |
| `ask_clarification` | One focused follow-up question (LLM, with a canned fallback if the LLM is down) |
| `fallback_handler` | Terminal for dead ends: apologizes, says what went wrong, prints the rebuild commands (now including `--agent surgeon`) |

**Which specialists actually get consulted on TEAM (Phase 4b)** is decided by `route_scores`,
not a fixed pair: the conditional edges after `route_question`, `consult_surgeon`,
`consult_pt`, and `consult_trainer` each check whether the *next* specialist's bucket scored
above zero before routing to it. A PT+trainer TEAM question (no surgeon or nutrition cues)
skips `consult_surgeon` and `consult_nutritionist` entirely — the chain is exactly as long as
the question calls for, never padded with an irrelevant specialist. The order
(**surgeon → PT → trainer → nutritionist**) is most-restrictive-first, so each agent's
restrictions reach everyone downstream and the nutritionist, which must respect all of them,
goes last.

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

**The public API is one function** — everything the Streamlit app (Phase 5) needs:

```python
from src.orchestrator import answer_question
result = answer_question("...")
# {"final_answer", "route", "route_confidence",
#  "agents_consulted", "sources": {agent: [files]},
#  "constraints": {agent: [{body_part, restriction, duration}]},   # Phase 4b
#  "execution_trace"}
```

Those seven keys are also exactly what one saved transcript row holds (§12.7), so replaying a
conversation from the database reconstructs the same UI a live answer produced.

And the full-pipeline CLI: `python -m src.orchestrator "your question"`.

---

## 8. The safety architecture, layered

Worth presenting as a stack — each layer catches what the previous one can't:

| Layer | Mechanism | Where |
|---|---|---|
| 1. Emergency detection | Deterministic RED_FLAG regexes, checked before any AI involvement; canned response | `router.py` / `orchestrator.py` |
| 2. Expertise silos | Each agent can only retrieve from its own collection | `rag_core.py` collections (D3) |
| 3. Grounding rule | "Answer ONLY from provided context" baked into the base prompt — can't be omitted by a subclass | `agents/base.py` |
| 4. Persona deference | PT never diagnoses; trainer never assesses pain; nutritionist never programs or diagnoses; all refuse out-of-scope plainly | persona prompts |
| 5. Constraint ordering | On TEAM the chain runs most-restrictive-first (surgeon → PT → trainer → nutritionist) and every upstream draft binds those below it (D4); synthesis lets the surgeon win post-op/hardware conflicts and the PT win the rest (D10) | `orchestrator.py` |
| 6. Fixed disclaimer | Appended by code to every final answer | `orchestrator.py` constant |
| 7. Graceful failure | Never-raise agents + fallback node — worst case is an apology with fix-it steps | `agents/base.py` + graph edges |

---

## 9. Demo guide

**Setup from a fresh clone** (each person needs their own free Groq key from
console.groq.com in `.env` — as of Phase 4c this is required even to get routing to work,
not just to get specialist answers):

```
pip install -r requirements.txt
python -m src.ingest --agent pt
python -m src.ingest --agent trainer
python -m src.ingest --agent surgeon
python -m src.ingest --agent nutrition
streamlit run app.py
```

`app.py` (Phase 5) is a chat UI over `answer_question()` plus `src/database.py` — nothing
else from the backend. Per-message it shows a route chip, colored badges for whichever
specialist(s) were consulted (🦴/🩺/🏋️/🥗), an expander with per-agent sources, an expander
with any extracted binding restrictions (Phase 4b's `constraints` field), a token/cost line,
and — toggled on in the sidebar — the raw routing/execution trace. The sidebar has a
**Conversations** block (new chat, reopen a past conversation, delete — §12.7) and one rebuild
button per knowledge base. This is the fastest way to demo all three killer artifacts below
live, or they can be run standalone via the CLIs.

**Demo tip for the persistence story:** ask a TEAM question, reload the browser, and reopen the
conversation from the sidebar — the badges, sources, and binding restrictions all come back.
Then hit "New chat" and ask something unrelated to show two conversations living side by side.

**The three killer artifacts** (Phase 6 will screenshot these; they demo the thesis):

1. **Constraint handoff (TEAM, now three-way):** `python -m src.orchestrator "I'm 8 weeks
   post-meniscus surgery - how do I get back into lifting safely?"` — real live trace:
   `consult_surgeon (6 sources) → consult_pt (5 sources, with surgeon draft as
   peer_context) → consult_trainer (4 sources, with 2 upstream draft(s) as peer_context) →
   synthesize (merged 3 drafts)`. The synthesized answer explicitly says the surgeon's
   post-op guidance "takes precedence" — D10's priority rule in a real model output.
2. **Safety short-circuit (RED_FLAG):** `python -m src.orchestrator "My calf is swollen,
   hot, and I have sharp pain when I stand."` — two trace lines, no agent, no LLM, fixed
   urgent-care response. Confirmed live, unaffected by the router redesign.
3. **Honest ignorance (grounding):** `python -m src.agents.gym_trainer "How much protein
   should I eat to build muscle?"` — "I don't have material on nutrition specifics" instead
   of a confident invented number. This is the anti-hallucination story in one screenshot.

The full battery (12 original + 3 surgeon/three-way rows) is §9 of PROJECT_PLAN.md. **Now
re-run live against the Phase 4c LLM-primary router (2026-07-15): 13/15 correct** — see §6
above for the two accuracy gaps found (a vague-question CLARIFY miss, and a three-specialist
question that under-chains to two). The original Phase 4 results block still has the
regex-era numbers for historical comparison.

---

## 10. Current limitations (know these before Q&A)

- **Single-turn reasoning, even though history is now saved.** Conversations persist to disk
  and reopen (§12.7), but the agents never receive prior turns as context — each question is
  still answered from scratch, so "what about my knee?" as a follow-up will not resolve. What
  changed in Phase 5b is what's *stored*, not what's *reasoned over*; using history to tailor
  answers is still a Phase B discussion. The flip side of storing it: whatever health details a
  user types now sit in plaintext in `data/chat_history.db`, which is fine for a local
  single-user demo but would need real thought before any hosted deployment.
- **Naive retrieval.** Top-k vector similarity only — no hybrid keyword search, reranking,
  or metadata filters.
- **Routing now costs an LLM call (Phase 4c).** Every non-RED_FLAG question is classified by
  Groq rather than free local keyword rules — this trades routing speed/cost/determinism for
  robustness to phrasing. Without a Groq key, routing falls through to the deterministic
  keyword net (§6 stage 3) and only reaches CLARIFY if no keyword matches — so the system
  still routes, just more crudely. RED_FLAG stays regex and can still false-positive (by
  design — err toward safety).
- **Router accuracy, measured live: 13/15 on the §9 battery (2026-07-15).** Two known,
  unfixed gaps: a vague subjective question ("what's the best gym?") resolves to
  `TRAINER_ONLY` instead of `CLARIFY`; a question with explicit surgeon-relevant language
  under-chains to PT+trainer only, missing the surgeon. Both are prompt-tuning follow-ups,
  not structural bugs — see §6.
- **The Streamlit UI (Phase 5) has been verified live** via Streamlit's `AppTest` (real
  question in, real synthesized answer with correct badges/route chip/sources out, zero
  exceptions) — but `AppTest` doesn't render actual CSS/layout, so a human should still
  click through it once in a real browser before the video demo. **No frozen evaluation
  table yet** (Phase 6).
- **RED_FLAG doesn't consult the surgeon agent.** The Orthopedic Surgeon agent exists now
  (Phase 4b, pulled forward from the original Phase B plan), but RED_FLAG's canned
  "contact your surgeon" response deliberately stays deterministic/no-agent per D5 — §11 of
  the plan documents this as open, not forgotten.
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
  synthesis, clarification, and (since Phase 4c) every routing decision except RED_FLAG.
- **Orchestrator:** the component that sequences router → specialists → synthesizer and
  handles every failure path.
- **peer_context:** our agent-to-agent handoff — one specialist's draft (plus, since
  Phase 4b, its structured constraints) passed into another's prompt as binding restrictions.
- **Structured constraints (Phase 4b):** a short list of `{body_part, restriction, duration}`
  extracted from a specialist's draft (`extract_constraints()`), so a downstream specialist
  doesn't have to parse restrictions out of free prose. Rides alongside, not instead of, the
  raw draft in `peer_context`.
- **Red flag:** a symptom pattern that warrants urgent medical evaluation rather than
  advice from this tool. The one route still decided by regex, not the LLM (D5).
- **Session / transcript (Phase 5b):** a *session* is one conversation (a row in
  `chat_sessions`); a *transcript* is one complete turn inside it — question, answer, route,
  specialists, sources, restrictions, tokens (a row in `chat_transcripts`). Reopening a
  conversation means replaying its transcripts in order. See §12.7.
- **WAL (write-ahead logging):** a SQLite mode where writes go to a separate log file instead
  of locking the whole database, so readers and a writer can work at the same time. It is why
  two browser tabs can hold two live chats without tripping over each other.

---

## 12. Extended Multi-Agent System Capabilities

### 12.1 Sports Nutritionist Specialist Agent 🥗
- **Domain:** Post-operative recovery nutrition, protein synthesis targets (1.2–2.0g/kg), anti-inflammatory micronutrients (Zinc, Vitamin C, Omega-3), and tendon/ligament collagen healing protocols.
- **Knowledge Base:** Siloed under `data/nutrition/` and embedded into the `nutrition_kb` Chroma collection.
- **Where it sits in the team:** a full `SpecialistAgent` like the other three — its own route label (`NUTRITION_ONLY`), its own `route_scores` bucket, and the **last** link in the TEAM chain, so every clinical restriction upstream reaches it as `peer_context`. See §5 (persona), §6 (routing), and §7 (`consult_nutritionist`) for how it integrates rather than bolts on.

> **Accuracy note (2026-08-02):** several claims in this section were found overstated
> during an audit and have been corrected below to describe what the code actually does.
> The originals are preserved in git history. See PROJECT_PLAN.md's audit results block.

### 12.2 Curated clinical reference lookup (`src/graph_rag/kuzu_graph.py`)
- **What it actually is:** a hand-curated in-memory lookup over **4 surgeries** (ACL
  reconstruction, meniscus repair, rotator cuff repair, total knee arthroplasty), mapping
  each to its contraindicated movements, rehab exercises, and healing nutrients.
- **The Kùzu graph database is not active.** `kuzu` is not in `requirements.txt`, so the
  DB never initializes and every query reads the in-memory dict. Real Cypher
  schema/query code exists in the file but is unreachable as shipped — it would need
  `kuzu` added and a caller wired to `query_contraindications()`.
- **Fixed in the audit:** it previously defaulted to "ACL Reconstruction" whenever nothing
  matched, silently stapling ACL contraindications onto *every* answer regardless of
  relevance. It now returns no match instead, per the §7.1 grounding rule.

### 12.3 Visual search over the diagram corpus (`src/multimodal/clip_search.py`)
- **Technology:** real CLIP image embeddings via `sentence-transformers` (`clip-ViT-B-32`),
  computed once over 277 images and cached to `clip_index.npz` (gitignored, auto-rebuilds
  when the image set changes).
- **Why it matters here:** ~94% of this corpus was auto-extracted from PDF pages with
  opaque filenames like `pdf_hhs_physical_activity_guidelin_p62_img1.jpg`. The previous
  implementation matched on filenames only and never opened an image, so those were
  unfindable by any query. Verified: that exact file is a photo of a bodyweight squat and
  now ranks #1 for "squat exercise form".
- **Hybrid scoring:** CLIP similarity plus a small filename-keyword bonus. CLIP is trained
  on natural photographs and measurably under-ranks dense text-heavy instructional
  diagrams (a labeled squat-form infographic scored below rank 20 for that same query);
  the bonus recovers those without displacing genuine visual matches.
- **Honest limits:** CLIP is a general-purpose model, not medically trained — expect solid
  results on "person doing a squat" or "food plate diagram", weaker discrimination between
  e.g. a meniscus-tear and an ACL diagram. A similarity floor (0.20) prevents confidently
  showing an unrelated image, since CLIP always returns *some* nearest neighbour.

### 12.4 Patient photo upload (`src/vision.py`)
- **What it does:** a user can attach a photo (swelling, an incision, exercise form) in the
  chat. It is described once by a vision model, and that description is folded into the
  question before the normal pipeline runs.
- **Provider:** Google Gemini free tier (`gemini-flash-latest`). This is the **only** part
  of the system not on Groq — a live check of the Groq account found no vision-capable
  model available at all. `GOOGLE_API_KEY` is optional; text questions work without it.
- **Why describe-then-route rather than passing pixels to the specialists:** every
  specialist answer is grounded in its own retrieved corpus (§7.1); handing four agents raw
  pixels would bypass that. This keeps routing, grounding, and synthesis unchanged.
- **Safety:** the vision prompt is constrained to neutral visual description only — no
  diagnosis, no severity judgement, no advice. Verified live that a photo described as
  showing "a surgical incision with redness and yellow drainage" trips the deterministic
  RED_FLAG gate and short-circuits, even when the typed question was innocuous.
- **Not stored:** uploaded bytes are used for the one API call and discarded; only the text
  description persists in session chat history.

### 12.5 Security scanners & guardrails (`src/security/guardrails.py`)
- **Prompt injection scanner:** regex patterns intercepting system-prompt disclosure
  requests, DAN jailbreaks, instruction overrides, and SQL-injection strings.
- **PII redaction:** redacts SSNs, email addresses, and phone numbers before text reaches
  an LLM.
- **Fixed in the audit:** this module was previously only called from the unused
  `src/cli.py` — never from `app.py` or the orchestrator, so it protected nothing a real
  user touched. It is now wired into `answer_question()` on both input and output, with a
  `BLOCKED` route visible in the execution trace.
- **Honest limit:** it is a literal regex blocklist, bypassable by rephrasing. Groq offers
  `meta-llama/llama-prompt-guard-2-86m`, a purpose-built injection classifier, as a
  stronger drop-in upgrade — noted, not yet implemented.

### 12.6 Business unit economics (`src/business/unit_economics.py`)
- **Cost estimate:** input ($0.59/1M) and output ($0.79/1M) Groq pricing applied to a token
  count **estimated** as `len(text)/4` — a heuristic, *not* real usage metadata from the
  API response. Labeled as an approximation in the UI.
- **Session tracking:** the sidebar computes real per-exchange cost from the actual chat
  history and shows an accumulated session total with a budget warning.
- **Fixed in the audit:** the sidebar previously displayed a **hardcoded `$0.0012`** and
  never touched a real query. The budget guard still does not *block* requests when
  exceeded — it warns. Stated plainly rather than described as enforcement.

### 12.7 High-Risk Patient Safety & LLM-as-a-Judge Evaluator
- **Location:** `tests/test_high_risk_scenarios.py` & `src/eval/eval_suite.py`
- **Stress-Test Benchmark:** Tests uninsured / self-treating patient scenarios (premature 225lb heavy gym squatting, skipping PT visits, forcing shoulder ROM, extreme 500 cal/day starvation diets, infection red-flags).
- **LLM-as-a-Judge Evaluation:** Uses Groq `Llama-3.3-70B` to evaluate outputs for **Clinical Safety (1–5)**, **Constraint Adherence (1–5)**, and **Brevity & Conciseness (1–5)**.
- **Fixed in the audit — read before citing any pass rate:** the judge previously returned
  a **hardcoded perfect score with `PASS: True` on any exception** (missing key, rate
  limit, bad JSON), and the backup string assertions matched substrings so common
  (`"rate"` matches "mode**rate**"; `"sorry"` matches the generic failure message) that
  the suite would have passed on a completely broken system. The earlier "100% pass rate"
  claim was therefore true by construction, not evidence of safety. Judge failures now
  score 0 with `verdict: "ERROR"`, and assertions check real safety language.

### 12.7 Multi-Session Chat Persistence 💬 (Phase 5b)

- **Location:** `src/database.py` (SQLAlchemy ORM over SQLite), wired into `app.py`'s sidebar.
  Ported from the opim-5517 coursework's HW8 "Relational Persistence" module and extended for
  this project's multi-agent turns (decision D13).
- **The problem it solves:** chat history lived only in Streamlit's `session_state`, so a page
  reload erased the conversation. That made it impossible to compare two recovery scenarios, or
  to walk away and come back — and it made the demo feel like a toy.
- **Two tables, turn-per-row.** `chat_sessions` holds one row per conversation (`session_id`,
  auto-derived `title`, `created_at`/`updated_at`, client metadata); `chat_transcripts` holds
  one row per **turn** — question, answer, `route_used`, `route_confidence`, which specialists
  were consulted, their sources and binding restrictions, the execution trace, and token/cost
  metrics. One row = one complete exchange, which is exactly what the UI renders for an
  assistant message, so replay is "load this session's rows in `id` order."
- **Typed columns vs. JSON, deliberately split.** `route_used` and the token/cost columns are
  real columns because we aggregate over them (`GROUP BY route_used` for routing analytics,
  `SUM(cost_usd)` for spend). `agents_consulted`, `sources`, `constraints`, and
  `execution_trace` are JSON text because the UI reads them back whole and never filters inside
  them — normalizing four display payloads into child tables would buy nothing. The payoff:
  a reopened turn renders with the same badges, source lists, restriction checklist, and debug
  trace as a live one.
- **SQLite hardening (two pragmas set on every connection).** **WAL** journal mode, so a reader
  and a writer no longer lock the whole database — this is what lets two browser tabs hold two
  live chats. **`foreign_keys=ON`**, because SQLite ignores foreign keys unless asked, and an
  orphan transcript should be a loud `IntegrityError` rather than silent corruption.
- **UI, in the sidebar's Conversations block:** the active chat (title · turns · tokens ·
  accumulated Groq spend, which now survives a reload in a way §12.5's in-memory
  `BudgetOverrunGuard` cannot), **New chat**, a picker over the 25 most recently *active*
  conversations, an explicit **Open** button, and delete. Conversations title themselves from
  the first question, so the picker reads as topics rather than uuids.
- **Two design details worth mentioning in Q&A:** (1) a session row is created lazily on the
  first *saved* turn, so opening the page — or a second tab — never litters the sidebar with
  empty conversations; (2) the write happens *after* the answer is rendered and inside a
  `try`, so a database problem costs the history row and shows a sidebar warning, never the
  answer itself.
- **What is deliberately not persisted:** the CLIP-matched exercise images (§12.3). Replaying
  them would mean one image-embedding search per historical message on every Streamlit rerun,
  so reopened turns show a "ask again to regenerate visual guides" note instead.
- **Storage:** `data/chat_history.db`, gitignored (with its `-wal`/`-shm` sidecars). The
  `CHAT_DB_URL` environment variable overrides the path, which is how the tests get an isolated
  temp database.
- **Verification:** `tests/test_database.py` — 14 tests that need no API key (JSON metadata
  round-trip, orphan-transcript rejection, title back-fill and truncation, `updated_at` bump,
  recent-activity ordering, two-session isolation, stats aggregation, rename, delete-cascade,
  WAL/FK pragmas). The five UI flows were driven headlessly through `streamlit.testing.v1.AppTest`
  — first render, two-turn save, New-chat isolation, reopen from a fresh browser session, and
  delete — 42 checks, zero exceptions.

