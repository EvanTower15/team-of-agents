# Class Preview Presentation — Plan (10 minutes: 5 slides + 5 demo)

> **What this is:** the working plan for our informal in-class preview of the Recovery Team
> project — *not* the final formal presentation. Goal is to give the class a flavor of what we
> built, hit the major functionality, and make the "why not just ask ChatGPT?" case explicitly.
>
> **Audience:** graduate-level generative AI class. They already know what RAG and an LLM are.
> Do not spend time defining embeddings; spend it on the architecture decisions and what they buy.
>
> **Format decisions already made:**
> - Slideshow emphasis: **architecture + why it works** (not a product pitch, not a business case)
> - Demo: **live Streamlit app** in the browser
> - Deep-dive features: **safety architecture** and **unit economics + evaluation**. GraphRAG,
>   CLIP visual search, and the security guardrails get one-line mentions only.
> - Speaker split: **by layer** — Speaker 1 problem/product, Speaker 2 architecture/differentiation,
>   Speaker 3 live demo.
>
> **How to use this file:** [Part 1](#part-1--slideshow-brief) is written to be pasted whole into
> a deck-building agent — it is self-contained and assumes no repo access. [Part 2](#part-2--live-demo-script)
> is for us. [Part 3](#part-3--qa-prep) is the honest-limitations cheat sheet.
>
> Sources: [Capabilities_Overview.md](Capabilities_Overview.md), [PROJECT_PLAN.md](PROJECT_PLAN.md),
> [README.md](README.md), and the live code in [src/](src/) and [app.py](app.py).

---

# PART 1 — SLIDESHOW BRIEF

> **↓↓↓ PASTE FROM HERE TO THE "END OF SLIDESHOW BRIEF" MARKER INTO THE DECK AGENT ↓↓↓**

## Deck-level instructions

Build a **9-slide PowerPoint** for a **5-minute** informal preview talk to a graduate-level
generative-AI class. Three presenters share it; speaker assignments are marked per slide.

**Tone and design constraints:**

- Technical peer audience. Assume they know RAG, embeddings, vector search, and agents. Never
  define those terms on a slide.
- **Visual-forward, low text.** Max ~6 short lines of body text per slide. The presenter carries
  the argument; the slide carries the diagram or the number.
- No animations beyond simple builds. No stock photos of doctors or gyms.
- Consistent specialist iconography throughout — 🦴 Orthopedic Surgeon, 🩺 Physical Therapist,
  🏋️ Gym Trainer, 🥗 Sports Nutritionist. Use the same four colors for these four agents on
  every slide they appear on.
- Monospace font for anything that is real system output (traces, routes, filenames).
- Slide numbers on. A one-line footer with the project name is fine.
- This is a **preview**, not the final defense. It should feel confident and fast, not exhaustive.

**The single argument the deck must land:** *a general-purpose LLM cannot credibly be four experts
at once, because its "personas" are stylistic rather than epistemic; four narrow agents, each
physically restricted to its own vetted corpus and chained in a fixed clinical-priority order, can.*

---

### Slide 1 — Title / hook

**Speaker:** 1 · **Time:** 20s

- **Title:** Recovery Team — a care team of four RAG agents
- **Subtitle:** One chat box. Four specialists. Nothing invented.
- Team names: Evan, Ben, James · OPIM 5517
- Small standing disclaimer line: *Educational support tool — not a substitute for a licensed clinician.*

**Visual:** the four specialist icons in a row, converging with arrows into a single chat bubble.

**Speaker note:** "Someone recovering from knee surgery has questions for four different
professionals and access to maybe one of them. We built the other three."

---

### Slide 2 — The problem

**Speaker:** 1 · **Time:** 40s

Frame it as one patient with four questions that belong to four different experts:

- *"Can I put weight on it yet?"* → surgeon
- *"Is this pain normal or a warning sign?"* → physical therapist
- *"How do I get back to lifting?"* → gym trainer
- *"What should I eat to heal faster?"* → nutritionist

Then the three failure modes of asking one general model all four:

1. **Hallucination** — it will produce a confident post-op timeline it has no source for.
2. **Instruction drift** — a constraint stated in turn 2 quietly stops binding by turn 6.
3. **Fake pluralism** — "act as a surgeon, a PT, and a trainer" is one model doing four voices
   from one undifferentiated pool of knowledge. The disagreement between experts — which is the
   clinically important part — never actually happens.

**Visual:** one patient icon, four question bubbles, four expert icons; a single grey "LLM" box
awkwardly straddling all four.

**Speaker note:** Land failure mode 3 hardest — it sets up the whole architecture.

---

### Slide 3 — What we built

**Speaker:** 1 → hand off to 2 · **Time:** 40s

- **Four specialist agents**, each with its **own** curated corpus and its **own** vector-store
  collection: 🦴 surgeon · 🩺 physical therapist · 🏋️ gym trainer · 🥗 sports nutritionist
- **79 vetted public-domain documents** — NIH, MedlinePlus, CDC, NHS, HHS. Every file carries a
  title/source/license/fetch-date header, committed to git.
- **A router** picks who should answer. **A LangGraph orchestrator** chains them. **A synthesizer**
  merges their drafts into one "care team" answer with citations.
- Stack: Groq `gpt-oss-120b` / `gpt-oss-20b` · local MiniLM embeddings (free, offline) ·
  ChromaDB · LangGraph · Streamlit · SQLite

**Visual:** four labeled corpus stacks feeding four agent icons — emphasize four *separate* stacks,
no shared pool.

---

### Slide 4 — Architecture (the centerpiece)

**Speaker:** 2 · **Time:** 60s — this is the longest slide, give it room

Reproduce this flow as a clean diagram:

```
                            user question
                                  │
                                  ▼
                          ┌──────────────┐
                          │    ROUTER    │
                          └──────┬───────┘
   ┌──────────┬────────────┬─────┴──────┬──────────┬──────────┬─────────┐
   ▼          ▼            ▼            ▼          ▼          ▼         ▼
 PT_ONLY  TRAINER_ONLY  SURGEON  NUTRITION_ONLY   TEAM     RED_FLAG   CLARIFY
   │          │            │            │          │          │         │
   ▼          ▼            ▼            ▼          ▼          ▼         ▼
 🩺 PT     🏋️ Trainer   🦴 Surgeon   🥗 Nutrition  🦴→🩺→🏋️→🥗  canned    one
(pt_docs) (trainer_    (surgeon_    (nutrition_  each passing  safety   follow-up
           docs)         docs)         kb)       constraints   response  question
                                                    downward   (NO LLM)
   └──────────┴────────────┴────────────┴──────────┘
                          ▼
              SYNTHESIZE — attribute each specialist, keep every
              [source: file] citation, resolve conflicts by rule
                          ▼
              final answer + citations + code-appended disclaimer
                          ▼
              saved as one transcript row → reopenable later
```

Three call-outs to place on the diagram:

- **Silos:** the trainer *cannot* retrieve surgeon documents. Enforced by separate collections,
  not by a prompt.
- **Order:** on TEAM the chain is **most-restrictive-first** — surgeon → PT → trainer → nutritionist.
- **RED_FLAG bypasses the model entirely.** That branch never touches an LLM.

**Speaker note:** "Every box is a node in a LangGraph state machine, so we get a guaranteed
termination path and a printable execution trace of exactly which specialist ran, in what order."

---

### Slide 5 — The mechanism: constraint handoff

**Speaker:** 2 · **Time:** 50s

This is the slide that proves it is a *team* and not four chatbots in a trench coat.

- Each specialist's draft is passed into the next specialist's prompt as **binding restrictions**,
  not as suggestions.
- An extra LLM call pulls a **structured constraint list** out of each draft —
  `{body_part, restriction, duration}` — so the downstream agent doesn't have to parse restrictions
  out of prose and hope it caught them all.
- **Conflict priority is coded, not negotiated:** surgeon wins on post-op / hardware / weight-bearing;
  PT wins on everything else safety-related.

**Real observed output** (put this on the slide verbatim, in monospace — it is our best evidence):

```
consult_surgeon:   6 sources
consult_pt:        5 sources, with surgeon draft as peer_context
consult_trainer:   4 sources, with 2 upstream drafts as peer_context
synthesize_team_answer: merged 3 drafts
```

> …and the synthesized answer said, unprompted, that *"your surgeon's guidance on post-op
> precautions takes precedence."*

**Speaker note:** "In a verified run, the trainer received a PT restriction of no loaded knee flexion
past 90° and no impact for four weeks — and programmed cycling warm-ups, hip thrusts, and seated
calf raises around it. It didn't just acknowledge the constraint, it re-planned under it."

---

### Slide 6 — Safety, as a stack

**Speaker:** 2 · **Time:** 45s

Present as **seven layers**, each catching what the layer above cannot. Render as a stacked
pyramid or a numbered vertical stack.

| # | Layer | Mechanism |
|---|---|---|
| 1 | Emergency detection | Deterministic red-flag regex, checked **before any AI involvement** — canned urgent-care response |
| 2 | Expertise silos | Each agent can retrieve only from its own collection |
| 3 | Grounding rule | "Answer ONLY from provided context" baked into the shared base class — a persona cannot omit it |
| 4 | Persona deference | PT never diagnoses · trainer never assesses pain · nutritionist never programs |
| 5 | Constraint ordering | Most-restrictive-first chain; every upstream draft binds everything below it |
| 6 | Fixed disclaimer | Appended **by Python**, not by the model |
| 7 | Graceful failure | Agents never raise; worst case is an apology with fix-it steps |

**The two sentences that matter:**

- Layer 1's red-flag list is the **only** regex left in the router. Everything else is an LLM
  classifier — but a safety gate has to behave identically every single time, and a model can't
  promise that.
- Layers 1 and 6 are Python constants. An LLM cannot forget them, rephrase them, or be talked out
  of them.

**One-line mention only (do not give these their own slides):** prompt-injection / jailbreak / PII
scanners, GraphRAG multi-hop clinical reasoning over a Kùzu property graph, and CLIP multimodal
matching of exercise diagrams to the patient's question.

---

### Slide 7 — Why not just ask ChatGPT? ⭐

**Speaker:** 2 · **Time:** 60s — **the most important slide in the deck**

Format as a two-column comparison: **General assistant** vs **Recovery Team**.

| | General assistant | Recovery Team |
|---|---|---|
| **Knowledge** | Parametric memory. You cannot audit what it drew on. | Every claim retrieved from a named, versioned, licensed document. Citations are file-level. |
| **Not knowing** | Almost never says "I don't have material on that." | Verified behavior: the trainer, asked about protein, answers *"I don't have material on nutrition specifics"* rather than inventing a number. |
| **Roles** | Personas are stylistic. One model, one knowledge pool, four voices. | Boundaries are physical — the trainer *cannot see* surgeon documents. Expertise is enforced by retrieval scope, not by a prompt promise. |
| **Constraints** | No guarantee the training advice was generated *subject to* the clinical restriction. | Fixed execution order + structured binding constraints + a coded conflict-priority rule. |
| **Safety** | Model behavior: usually good, statistically variable, jailbreakable. | Deterministic pre-model short-circuit. Identical every run, at zero token cost. |
| **Auditability** | Black box. | Full execution trace: who ran, in what order, from which files, at what token cost. |
| **Economics** | Per-seat subscription, opaque per-query cost. | Metered per query, hard-capped, and the corpus is ours to swap. |

**The closing line — say it out loud:**

> "GPT-5 almost certainly *knows* more orthopedics than our 79 documents. That's not the claim.
> The claim is that it can't show you where an answer came from, can't be prevented from answering
> outside its lane, and can't guarantee the trainer heard the surgeon. We can do all three — and
> those are exactly the properties you need before anyone would let a system like this near a
> patient."

---

### Slide 8 — Economics + evaluation

**Speaker:** 2 · **Time:** 40s

Two halves, both as **big numbers**, not paragraphs.

**Unit economics** (live in the app's sidebar — the demo will show this):

- Groq `gpt-oss-120b` metered per call from the provider's own token counts:
  **$0.15 / 1M input**, **$0.60 / 1M output** (`gpt-oss-20b`: $0.075 / $0.30)
- **Measured, not estimated:** a single-specialist question is **11,564 tokens across 6
  calls** ($0.0024); a TEAM question **38,141 tokens across 14** (~$0.009). Against $0.12
  per question that is **~98% gross margin**
- **The constraint is supply, not cost.** Two free-tier caps: **8,000 tok/min** makes one
  TEAM question eat **4.8 minutes** of the account's budget (the stall you'll see live),
  and **200,000 tok/day** allows only **~5 TEAM questions a day → 157/month**. One
  subscriber is promised 250, so the free tier hosts **zero paying customers**
- Embeddings run **locally and free** — zero API cost, zero rate limits, works offline
- Hard budget guard: **$0.05 max per query**, **$1.00 max per session** — a runaway agent loop is
  capped by code
- vs. **$150–$350/hr** for human clinical consultation → **100x+** cost reduction per consult

**Evaluation:**

- 15-question routing battery, run live: **13/15 correct**
- **LLM-as-a-judge** scoring of outputs on Clinical Safety (1–5), Constraint Adherence (1–5), and
  Brevity (1–5)
- High-risk patient stress tests — premature 225 lb squatting, skipping PT, 500 cal/day starvation
  diets, infection red flags — **100% pass**
- Full offline test suite, no API key required for most of it

**Include the honest line on the slide:** *2 known routing gaps, unfixed, documented.* It costs us
nothing with this audience and buys a lot of credibility. Details are in the presenter's notes.

---

### Slide 9 — Demo handoff

**Speaker:** 2 → 3 · **Time:** 15s

Four things to tell the audience to watch for, as a checklist they can hold in their head:

1. **The route chip and the badges** — which specialists the system chose, and why
2. **The trace** — surgeon → PT → trainer, each one reading the last one's restrictions
3. **The red-flag question** — answered instantly, with no model call at all
4. **The cost line** — what a full four-specialist consult actually costs

**Visual:** a screenshot of the app with those four regions circled and numbered.

> **↑↑↑ END OF SLIDESHOW BRIEF ↑↑↑**

---

# PART 2 — LIVE DEMO SCRIPT

**Driver:** Speaker 3 · **Total:** 5:00 · **Mode:** live Streamlit app in a browser

## Pre-flight (do this *before* class, not on the clock)

- [ ] `.venv` activated; `GROQ_API_KEY` present in `.env` and confirmed working
- [ ] All four collections built — `python -m src.ingest --agent pt|trainer|surgeon|nutrition`
- [ ] **Warm-up run:** ask one throwaway question and let it complete. The first question of a
      session pays for loading MiniLM and, if a visual match fires, the CLIP model. Do not let the
      class watch that.
- [ ] **Pre-seed one saved conversation** so the persistence beat has something to reopen instantly
- [ ] Sidebar toggle **"Show routing debug trace" = ON** — the trace is half the point of the demo
- [ ] Browser zoom ~125–150%, back-row legible; pick light or dark and stick to it
- [ ] Second terminal tab open at the repo root, ready for the CLI fallback
- [ ] Phone hotspot ready — Groq is a network call and campus wifi is campus wifi
- [ ] Close Slack/mail notifications

## Timing reality check — read this before you rehearse

A **TEAM** question fires roughly **7–8 sequential Groq calls** (router → 3 specialists → their
constraint extractions → synthesis). Expect **20–40 seconds of spinner**. That is a third of your
demo time.

**Turn the latency into content.** Type the question, press Enter, and *keep talking* through the
spinner — the beat-2 narration below is written to be delivered over the wait, and it is
architecture recap the audience wants anyway. Do not stand in silence watching a spinner, and do
not apologize for it.

---

## Beat 1 — Orientation (0:00 – 0:40)

Show the app without typing anything yet.

- One chat box. Sidebar: **Conversations** (active chat with turn count, token count, and
  accumulated spend), **New chat**, a picker over past conversations, and one **rebuild** button
  per knowledge base.
- Open the **💰 Business Unit Economics & Strategy** expander for ~5 seconds. This is your entire
  unit-economics demo — token pricing, local-compute savings, the human-consult comparison, and the
  budget guard, all visible at once. Say one sentence, close it, move on.

> **Say:** "Everything the class saw on the architecture slide is behind this one text box."

---

## Beat 2 — The flagship: constraint handoff (0:40 – 2:30)

**Type exactly:**

```
I'm 8 weeks post-meniscus surgery - how do I get back into lifting safely?
```

**Press Enter, then narrate over the spinner** (~25s of material):

> "Right now the router is classifying this — it's an LLM call, and it's deciding not just *which*
> specialist but *which combination*. It came back TEAM with three specialists flagged. So the
> surgeon is going first, because post-op restrictions have to bound everything downstream. Its
> draft is being turned into a structured constraint list. That list is now being prepended to the
> PT's prompt as *binding restrictions*. The PT is writing under the surgeon's constraints. Then
> the trainer gets **both** upstream drafts, and finally a synthesizer merges all three into one
> voice."

**When it lands, point at these in order — this is the part to rehearse:**

1. **Route chip:** `TEAM` with its confidence
2. **Three badges:** 🦴 🩺 🏋️ — the system chose the roster
3. In the answer body, find and **read aloud** the language deferring to the surgeon
   ("…your surgeon's guidance on post-op precautions takes precedence"). Say plainly: *that
   sentence came out of the model, not out of a template.*
4. **Sources expander** — per-agent file lists. Three different specialists, three different
   document sets, no overlap.
5. **Binding restrictions expander** — the structured constraints, rendered as a checklist
6. **🪙 token/cost caption** — pause on it. "That's what a four-specialist consult costs."
7. **Routing trace (debug)** — the execution trace, live, matching slide 5 exactly

> **Say:** "That trace is the difference between an agent system and a prompt. I can prove the
> trainer read the surgeon."

---

## Beat 3 — Deterministic safety (2:30 – 3:10)

**Type exactly:**

```
My calf is swollen, hot, and I have sharp pain when I stand.
```

It returns **instantly**. Let the speed itself make the point before you explain it.

- Route chip: `RED_FLAG`, ~0.97
- **No badges** — no specialist was consulted
- The trace is **two lines**. No retrieval, no LLM, no token cost.

> **Say:** "That's a possible DVT. It never reached a language model. A regex caught it and a fixed
> Python string answered it. Nothing about that path can vary between runs, and nothing in a prompt
> can talk it out of firing — which is exactly what you want from the one branch where being wrong
> is dangerous."

---

## Beat 4 — Honest ignorance (3:10 – 3:50)

The anti-hallucination beat: get the system to admit it doesn't know something.

**In the app, type:**

```
What's the best swimming workout for my recovery?
```

Swimming is genuinely absent from all four corpora, so the answer should be an honest
"I don't have material on that" rather than an invented protocol.

> ⚠️ **Trap — do not use the protein example in the app.** "How much protein should I eat?" *used*
> to produce the trainer's famous "I don't have material on nutrition specifics" refusal, but we
> shipped a nutritionist agent since — the router now correctly sends it to 🥗 and it gets a real
> answer. That's an upgrade, not a bug, but it kills the demo beat.

**Reliable variant if the app's routing wanders** — second terminal tab, single agent, no router:

```
python -m src.agents.gym_trainer "How much protein should I eat to build muscle?"
```

This is verified behavior and is worth showing anyway, because it isolates the mechanism: this is
the *trainer specifically*, refusing to leave its lane, with no router or orchestrator involved.

> **Say:** "This is the behavior a general assistant essentially never gives you. The refusal isn't
> politeness — it's structural. There is nothing about swimming in that agent's collection, and the
> base-class prompt forbids answering from anything else."

---

## Beat 5 — It's a product, not a notebook (3:50 – 4:40)

- **Reload the browser (F5)** in front of the class. The chat is gone from the screen.
- Reopen the conversation from the sidebar picker → **Open**.
- Everything comes back: the answer, the badges, the per-agent sources, the binding restrictions,
  the trace, the accumulated spend.
- Click **New chat** and note that you now have two independent recovery scenarios side by side.

> **Say:** "Every turn is a row in SQLite — question, answer, route, specialists, sources,
> restrictions, tokens, cost. Route and cost are typed columns specifically so we can aggregate:
> what does routing actually look like across a hundred users, and what did it cost."

*(Note: reopened turns show a small "ask again to regenerate visual guides" line — the CLIP image
matches are deliberately not persisted. If anyone asks, that's a cost decision: replaying them
would mean an image-embedding search per historical message on every rerun.)*

---

## Beat 6 — Close (4:40 – 5:00)

> **Say:** "Four agents, four siloed corpora, a fixed clinical priority order, a safety branch that
> never touches a model, and a full audit trail for every answer. You can ask ChatGPT about your
> meniscus. You can't ask it to prove the trainer heard the surgeon."

---

## Contingency

| If… | Then… |
|---|---|
| Groq is slow or 503s | Keep narrating; if it fails outright, switch to the second terminal and run `python -m src.orchestrator "…"`. Same trace, less chrome. |
| Network dies completely | Beat 3 (red flag) still works — it never calls out. Show it, then pivot to the pre-seeded saved conversation from beat 5, which renders entirely from SQLite. **Both beats are fully offline.** |
| Running long | Cut beat 4 (honest ignorance) — slide 7 already makes that argument. Cut the "New chat" half of beat 5 second. |
| Running short | Open the sidebar's per-knowledge-base rebuild buttons, or ask a `NUTRITION_ONLY` question to show a single-specialist route for contrast with TEAM. |
| Someone asks for a visual | If the 🖼️ **Visual Guides & Diagrams** expander appeared on a fresh answer, open it — that's the CLIP multimodal search finding an exercise diagram by semantic match to the question. |

---

# PART 3 — Q&A PREP

Grad classes ask sharp questions. Answer these plainly; every one of them is already documented,
and being straight about them is more impressive than dodging.

**"Isn't 79 documents nothing compared to what GPT-5 knows?"**
Correct, and that's not the claim. We're trading knowledge breadth for provenance, enforced scope
boundaries, deterministic safety, and auditability. Also worth saying plainly: our corpus is
public-domain *patient-education* material, not clinical protocols — which is exactly why the
disclaimer exists and why the product is framed as educational support.

**"Does it remember the conversation?"**
No — and we're precise about this. Conversations *persist* and reopen, but each question is still
answered from scratch; the agents never receive prior turns. "What about my knee?" as a follow-up
will not resolve. What Phase 5b changed is what's *stored*, not what's *reasoned over*. Multi-turn
context is the next real piece of work.

**"How good is the routing, really?"**
13/15 on our battery, run live. Two known unfixed gaps: (1) "What's the best gym?" resolves to
`TRAINER_ONLY` instead of asking for clarification — the LLM is more willing to answer an
underspecified question than the old regex router was; (2) a question with explicit
surgeon language ("my surgeon cleared me for full weight-bearing 6 weeks after ACL reconstruction")
under-chains to PT+trainer and misses the surgeon. Both are prompt-level fixes — few-shot examples —
not structural bugs.

**"Why is the safety check a regex when everything else is an LLM?"**
Deliberate. We actually *replaced* a regex router with an LLM classifier because the hand-tuned
cue lists were brittle — a real bug: a pattern for "stitches out" didn't match "when do my stitches
come out." But a safety gate has to behave identically every time, and an LLM can't promise that.
So the regex went from being *the router* to being *the floor*.

**"What's your retrieval strategy?"**
Naive top-k cosine similarity, k=6, on 384-dim MiniLM embeddings. No BM25 hybrid, no reranking, no
metadata filtering. Fine at our corpus size; it's on the list.

**"Is it secure? What about prompt injection?"**
There's a scanner module for prompt-injection, jailbreak, SQL-injection, and PII redaction, with a
red-team test suite behind it. Be accurate about the wiring: it's currently wired into the
**CLI** path (`src/cli.py`), not into the Streamlit app. Say that if asked.

**"You're storing health information."**
Yes, in plaintext SQLite on the local machine. Fine for a single-user local demo; it would need
real thought before any hosted deployment. We know.

**"What happens if a knowledge base is missing?"**
Tested by deleting the entire `chroma_db/` directory: polite fallback answer with the exact rebuild
command, no stack trace. Agents capture errors into a return field instead of raising, so the graph
treats a broken agent as a routing condition. On a TEAM route, if the PT fails the trainer still
runs — one broken knowledge base degrades the answer instead of killing it.

**"Why not fine-tune?"**
Corpus changes shouldn't require retraining, we need file-level citation for every claim, and the
whole system runs on a free API tier plus local embeddings. Swap the `data/` folder and you have a
different vertical.

---

## Appendix — fact sheet (numbers we can defend)

| Fact | Value |
|---|---|
| Specialist agents | 4 — surgeon, PT, trainer, nutritionist |
| Corpus | 79 documents across 4 siloed collections (PT 29, trainer 22, surgeon 18, nutrition 10) |
| Chunk counts | PT 203 · trainer 536 · surgeon 121 · (nutrition not recorded in the plan) |
| Chunking | ~1,000 chars, 150-char overlap |
| Embeddings | `all-MiniLM-L6-v2`, 384-dim, local, CPU, free |
| Retrieval | top-k cosine, k=6, per-agent collection |
| LLM | Groq `openai/gpt-oss-120b` (temp 0.2) · `openai/gpt-oss-20b` (temp 0, `reasoning_effort=low`) |
| Token pricing | $0.15/1M in · $0.60/1M out (120b) · $0.075 / $0.30 (20b) — verified 2026-08-08 |
| Budget guard | $0.05/query · $1.00/session |
| Human comparison | $150–$350/hr clinical consult → 100x+ reduction |
| Routing battery | 13/15 correct, run live |
| Red-flag confidence | 0.97, regex, pre-model |
| TEAM chain order | surgeon → PT → trainer → nutritionist (most-restrictive-first) |
| Persistence | SQLAlchemy/SQLite, WAL + foreign keys, one row per turn |
| Test suite | 56 passing; 14 offline DB tests; 42 headless UI checks via `AppTest` |
| Licensing | US-government content public domain; NHS pages under Open Government Licence v3.0; provenance logged in `data/SOURCES.md` |

## Open items before we present

- [ ] Assign Speaker 1 / 2 / 3 to Evan, Ben, James
- [ ] One full timed rehearsal — the demo is the part that overruns
- [ ] Confirm the swimming question in beat 4 actually produces an honest refusal in the app
      (verified for the PT agent standalone; not yet re-checked through the live router)
- [ ] Take the slide-9 annotated screenshot from a real run
- [ ] Whoever drives the demo: pre-seed a saved conversation the morning of
