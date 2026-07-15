# Capabilities Overview — How the Recovery Team Actually Works

> **Who this is for:** every teammate, and especially whoever builds the presentation.
> [PROJECT_PLAN.md](PROJECT_PLAN.md) tracks *what* was built, in what order, and what's next.
> This document explains *how* each part works and *why* it was designed that way, in enough
> depth that you can confidently explain (and demo) the parts you didn't personally build.
> Everything below reflects the system as of Phase 4c (2026-07-14): three specialists live
> and orchestrated end-to-end, with structured constraint handoff between them, and the
> router is now LLM-primary rather than regex-driven. Update this document when a phase
> changes how something works.

---

## 1. The product in one paragraph

A user recovering from an injury asks one chat interface a question. Behind it, a **router**
decides which specialist(s) should answer — an **Orthopedic Surgeon agent**, a **Physical
Therapist agent**, a **Gym Trainer agent**, or a chain of them. Each specialist answers
**only from its own curated library of vetted documents** (this is Retrieval-Augmented
Generation — RAG), and a **synthesizer** merges their drafts into one coherent "care team"
response with source citations and a standing disclaimer. Questions that look like medical
emergencies never reach an AI model at all — they get a fixed safety response. The core
thesis: one general-purpose LLM hallucinates and can't credibly be three experts at once;
narrow agents, each grounded in its own knowledge base and coordinated by an orchestrator,
can.

```
                            ┌──────────────────────────┐
        user question ────► │   router (src/router.py) │
                            └────────────┬─────────────┘
   ┌───────────┬────────────┬────────────┼────────────┬───────────────┐
   ▼           ▼            ▼            ▼            ▼               ▼
PT_ONLY   TRAINER_ONLY   SURGEON        TEAM       RED_FLAG        CLARIFY
   │           │            │      surgeon → PT →      │              │
   ▼           ▼            ▼      trainer, whichever  ▼              ▼
PT agent  Trainer agent  Surgeon   cues fired,      canned safety  one focused
(pt_docs) (trainer_docs) agent     each passing      response      follow-up ?
   │           │       (surgeon_docs) structured    (no LLM ever)     │
   │           │            │      constraints down     │             │
   └───────────┴─────┬──────┴──────────┘                │             │
                      ▼                                 │             │
           synthesize_team_answer                        │             │
           (attributes each specialist consulted;        │             │
            surgeon wins post-op/hardware conflicts,      │             │
            PT wins everything else safety-related)      │             │
                      │                                  │             │
                      ▼                                  ▼             ▼
               final answer + [source: ...] citations + disclaimer
```

---

## 2. A question's journey (real, observed run)

The fastest way to understand the system is to follow one question through it. This is the
actual execution trace from Phase 4 testing, not a mock-up:

> **Note (Phase 4c):** this trace is from before the router redesign — at the time, routing
> was regex/rules-based, hence `method: rules` and "no LLM call" below. Since Phase 4c the
> router is LLM-primary (§6), so re-running this exact question today would show
> `method: llm` and cost one Groq call for the routing step itself; the rest of the flow
> (PT-first, trainer gets PT's draft as `peer_context`, synthesis) is unchanged. Kept as-is
> for the historical record rather than rewritten.

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

| | Physical Therapist | Gym Trainer | Orthopedic Surgeon |
|---|---|---|---|
| Folder → collection | `data/pt/` → `pt_docs` | `data/trainer/` → `trainer_docs` | `data/surgeon/` → `surgeon_docs` |
| Size | 29 documents (25 txt + 4 PDF), 203 chunks | 22 documents (19 txt + 3 PDF), 536 chunks | 18 documents (all txt) |
| Anchor documents | NIA "Exercise & Physical Activity for Older Adults" guide (34-page PDF), 3 CDC STEADI fall-prevention brochures | HHS "Physical Activity Guidelines for Americans, 2nd ed." (118-page PDF) | MedlinePlus post-op/discharge instruction set (wound care, crutches, ACL/rotator-cuff/knee-arthroscopy discharge) |
| Text sources | MedlinePlus injury topics, NIAMS fact sheets, NINDS pain page, NHS rehab pages | CDC physical-activity-basics, NIA get-started guides, MedlinePlus, 8 practical NHS exercise pages (strength/balance/flexibility/sitting/Couch-to-5K) | MedlinePlus encyclopedia/patient-instructions pages, NIAMS hip-replacement page, 3 NHS post-surgery recovery pages |

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

### The three personas

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

Each agent is independently testable from the command line, which is the fastest demo of a
single specialist:

```
python -m src.agents.physical_therapist "My knee aches after squats - normal?"
python -m src.agents.gym_trainer "Give me a simple 3-day beginner strength program."
python -m src.agents.orthopedic_surgeon "How long until I can put weight on my knee after knee arthroscopy?"
```

---

## 6. Layer 4 — The router (`src/router.py`)

The router answers one question: *which specialist(s), if any, should see this?* It returns
a `RouteDecision` — label, confidence (0–1), a human-readable reason, which method decided
(`rules` or `llm`), and `scores` — `{"pt", "trainer", "surgeon"}`, each 0 or 1, marking which
specialist(s) apply. This is what the orchestrator reads to decide who to chain on TEAM.

**Redesigned in Phase 4c to be LLM-primary** (decision D11) — this supersedes the
Phase 4/4b design, which used a weighted regex keyword scorer (rehab words for the PT,
training words for the trainer, post-op words for the surgeon) and only fell back to an LLM
when the rules were unsure. That regex layer kept needing hand-patches as phrasing varied —
the bug that triggered the redesign: a cue meant to catch "stitches out" didn't match the
equally natural "when do my stitches come out." Rather than keep patching individual
patterns, the weighted scorer was deleted outright.

It now works in two stages:

**Stage 1 — RED_FLAG regexes, checked before everything, unchanged.** A fixed list of
urgent-care patterns: severe/sharp pain, numbness or tingling, can't bear weight, visible
deformity, fever, chest pain, a hot or swollen calf (the DVT signature), "felt a pop", a
joint that buckles or gives way, wound/incision problems. Any match ends routing immediately
at confidence 0.97. This is the **only** regex left in the router, deliberately (decision
D5): a safety gate must behave identically every single time, which an LLM can't guarantee.

**Stage 2 — one Groq/Llama call decides everything else.** The prompt asks the model for two
things at once: a single overall label (`PT_ONLY` / `TRAINER_ONLY` / `SURGEON` / `TEAM` /
`CLARIFY`) and which specialist(s) are relevant (any subset of `pt`, `trainer`, `surgeon`).
The response is parsed by a deliberately tolerant parser (scans the whole response for a
valid label and an in-range confidence, survives messy formatting) into the same `scores`
shape the orchestrator's TEAM chain already consumed in Phase 4b — so `orchestrator.py`
needed **zero changes** for this redesign, only `router.py` did. A model that says `TEAM`
but names fewer than 2 specialists is treated as inconsistent and defaults to consulting all
three, rather than silently under-chaining. If the model's confidence is below 0.50, or the
LLM call fails entirely (no key, network error), the route collapses to CLARIFY — same
"never guess, never crash" posture as the rest of the codebase.

**Trade-off, explicit:** routing is no longer free. Every non-RED_FLAG question now costs a
Groq call and takes real latency, instead of resolving instantly from local keyword weights.
More importantly, there is now **no rules fallback** if `GROQ_API_KEY` isn't set — verified
live: `classify()` returns CLARIFY for every non-RED_FLAG question without a key, since
there's nothing left to resolve it locally. This makes each teammate's own Groq key a harder
prerequisite than it was through Phase 4b.

**What's actually been verified vs. still pending:** without a live Groq key available in
the dev environment, the parser (`_parse_llm_response`) was unit-tested directly against
synthetic `LABEL | confidence | specialists | reason` strings — including malformed ones —
and confirmed to produce correct `scores`; `classify()` was confirmed to still resolve
RED_FLAG via regex and to degrade to CLARIFY (not crash) on an empty question or a missing
key. **Not yet verified:** actual routing accuracy against the §9 battery with a real key.
Whoever configures a key first should run:

```
python -m src.router "Is soreness two days after a workout normal or an injury?"
python -m src.router "My surgeon cleared me for full weight-bearing 6 weeks after ACL reconstruction - how do I safely get back into leg training?"
```

---

## 7. Layer 5 — The orchestrator (`src/orchestrator.py`)

The orchestrator is a **LangGraph state machine**. Mental model: a flowchart where each box
(node) is a Python function that reads a shared state dictionary and returns updates to it,
and the arrows (edges) can branch on the state's contents.

**The shared state (`TeamState`)** carries the question, the routing decision (including
`route_scores`, Phase 4b — the same `{"pt", "trainer", "surgeon"}` dict the router produced),
each specialist's `consult()` result and extracted constraints, the final answer,
per-specialist sources, and `execution_trace` — a list every node appends one line to, which
is how we can always show exactly which path a question took (the trace in §2 is this field,
verbatim).

**The nodes:**

| Node | What it does |
|---|---|
| `route_question` | Calls the router; writes label/confidence/reasoning/`route_scores` into state |
| `consult_surgeon` | `OrthopedicSurgeonAgent().consult(question)`, then `extract_constraints()` on its own draft (Phase 4b) |
| `consult_pt` | `PhysicalTherapistAgent().consult(question)`; **on TEAM, if the surgeon already ran, receives its structured constraints + draft as `peer_context`** |
| `consult_trainer` | Same for the trainer; **on TEAM, receives whichever upstream specialists ran (surgeon and/or PT), each as a constraints block + draft** |
| `synthesize_team_answer` | One LLM call that merges the usable drafts: attribute each specialist, keep citations, surface conflicts — surgeon wins on post-op/hardware/weight-bearing, PT wins otherwise (Phase 4b) — add nothing new. Single-agent routes also pass through here so every answer has a consistent voice |
| `safety_response` | Returns the fixed RED_FLAG text. No retrieval, no LLM — nothing in this node can fail or vary |
| `ask_clarification` | One focused follow-up question (LLM, with a canned fallback if the LLM is down) |
| `fallback_handler` | Terminal for dead ends: apologizes, says what went wrong, prints the rebuild commands (now including `--agent surgeon`) |

**Which specialists actually get consulted on TEAM (Phase 4b)** is decided by `route_scores`,
not a fixed pair: the conditional edges after `route_question`, `consult_surgeon`, and
`consult_pt` each check whether the *next* specialist's bucket scored above zero before
routing to it. A PT+trainer TEAM question (no surgeon cues) skips `consult_surgeon`
entirely — the chain is exactly as long as the question calls for, never padded with an
irrelevant specialist.

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
console.groq.com in `.env` — as of Phase 4c this is required even to get routing to work,
not just to get specialist answers):

```
pip install -r requirements.txt
python -m src.ingest --agent pt
python -m src.ingest --agent trainer
python -m src.ingest --agent surgeon
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

The full battery (12 original + 3 surgeon/three-way rows) is §9 of PROJECT_PLAN.md; the
Phase 4 results block has the original measured routing results (regex-era). **The battery
has not yet been re-run against the Phase 4c LLM-primary router with a real Groq key** — do
that before relying on these as current numbers.

---

## 10. Current limitations (know these before Q&A)

- **Single-turn.** No memory of the user or prior questions; each question stands alone
  (privacy-by-design for Phase A; personalization is a Phase B discussion).
- **Naive retrieval.** Top-k vector similarity only — no hybrid keyword search, reranking,
  or metadata filters.
- **Routing now costs an LLM call (Phase 4c).** Every non-RED_FLAG question is classified by
  Groq rather than free local keyword rules — this trades routing speed/cost/determinism for
  robustness to phrasing. **Without a Groq key configured, routing degrades to CLARIFY for
  everything** (verified) except RED_FLAG, which stays regex. RED_FLAG patterns can still
  false-positive (by design — err toward safety).
- **Router's real-world routing accuracy is unverified.** The Phase 4c redesign was tested
  structurally (parser unit tests, graph-topology monkeypatch tests) but not against live
  Groq responses — nobody has run the §9 battery for real since the redesign landed.
- **No web UI yet** (Phase 5) and **no frozen evaluation table yet** (Phase 6).
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
