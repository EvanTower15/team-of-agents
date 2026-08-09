# Final Presentation — Plan (15 slides / ~14:00 + 6:00 live demo)

> **What this is:** the working plan for the **final** presentation of the Recovery Team project
> to a graduate-level generative AI class. Supersedes [PRESENTATION_PREVIEW.md](PRESENTATION_PREVIEW.md),
> which was the informal 10-minute in-class preview.
>
> **Budget:** 12–15 min slideshow (this plan targets **14:00**) + 5–7 min live Streamlit demo
> (this plan targets **6:00**).
>
> **Audience:** graduate generative-AI students. They know RAG, embeddings, vector search, and
> agent frameworks. Do not define them. Spend the time on architecture *decisions*, the evidence
> that they worked, and the differentiation argument.
>
> **How to use this file:**
> - [Part 0](#part-0--read-this-before-you-build-anything) — corrections and prep that must happen first.
> - [Part 1](#part-1--slideshow-plan) — the slide-by-slide plan. Self-contained; paste whole into the deck agent.
> - [Part 2](#part-2--live-demo-script) — the demo script, for us.
> - [Part 3](#part-3--qa-prep) — honest-limitations cheat sheet.
> - [Part 4](#part-4--fact-sheet) — every number, verified against the repo.
>
> **⚠️ REVISED 2026-08-07/08.** The system changed substantially while this plan was being written:
> a model migration, an LM planner, specialist tool calling, conversation memory, and a back-channel
> between agents all landed — and then **Evan merged PR #10 (multi-session chat persistence, +1,561
> lines) on top.** **Roughly a third of this document's previous claims went stale inside a day.**
> Everything below is re-verified against `main` at the revision, and changed items are marked ✱.
> Read Part 0 in full before building anything.
>
> **Note the decision log now runs to D31, not D30** — Evan renumbered persistence when he
> reconciled his branch against the planner/tools merge.

---

# PART 0 — Read this before you build anything

## 0.1 ⚠️ The three things that will embarrass you if nobody checks them

These are live, verified problems as of the revision. None is hard to fix; all are easy to get
caught on.

**(a) The Groq free tier has a 200,000-token daily cap, and we hit it today.** Verified from a real
429: `Limit 200000, Used 198872`. A four-specialist TEAM question now costs **12–18 Groq calls**
(see 0.3), so the daily budget is roughly **a dozen full team consults**. If three people rehearse
the demo the morning of, *the presentation itself may 429 on stage.*
→ **Action:** do not rehearse against the live API on presentation day. Rehearse the day before,
and confirm remaining budget at console.groq.com before you walk in. Consider a paid Dev tier
upgrade for the presentation window — it is the single cheapest risk reduction available.

**(b) Kùzu is not installed** — `import kuzu` → `No module named 'kuzu'`. The orchestrator prints
`[graph_rag] KuzuDB unavailable, using in-memory fallback data` and runs on a hardcoded in-memory
dict. Slide 11 and the fact sheet previously described "a Kùzu property graph" as a shipped
capability. **On this machine it is a stub.**
→ **Action:** either `pip install kuzu` and verify the real graph loads, or describe it accurately
on the slide. Do not say "Kùzu property graph" while it is falling back.

**(c) ✅ RESOLVED — but it changed the corpus numbers.** `pt_docs` had gone missing entirely;
Chroma held only 3 of 4 collections. The cause was a real bug, now fixed: `DoclingLoader` can fail
at *conversion* time (on a machine with no C++ compiler it raises `InvalidCxxCompiler: Compiler: cl
is not found`), but `rag_core.load_folder_documents` only guarded the *import*. One unconvertible
PDF aborted the entire ingest and left the collection unbuilt.

**Rebuilt with the per-file fallback, and it came back 5x bigger: 203 → 1,050 chunks.** Four PDFs
had never made it in — the NIA 34-page older-adult exercise guide and three CDC STEADI documents,
which slide 6 cites as the PT corpus's *anchor sources*. Verified: all 40 files in `data/pt/` are
now represented in the collection, none missing.

*Be honest about the 5x if asked:* part of it is genuinely new material, and part is that the
PyPDF fallback is a coarser parser than Docling and produces more chunks from the same pages.
→ **Action:** confirm all four collections are present and non-empty the morning of. The PT corpus
is the one the flagship demo needs.

## 0.2 ✱ The model changed. Every "Llama-3.3-70B" in the old deck is wrong.

Groq retires `llama-3.3-70b-versatile` on **2026-08-16** — before or right around presentation day.
Migrated 2026-08-07 (D27):

| Job | Model |
|---|---|
| Specialists, synthesis, constraint extraction, peer-consult detection, follow-up resolution | `openai/gpt-oss-120b` |
| Routing, planning, compliance check | `openai/gpt-oss-20b` (`reasoning_effort="low"`) |
| User photo description only | Google `gemini-flash-latest` — the one non-Groq call ✱ |

Two things follow that the deck must reflect:

- **The token pricing on the old slide 13 ($0.59/$0.79 per 1M) was Llama-3.3-70B pricing.**
  ✱ **RESOLVED 2026-08-08 — verified against console.groq.com, use these:**
  `gpt-oss-120b` **$0.15/1M input, $0.60/1M output**; `gpt-oss-20b` **$0.075 / $0.30**.
  They now live in exactly one place in the code (`src/business/pricing.py`) and every cost
  figure in the app reads from it. The old numbers were still live in `unit_economics.py`
  until 2026-08-08 — every dollar the app displayed for nine days after the migration was a
  chars/4 token count priced at a retired model's rates (D32).
- **gpt-oss models emit reasoning tokens before content.** They cost more per call than the model
  they replaced. Anything setting `max_tokens` must leave headroom or `content` comes back empty.

**Why it's worth 15 seconds on stage:** we caught a vendor deprecation nine days early and migrated
without changing the architecture, because every model call goes through two factory functions in
`rag_core.py`. That is a real engineering point about seams, and it is cheap to make.

## 0.3 ✱ Cost per TEAM question roughly doubled, and the app's estimator is worse than before

The old plan said 7–9 Groq calls for a TEAM question. That is now low. Counting the actual call
sites for a four-specialist consult:

| Stage | Calls | Model |
|---|---|---|
| Follow-up resolution (only when history exists) ✱ | 0–1 | 120b |
| Router classification | 1 | 20b |
| **Planner — which specialists, in what order** ✱ | 1 | 20b |
| Specialist consults (4 × 1 base + up to 2 tool rounds) ✱ | 4–12 | 120b |
| Constraint extraction (surgeon, PT, nutritionist — **not** the trainer) | 3 | 120b |
| Peer-consult detection, + the back-channel consult if one fires ✱ | 1–2 | 120b |
| Synthesis | 1 | 120b |
| **Compliance check** ✱ | 1 | 20b |
| **Total** | **12–18** | |

*(A bug found during this revision and fixed: constraint extraction was running for the trainer too,
whose result is discarded — one wasted 120b call on every TEAM question that included the trainer.)*

**✱ MEASURED, no longer estimated.** `src/telemetry.py` now records Groq's own token counts for
every call. First real numbers, from a **single-specialist** question — the cheapest non-red-flag
route:

| Stage | Tokens | Latency |
|---|---|---|
| `consult:pt` | 3,643 | 3,655 ms |
| `synthesize` | 2,641 | 2,320 ms |
| `extract_constraints:pt` | 2,475 | 2,323 ms |
| `compliance_check` | 1,364 | 580 ms |
| `route` | 988 | 410 ms |
| `plan` | 453 | 213 ms |
| **Total** | **11,564** | **6 calls** |

The old chars/4 estimator logged a comparable question at **2,011** tokens — it understates by
**~5.7×** on the *cheapest* route. "Roughly an order of magnitude" was the right instinct; this is
the measurement.

**Two findings worth stage time:**

1. **Constraint extraction costs nearly as much as the consult it summarises** (2,475 vs 3,643).
   That is the real price of the structured-handoff mechanism on slide 9, and it was invisible until
   we measured it.
2. **The planner is almost free** (453 tokens). Putting routing and planning on the small model was
   the right call, and now there is a number proving it rather than an assertion.

## 0.3b ⚠️✱ THROUGHPUT IS THE BOTTLENECK, NOT COST — and it does not raise an error

**Measured, live, three-specialist TEAM question:**

| | |
|---|---|
| Wall clock | **204.8 s (3 min 25 s)** |
| Model calls | **14** |
| Real tokens | **38,141** |
| Recorded 429s | **0** |

Read that last row twice. **Three and a half minutes, and not one rate-limit error.**

`gpt-oss-120b` is capped at **8,000 tokens/minute** on the free tier, and this question used 38,141.
But Groq does not reject the excess — it *stalls* the request, and the SDK absorbs the retry below
the callback layer, so the call eventually succeeds. No 429 is ever raised. The only signature is
latency:

| Stage | Avg latency |
|---|---|
| `extract_constraints:nutrition` | **34,714 ms** |
| `consult:nutrition` | **30,643 ms** |
| `peer_consult` | **18,512 ms** |
| `consult:surgeon` | 1,080 ms |

An unthrottled consult returns in ~1–4 s. Under throttling the *same* call takes 30 s+. That is why
the Observability tab counts **"throttled calls"** (over 10 s) rather than 429s — counting errors
finds nothing.

**This is a genuinely good 20 seconds on stage.** "Our monitoring showed zero errors while the
system was visibly broken" is a real observability lesson, and the fix — measure latency, not just
error rate — is the kind of thing a graduate audience will recognise.

> **Correction worth noting internally:** an earlier draft of this plan said the client "backs off
> silently" and that we should count 429s. The effect was right, the mechanism was wrong, and the
> metric it implied would have read zero. Caught by actually measuring.

→ **Action, in priority order:**
1. **Upgrade to a paid Groq tier for the presentation window.** Highest leverage, a few dollars,
   removes the failure mode. **Beat 2 is currently 3.5 minutes of a 6-minute demo.**
2. **Drop `k` from 6 to 3 for the demo.** Retrieved context dominates each consult's input tokens.
3. **Pick a flagship question that wakes 2–3 specialists.** This one already only woke three
   (surgeon → PT → nutritionist); the trainer was not selected.
4. Keep the Observability tab open on a second monitor. If it stalls, *show* the ceiling.

## 0.3c ✱✱ The business conclusion that follows: we are throughput-limited, not cost-limited

§0.3b is an engineering finding. This is the commercial one it forces, and it is the strongest
business material in the deck because it is **measured, not modelled**.

Cost to serve, at the verified gpt-oss rates (§0.2):

| Route | Real tokens | Cost to serve | Price (overage) | Gross margin |
|---|---|---|---|---|
| Single specialist | 11,564 | **$0.0024** | $0.12 | **~98%** |
| TEAM (3 specialists) | 38,141 | **~$0.009** | $0.12 | **~93%** |

### ⭐ The headline: the same architecture is cheap or ruinous depending on the model under it

The free tier is a **coursework choice**, not a product decision — and it cannot host a business
(see the ceiling below). So the unit economics are modelled on a stack a startup would actually
deploy: **Sonnet 5** ($3/$15) for specialists, **Haiku 4.5** ($1/$5) for orchestration — a
tier-for-tier swap of the split we already have, applied to the **same measured token counts**.

| | Free tier (actual) | Production (projected) |
|---|---|---|
| Single-specialist question | $0.0024 | **$0.052** |
| TEAM question | $0.0092 | **$0.185** |
| | | **≈ 20× dearer** |

**Say this on stage:** *"On a free tier, our multi-agent design costs a fifth of a cent per
question and nobody cares. On a production model it's 18 cents, and suddenly the fact that our
constraint-extraction step costs almost as much as the consult it summarises is a line item we'd
fight over. The architecture didn't change. The model under it did."*

That forced a reprice. Plans are **derived** from cost at a 75% margin target, not picked:

| Plan | Price | Included | Cost at full quota | Margin |
|---|---|---|---|---|
| Free | $0 | 10 | $1.01 | — |
| Recovery | **$45/mo** | 100 | $10.06 | **77.6%** |
| Clinic | **$225/mo** | 500 | $50.30 | **77.6%** |

The old $19/mo plan with 250 included questions would run at **−32% margin** on this stack.
Still cheaper than one $150 PT visit; Clinic works out to $45/provider/month.

> **Honesty line, say it before someone asks:** token counts are measured, the rates are modelled.
> Different models tokenize differently and spend different amounts on reasoning, so these are
> projections accurate to roughly ±20–30%, not metered bills. The app says so on every screen.

---

**And on the free tier we actually run, token cost is not the constraint at all.** Groq imposes
**two** token limits that cap different things. Keeping them straight matters, because modelling
capacity from the per-minute limit alone overstates it by **~58×**:

| Limit | What it constrains | Effect |
|---|---|---|
| **8,000 tokens/min** | **Latency** — one question | A TEAM question needs 38,141 tokens = **4.8 minutes of the whole account's budget**, so Groq stalls it. This is the 3m25s demo problem |
| **200,000 tokens/day** ⟵ **binding** | **Volume** — how many questions exist | **~5.2 TEAM questions per day**, then the account is done until tomorrow. This is the business ceiling |

Run the daily cap out to a month:

| | |
|---|---|
| TEAM questions / month (entire account) | **157** |
| Recovery subscribers supportable (100 questions each) | **1** |
| Revenue ceiling | **$45 / month** |
| Same figure if every question woke only ONE specialist | **5 subscribers** |

**The entire free-tier account tops out at one paying subscriber — $45/month.** One subscriber is
promised 100 questions a month; the whole account has 157.

**The line to say on stage:** *"On the free tier the entire account supports 157 team questions a
month — that's one customer and $45 of revenue, for the whole company. That's not a margin
problem, it's a supply problem, and the fix is a purchase order rather than a rewrite. Which is
exactly why we modelled the business on a paid stack instead."*

> ⚠️ **Do not quote a per-minute-derived capacity number.** An earlier draft of this section said
> "~36 subscribers, $684/mo" by modelling TPM only — that assumes sustaining 8,000 tok/min for a
> full month (~350M tokens) when the daily cap allows 6M. Both limits are real; only the tighter
> one is the ceiling. The corrected model is in `plans.capacity_report()` and is pinned by tests.

That reframes what would otherwise be an embarrassing demo problem (the 3m25s stall) into the
scaling analysis a business audience actually wants, and it is the same number in both places.

**Monetization shipped 2026-08-08 (D32/D34)** and the demo can show it live: accounts (scrypt),
Free / Recovery $19 / Clinic $99 with metered overage, quota enforcement, and an **admin-only
business console** (`pages/1_Business_Dashboard.py`) rendering MRR, ARR, ARPU, conversion,
per-route margin, and the capacity ceiling above — all from real rows. **Nothing is charged**;
invoices are written `status='simulated'`. Two demo logins: `demo@recoveryteam.app` (patient) and
`admin@recoveryteam.app` (console), password `recovery2026`.

One honest caveat to keep in the speaker notes: billing is **per question, not per token**,
because a TEAM question costs 3.3× a single-specialist one and *the planner* chooses the route,
not the patient (D28). Charging a patient more because our orchestrator decided they needed the
surgeon is not defensible, so we absorb the variance — and the margin table above is the evidence
that absorbing it is safe.

## 0.4 ✱ One old limitation is now fixed — do not read it off the old slide

The previous deck's headline limitation was *"no multi-turn reasoning — each question is answered
from scratch."* **That shipped.** `src/conversation.py` resolves a follow-up against up to 6 prior
turns into a standalone question *before* the pipeline runs, so routing and retrieval both see the
full context. "What about my knee?" now resolves.

The design point is worth making: history is resolved **once, up front**, rather than injected into
every specialist's prompt — because chat history is not retrieval evidence, and mixing it into
specialist context would blur the grounding rule that is the whole anti-hallucination story.

Slide 15 has a replacement set of genuine limitations. The most important one is new (see D28
below) and it is *more* interesting than the one it replaces.

## 0.5 ⚠️ The honest-limitation you must not skip: we gave up a safety guarantee

This is the one item in this document that a sharp grader could use against you if you present the
old story. Say it first instead.

The old deck claimed a **fixed, hardcoded clinical priority order** — surgeon → PT → trainer →
nutritionist — which guaranteed *by construction* that a restrictive specialist's constraints
reached everyone downstream. **That is no longer true.** A small LM now chooses both the roster and
the order (D28). A plan of `["trainer", "surgeon"]` would write the training plan before the
surgeon's restrictions exist.

Three things contain it, and none fully restores the guarantee:

1. RED_FLAG still runs on regex **before** the planner is ever called.
2. The planner prompt states most-restrictive-first as a strong default, and **ordering inversions
   are detected in Python (`violates_restrictiveness`) and written to the execution trace.**
3. `compliance_check` (D30) re-verifies the finished answer against every extracted constraint
   *regardless of what order ran* — recovering after the fact what ordering used to guarantee up front.

**Presenting this as a tradeoff you made knowingly is strictly stronger than presenting the old
guarantee and being caught.** It is also a genuinely interesting design question for this audience:
*when is a learned decision worth a lost invariant, and what do you build to compensate?*

## 0.6 ✱ NEW — chat persistence shipped (Evan, PR #10), and it changes two beats

`src/database.py` (SQLAlchemy/SQLite, 476 lines, 14 tests) persists `chat_sessions` +
`chat_transcripts`: one row per turn, with route, specialists, sources, restrictions, tokens, and
cost as **typed columns** rather than a blob. The Streamlit sidebar gained a real conversation
manager — active-session line with turn count / tokens / accumulated spend, **🧹 New chat**,
a picker over the last 25 conversations with **📂 Open** and **🗑️ Delete**.

Two deliberate design choices worth 10 seconds each on stage:

- **Reopening is an explicit button, not the selectbox's change event** — so browsing the list of
  past conversations never clobbers the chat you have open.
- **Failure to save is surfaced, not swallowed** — `persist_error` renders a visible warning
  ("Last turn was not saved: …"). Same principle as the compliance check's `checked: False`:
  never let a silent failure look like success.

**This makes demo beat 5 real** (see Part 2). The old script said "reload the browser and reopen
the conversation" as an aspiration; it now works, including accumulated spend surviving the reload.

**And it sharpens the privacy limitation on slide 15** — we are no longer merely *holding* health
information in memory, we are *writing it to disk* in plaintext SQLite. Say that plainly.

## 0.7 ✱ CI now splits live tests from offline ones — and the reason is the token cap

Evan added `pytest.ini` with a `live` marker (9 tests) excluded from push/PR CI via `-m "not live"`,
for two stated reasons: **the free-tier daily token cap has been exhausted repeatedly by test
runs**, and LLM phrasing varies between runs so those tests fail for reasons unrelated to the commit
under test.

That is worth a sentence on slide 13, because it is the same constraint as 0.1(a) showing up in a
second place: *"our test suite had to be split by cost, not by scope."* It also means **"most tests
run offline with no API key" is now enforced by tooling**, not just true by accident.

## 0.8 Assets and prep

- **Architecture diagram: redrawn and current** ✱ — `recovery_team_rag_architecture.svg` + a 2x PNG
  export (2000x2300), both on `main` as of commit `1f90e94`. The previous one showed only THREE
  specialists — it predated the nutritionist entirely, and still asserted the fixed
  surgeon→PT→trainer chain D28 removed. The new one has the planner, the consult_next loop, tools,
  the back-channel, the compliance check, and all four collections.
  **Two versions exist — use the right one:** ✱
  - `recovery_team_rag_architecture_slide.png` — **16:9 landscape, 3200x1800. THIS is the one for
    slide 5.** Simplified for projection: bigger type, fewer words, specialist boxes in the app's
    real badge colours. Drops the separate RAG-core band (collection names and chunk counts live
    inside each specialist box instead).
  - `recovery_team_rag_architecture.png` — portrait, 2000x2300, full detail. Good for the README
    and the appendix; it will **not** read projected at full size.

  Re-export either after an edit with (swap the filename):
  `python -c "import cairosvg; cairosvg.svg2png(url='recovery_team_rag_architecture.svg', write_to='recovery_team_rag_architecture.png', scale=2, background_color='white')"`
- **Security guardrails are wired into `src/cli.py`, not `app.py`.** They cannot be demoed in the
  Streamlit UI. Say so if asked.
- **`llm-guard` was evaluated and rejected** — it would have downgraded `transformers` 5.14.1 → 4.51.3,
  breaking `sentence-transformers` and with it all four agents' retrieval *and* CLIP. Good answer to
  "why not use an off-the-shelf guardrail library": we tried, and the dependency cost was the
  entire retrieval layer.

---

# PART 1 — SLIDESHOW PLAN

> **↓↓↓ PASTE FROM HERE TO THE "END OF SLIDESHOW PLAN" MARKER INTO THE DECK AGENT ↓↓↓**

## Deck-level instructions

Build a **15-slide** deck for a **14-minute** final presentation to a graduate-level generative-AI
class. Three presenters share it; speaker assignments and time budgets are marked per slide and
sum to 14:00.

**Tone and design constraints:**

- Technical peer audience. They know RAG, embeddings, vector search, and agent orchestration.
  Never define those terms on a slide.
- **Visual-forward, low text.** Max ~6 short lines of body text per slide. The presenter carries
  the argument; the slide carries the diagram or the number.
- Consistent specialist iconography and color — 🦴 Orthopedic Surgeon · 🩺 Physical Therapist ·
  🏋️ Gym Trainer · 🥗 Sports Nutritionist, in the app's actual badge colors so slides and demo
  match: surgeon `#6366f1` · PT `#0d9488` · trainer `#ea580c` · nutritionist `#16a34a`.
- **The colored icons mean OUR AGENTS, and nothing else.** Slides 2 and 3 describe the *problem* —
  the patient's real-world human care team, and a general-purpose LLM. Draw the four professionals
  there as **grey generic human figures**. The colored icons make their first appearance on slide 4,
  where we introduce the agents, and are used consistently from then on. Reusing them on slides 2–3
  would make the problem statement read as a description of our system.
- **Monospace** for anything that is real system output — traces, route labels, filenames, tool
  calls, code. Real output is the deck's best evidence; make it look like output.
- No animations beyond simple builds. No stock photos of doctors or gyms.
- Slide numbers on. One-line footer with the project name.
- Four slides are marked ⭐ — **8, 9, 12, and 14**. They carry the argument. Give them the most
  design attention and do not let them get compressed if the deck runs long.

**The single argument the deck must land:**

> *A general-purpose LLM answering this question is one model, one undifferentiated knowledge pool,
> and one shot. Our system is a planned sequence of narrow agents — each physically restricted to
> its own vetted corpus, each able to call tools and re-query, each writing under the previous one's
> binding constraints, with the whole thing verified afterward and auditable line by line. The
> difference is not prompt quality. It is that there are **steps**, and every step leaves a record.*

**Speaker split (by role, not by slide count):**

| Speaker | Slides | Time | Owns |
|---|---|---|---|
| **1** | 1–4 | 3:30 | Problem, product, why this shape |
| **2** | 5–10 | 6:00 | Architecture, the agentic loop, tools, safety |
| **3** | 11–15 | 4:30 | Differentiation, evidence, economics, limits |

**Recommended:** Speaker 1 also drives the live demo — they opened with the patient's four
questions, they close by showing the system answer them. Swap freely, but the demo driver should be
whoever has rehearsed it most.

---

## ACT I — The problem and the product · Speaker 1 · 3:30

### Slide 1 — Title / hook
**Speaker:** 1 · **Time:** 0:20

- **Title:** Recovery Team — a care team of four RAG agents
- **Subtitle:** One chat box. Four specialists. Nothing invented.
- Evan · Ben · James — OPIM 5517
- Small standing disclaimer: *Educational support tool — not a substitute for a licensed clinician.*

**Visual:** the four specialist icons in a row, arrows converging into a single chat bubble.

**Speaker note:** "Someone recovering from knee surgery has questions for four different
professionals and access to maybe one of them. We built the other three."

---

### Slide 2 — The problem: one patient, four experts
**Speaker:** 1 · **Time:** 1:00

One patient, eight weeks post-op, four questions belonging to four different professionals:

- *"Can I put weight on it yet?"* → 🦴 surgeon
- *"Is this pain normal or a warning sign?"* → 🩺 physical therapist
- *"How do I get back to lifting?"* → 🏋️ gym trainer
- *"What should I eat to heal faster?"* → 🥗 nutritionist

Then the constraint that makes this a real problem: **in the real world, these four professionals
do not talk to each other.** The surgeon's weight-bearing restriction never reaches the trainer. The
patient is the integration layer, and the patient is the least qualified person in the loop.

> **⚠️ DECK AGENT — do not reuse the four colored specialist icons on this slide.** This slide is
> about the patient's **real-world human care team**, not about our agents. Draw these four as
> **grey, generic human figures**. The colored 🦴🩺🏋️🥗 icons are reserved for our agents and must
> first appear on slide 4. If both slides use the same icons, this slide reads as "our agents don't
> communicate" — which is the opposite of what slides 8 and 9 prove.

**Visual:** one patient icon centered, four question bubbles radiating out to four **grey human**
expert figures — with the *lateral* arrows between them drawn dashed/greyed and marked with a small
✕, showing the coordination that does not happen. This dashed-lateral motif is the setup; slide 9
pays it off by redrawing the same laterals as solid arrows.

**Speaker note:** Land the coordination gap, not just the access gap — and **say "in the real world"
out loud** so nobody hears this as a description of our system. Cost and access are the obvious
framing; the *handoff failure* is what our architecture actually addresses. Plant the flag here:
*"Hold onto those broken arrows — in about four minutes I'm going to show you them working."*

---

### Slide 3 — Why one general model can't do this
**Speaker:** 1 · **Time:** 1:05

Three failure modes of asking one general assistant all four questions:

1. **Hallucination** — it will produce a confident post-op timeline it has no source for, and you
   cannot tell which claims came from where.
2. **Instruction drift** — a constraint stated in turn 2 quietly stops binding by turn 6. Nothing
   enforces it; it's just tokens competing with other tokens in a context window.
3. **Fake pluralism** ⭐ — "act as a surgeon, a PT, and a trainer" is *one* model producing four
   voices from *one* undifferentiated pool of knowledge. The personas are **stylistic, not
   epistemic**. The disagreement between experts — the clinically important part — never actually
   happens, because there is nothing there to disagree.

**Visual:** one grey "LLM" box straddling the same four **grey human figures** from slide 2 (still
not the colored agent icons — see the deck-level rule), with the four corpora it would need drawn as
a single undifferentiated blob.

**Speaker note:** Land failure mode 3 hardest and say "stylistic, not epistemic" out loud. It is the
thesis of the talk, and slides 6, 8, 9, and 12 are each a different proof of it.

---

### Slide 4 — What we built
**Speaker:** 1 → hand off to 2 · **Time:** 1:05

- **Four specialist agents**, each with its **own** curated corpus and its **own** vector-store
  collection — 🦴 surgeon · 🩺 PT · 🏋️ trainer · 🥗 nutritionist
- **90 license-logged documents → 1,886 chunks** across four siloed collections. NIH, MedlinePlus,
  CDC, NHS, HHS. Every file carries a title/source/license/fetch-date header and is committed to
  git. US-government content is public domain; NHS pages are Open Government Licence v3.0.
- **A router** classifies the question. **A small-LM planner** decides which specialists run and in
  what order. **A LangGraph orchestrator** runs them as a loop, each writing under the previous
  one's constraints. **Specialists call tools.** **A synthesizer** merges the drafts, and **a
  compliance check** verifies the result against every extracted restriction. ✱
- **Every conversation persists** — one SQLite row per turn, with route, specialists, sources,
  restrictions, tokens, and cost as typed columns. Reopenable, and aggregatable. ✱
- **Stack:** Groq `gpt-oss-120b` / `gpt-oss-20b` · Gemini Flash (vision only) · local MiniLM
  embeddings · ChromaDB · LangGraph · CLIP · Streamlit · SQLAlchemy/SQLite ✱

**Visual:** four labeled corpus stacks feeding four agent icons. Emphasize four *separate* stacks —
this slide is the visual answer to slide 3's blob.

**Speaker note:** "One design decision drives everything else: each agent's expertise boundary is
enforced by *what it can retrieve*, not by what its prompt promises."

---

## ACT II — Architecture, the agentic loop, and safety · Speaker 2 · 6:00

### Slide 5 — Architecture
**Speaker:** 2 · **Time:** 1:15

```
                       user question  (+ optional photo → Gemini → text description)
                             │
                             ▼
                   ┌───────────────────┐
                   │ RESOLVE FOLLOW-UP │  ← ≤6 prior turns → standalone question
                   └─────────┬─────────┘
                             ▼
                   ┌───────────────────┐
                   │      ROUTER       │  RED_FLAG regex checked FIRST, always wins
                   └─────────┬─────────┘
       ┌───────────┬─────────┴────────┬───────────┬──────────┐
       ▼           ▼                  ▼           ▼          ▼
  single-agent   TEAM            NUTRITION    RED_FLAG    CLARIFY
       │           │                  │           │          │
       └─────┬─────┘                  │      canned safety  follow-up
             ▼                        │      response       question
    ┌──────────────────┐              │      (NO LLM)
    │  PLANNER (20b)   │  which specialists, in what order
    └────────┬─────────┘
             ▼
    ┌──────────────────┐
    │   CONSULT_NEXT   │◄─┐  one node, looped over the plan
    │  retrieve → tools│  │  each agent gets ALL upstream drafts
    │  → draft →       │  │  + their structured constraints as
    │  extract         │  │  BINDING peer_context
    └────────┬─────────┘  │
             └────────────┘  (bounded by plan length ≤ 4)
             ▼
    ┌──────────────────┐
    │   PEER_CONSULT   │  back-channel: one specialist asks another
    └────────┬─────────┘  (≤1 round-trip)
             ▼
    ┌──────────────────┐
    │    SYNTHESIZE    │  attribute each specialist, keep every citation
    └────────┬─────────┘
             ▼
    ┌──────────────────┐
    │ COMPLIANCE CHECK │  answer re-verified against every constraint
    └────────┬─────────┘
             ▼
      final answer + citations + code-appended disclaimer
```

Three call-outs directly on the diagram:

- **Silos** — the trainer *cannot* retrieve surgeon documents. Enforced by separate collections,
  not by a prompt.
- **The plan is data, not topology** ✱ — one `consult_next` node loops over a list the planner
  produced. Adding a fifth specialist changes a list, not the graph.
- **RED_FLAG bypasses everything.** That branch never touches an LLM.

**Speaker note:** "Every box is a node in a LangGraph state machine over a shared typed state. There
is exactly one cycle — `consult_next` back to itself — and it is bounded by plan length, which the
planner caps and de-duplicates at the size of the roster. Every node appends one line to an
execution trace, which is why I can *prove* claims later instead of asserting them."

---

### Slide 6 — Siloed retrieval: four corpora, four collections
**Speaker:** 2 · **Time:** 0:45

| | 🦴 Surgeon | 🩺 PT | 🏋️ Trainer | 🥗 Nutritionist |
|---|---|---|---|---|
| Collection | `surgeon_docs` | `pt_docs` | `trainer_docs` | `nutrition_kb` |
| Documents | 18 | 40 | 22 | 10 |
| Chunks | 121 | **1,050** ✱ | 536 | 179 |
| Anchor source | MedlinePlus post-op / discharge instructions | NIA 34-page older-adult exercise guide, CDC STEADI | HHS Physical Activity Guidelines, 2nd ed. (118 pp) | NIH Office of Dietary Supplements fact sheets |

- ~1,000-char chunks, 150-char overlap; embedded locally by `all-MiniLM-L6-v2` (384-dim, CPU, free);
  top-k cosine at **k=6** per agent.
- **Local embeddings were deliberate:** zero API cost, zero rate limits, ingestion works offline.
  The course reference project used a cloud embeddings API and had to sleep 60 seconds per batch to
  dodge rate limits. We deleted that entire class of problem — *and given that we hit Groq's daily
  token cap during development, that decision aged well.*
- Three elderly-onboarding documents appear in **both** the PT and trainer corpora *on purpose* —
  the collections are physically siloed, so shared content must be physically duplicated. That
  duplication is the cost of the silo, and we paid it knowingly.

**Speaker note:** "This is the epistemic boundary from slide 3, made physical. There is no prompt in
this system that says 'don't answer nutrition questions.' The trainer simply has no nutrition
documents to retrieve."

---

### Slide 7 — The router: we deleted our own regex, then put a floor under it
**Speaker:** 2 · **Time:** 0:55

A three-act story — the most genuinely interesting engineering narrative in the project, because it
went in both directions.

1. **v1: weighted regex cue scorer.** Fast, free, deterministic. Brittle. The bug that killed it: a
   pattern written to catch *"stitches out"* did not match *"when do my stitches come out."* Every
   new specialist and phrasing meant another hand-patch.
2. **v2: LLM-primary classification.** One call returns the route label *and* which specialists
   apply, parsed into the same `scores` dict the orchestrator already consumed — so the
   orchestrator needed **zero changes**. Robust to phrasing. **Trade-off accepted explicitly:**
   routing is no longer free, and costs latency on every question.
3. **v3: put the keywords back — underneath.** When the classifier hedges (confidence < 0.50),
   answers CLARIFY, or is unavailable, a deterministic keyword net catches the question. **The regex
   went from being the router to being the floor.**

**And one regex never moved:** `RED_FLAG` is checked **before** the classifier and always wins, at
confidence 0.97. A safety gate has to behave identically every run, and a model cannot promise that.

**Visual:** three stacked bands — `RED_FLAG regex` (top, "always first, always wins"), `LLM
classifier` (middle, "the router"), `keyword net` (bottom, "the floor").

---

### Slide 8 ⭐ — This is not one LLM call: the agentic loop
**Speaker:** 2 · **Time:** 1:20 — **the slide Ben asked for; the mechanism slide**

> **Deck agent:** build this as a numbered horizontal or vertical pipeline, each step a labeled box.
> The point is *countable steps*. A single "LLM" box on the left with an arrow to an answer, versus
> this pipeline on the right, is the strongest possible visual for the whole talk.

**One question. Six distinct decisions, none of them made by the same call:**

| # | Step | What decides | Model |
|---|---|---|---|
| 1 | **Resolve** the follow-up against ≤6 prior turns | LLM | 120b |
| 2 | **Classify** the route — RED_FLAG regex checked first | regex, then LLM | 20b |
| 3 | **Plan** which specialists run, and in what order | LLM | 20b |
| 4 | **Consult** each specialist in turn — *retrieve → optionally call tools → draft* | LLM + tools | 120b |
| 5 | **Extract** binding constraints from each draft, feed them forward | LLM | 120b |
| 6 | **Back-channel** — one specialist asks another a direct question | LLM | 120b |
| 7 | **Synthesize**, then **verify** the answer against every constraint | LLM | 120b + 20b |

**Real observed output — put this on the slide verbatim, in monospace:**

```
route_question:     TEAM (0.97, llm) - All specialists needed for safe
                    return to lifting and nutrition support.
plan_consultation:  surgeon -> pt -> nutrition (llm) - The surgeon must
                    first establish post-operative restrictions and safe
                    weight-bearing limits. The physical therapist then
                    builds on those limits to guide safe lifting
                    progression. Nutrition can then advise...
consult_surgeon:    6 source(s)
consult_pt:         3 source(s), 1 upstream draft(s) as peer_context
consult_nutrition:  2 source(s), 2 upstream draft(s) as peer_context,
                    tools=['search_my_corpus', 'search_my_corpus']
peer_consult:       pt -> surgeon: "Is the patient cleared to begin light
                    resistance training at 8 weeks post-meniscus repair?"
                    (4 source(s))
synthesize_team_answer: merged 5 draft(s)
compliance_check:   no constraint conflicts found
```

> **✱ This trace is verbatim from a live run on 2026-08-08 — not reconstructed.** 14 model calls,
> 38,141 tokens, 204.8 seconds.

**Speaker note:** "Read the second line. The planner didn't just pick three specialists — it
*explained its ordering*, and that reasoning is in the trace. Then look at line four: the surgeon
called a tool. That's the difference between an agent and a prompt. And the last line is the system
checking its own homework." Then: **"A general assistant does step 4, once, with no corpus. We do
seven steps and write down all of them."**

---

### Slide 9 ⭐ — Two mechanisms: binding constraints, and tools
**Speaker:** 2 · **Time:** 1:30 — **the architectural payoff slide**

> **DECK AGENT — this slide is the visual answer to slide 2.** Somewhere on it, redraw slide 2's
> four figures with the **lateral arrows now solid** and in the specialist colors: downstream arrows
> for the constraint chain, plus one arrow pointing *back* upstream for the peer consult. Same
> motif, repaired. That before/after is the single clearest image in the deck.

Split the slide in two halves.

**LEFT — Constraint handoff (why it's a *team*, not four chatbots in a trench coat)**

- Each specialist's draft is injected into the next specialist's prompt as **binding restrictions**,
  not suggestions — *"treat any restrictions in their draft as binding; build on them, never
  contradict them."*
- A separate LLM call extracts a **structured constraint list** — `{body_part, restriction,
  duration}` — so the downstream agent doesn't parse restrictions out of prose and hope. Degrades to
  `[]` on failure; the raw draft still carries the restriction in prose either way.
- **The back-channel closes the loop** ✱ — the chain used to be strictly one-directional. Now, if a
  specialist hits the edge of its scope, it can put a direct question to another specialist and the
  reply joins the synthesis evidence. Capped at one round-trip so the DAG still cannot run away.

**RIGHT — Tools: agents that compute, re-query, and look things up** ✱

| Tool | Why |
|---|---|
| **Calculators** — protein target, training load, 1RM, post-op phase, unit conversion | The numbers this system hands patients are arithmetic, and **arithmetic is where LLMs quietly slip**. The tool multiplies; the corpus still decides the clinical guideline. |
| **`search_my_corpus`** — re-query own collection with better terms | A weak first retrieval used to mean a weak answer. Now the agent gets a second attempt. **Siloing survives: the collection name is injected by the agent, never read from model-supplied arguments** — asserted by test. |
| **`search_pubmed`** — gated | Offered **only when the agent's own corpus returned nothing**, enforced in code, not requested in a prompt. Results cite `[research: PMID …]`, never `[source: filename]`, so a single abstract can never be mistaken for vetted guidance — and can never override a restriction. |

Loop capped at **2 tool rounds**. Unbounded tool loops are the standard way an agent burns a metered
budget, and we have hit the daily cap more than once.

**Speaker note — open with the callback to slide 2:** *"Remember the four experts who don't talk to
each other? These are those arrows, working."* Then the tools half. Close on the gate: "It would
have been easy to write 'only use this if your corpus fails' in the prompt and call it a policy. We
don't offer the tool schema at all unless retrieval came back empty. **A capability the model cannot
see is a policy it cannot violate.**"

---

### Slide 10 — Safety as an eight-layer stack
**Speaker:** 2 · **Time:** 0:55

| # | Layer | Mechanism |
|---|---|---|
| 1 | Emergency detection | Deterministic red-flag regex, checked **before any AI involvement** — canned urgent-care response |
| 2 | Expertise silos | Each agent retrieves only from its own collection |
| 3 | Grounding rule | "Answer ONLY from provided context," baked into the shared base class — a persona cannot omit it |
| 4 | Persona deference | PT never diagnoses · trainer never assesses pain · nutritionist never programs |
| 5 | Tool gating ✱ | PubMed withheld in code unless the corpus missed; corpus tool cannot cross silos |
| 6 | Constraint propagation | Every upstream draft binds everything below it, as structured constraints |
| 7 | **Compliance check** ✱ | The synthesized answer is re-verified against every extracted restriction; violation appends a visible warning |
| 8 | Fixed disclaimer + graceful failure | Disclaimer appended **by Python**. Agents never raise; errors become routing conditions |

**The three sentences that matter:**

- Layers 1 and 8 are **Python constants**. An LLM cannot forget them, rephrase them, or be talked
  out of them.
- Layer 7 **distinguishes "checked and clean" from "could not check"** (`checked: False`). A broken
  checker never reports a clean bill of health it did not establish. *(We learned this the hard way —
  see slide 13.)*
- Graceful failure is not theoretical: **verified live during this revision.** With the PT knowledge
  base missing and the Groq account rate-limited mid-run, the system returned a polite fallback
  naming both causes and the exact rebuild command — no stack trace, no invented answer.

---

## ACT III — Differentiation, evidence, economics · Speaker 3 · 4:30

### Slide 11 — Beyond text RAG
**Speaker:** 3 · **Time:** 0:45

Four capabilities layered on the core system. One line each — do not deep-dive.

- **Patient photo upload → VLM** ✱ — a user can attach a photo (swelling, an incision, exercise
  form). Google Gemini Flash converts it to a factual text description, which is prepended to the
  question *before* it enters the pipeline. **Why a description rather than pixels to four agents:**
  every specialist answer is grounded in its own retrieved corpus; feeding raw images to the agents
  would bypass that entirely. One conversion up front keeps routing, grounding, and synthesis intact.
- **CLIP multimodal search** ✱ — `clip-ViT-B-32` embeds **279 exercise diagrams and extracted PDF
  figures** into the same space as the question text, so a rehab question surfaces the *picture* of
  the movement. **Now real image embeddings with a hybrid filename bonus** — it was filename
  matching before. Wired into the app.
- **GraphRAG property graph** — clinical entities (`Procedure`, `Nutrient`, `Exercise`,
  `Contraindication`) joined by typed edges, enabling multi-hop reasoning vector similarity cannot
  reach. **⚠️ Check 0.1(b) before claiming Kùzu — it currently falls back to in-memory data.**
- **Security guardrails** — prompt-injection / jailbreak / SQL-injection scanning and PII redaction,
  with a red-team suite. **Currently on the CLI path, not the Streamlit app.**

**Speaker note:** Volunteer the two wiring caveats rather than waiting to be caught. In this room
that buys more credibility than it costs.

---

### Slide 12 ⭐ — Why not just ask ChatGPT or Claude?
**Speaker:** 3 · **Time:** 1:15 — **the most important slide in the deck**

| | General assistant | Recovery Team |
|---|---|---|
| **Knowledge** | Parametric memory. You cannot audit what it drew on. | Every claim retrieved from a named, versioned, license-logged document. File-level citations. |
| **Not knowing** | Almost never says "I don't have material on that." | Structural refusal — and if the corpus misses, it says so *and then* is allowed one gated PubMed lookup, labeled as research. |
| **Roles** | Personas are **stylistic**. One model, one knowledge pool, four voices. | Boundaries are **physical**. The trainer *cannot see* surgeon documents. |
| **Steps** ✱ | One call. One shot. | **7 distinct stages**, each logged: resolve → route → plan → consult(+tools) → extract → back-channel → synthesize → verify. |
| **Arithmetic** ✱ | Computed in-weights, silently, sometimes wrong. | Deterministic calculator tools. The protein number came from a function, not a guess. |
| **Constraints** | No guarantee training advice was generated *subject to* the clinical restriction. | Structured binding constraints passed forward + a compliance check on the finished answer. |
| **Safety** | Model behavior: usually good, statistically variable, jailbreakable. | Deterministic pre-model short-circuit. Identical every run, zero token cost. |
| **Auditability** | Black box. | Full execution trace: who ran, in what order, **why that order**, from which files, using which tools. |
| **Corpus control** | Theirs, opaque, changes under you. | Ours. Swap `data/` and you have a different vertical. |

**The closing line — say it out loud, do not paraphrase:**

> "GPT-5 almost certainly *knows* more orthopedics than our 90 documents. That is not the claim. The
> claim is that it cannot show you where an answer came from, cannot be prevented from answering
> outside its lane, cannot prove the trainer heard the surgeon, and cannot tell you which of its
> steps produced the number it just gave your patient — because it only has one step. We can answer
> all four, and those are exactly the properties you need before anyone lets a system like this near
> a patient."

**Speaker note:** Concede the knowledge-breadth point first and fast; conceding it is what makes the
rest land as engineering rather than marketing. Then point forward: "the next four minutes of live
demo are the proof of rows 2, 4, 5, and 8."

---

### Slide 13 — Evidence: what we measured, including what we got wrong
**Speaker:** 3 · **Time:** 1:05

- **Routing accuracy: 15/15** on the frozen 15-question battery, run live 2026-07-18. **⚠️ That run
  predates both the model migration and the planner.** Re-run before presenting or say "last
  verified in July, on the previous model." *(See 0.1(a) — budget the tokens.)*
- **Test suite: 74 test functions across 10 modules** ✱ — routing, planner bounds, tool dispatch,
  compliance, conversation memory, persistence, GraphRAG, red-team, unit economics, and full E2E.
  **CI splits them by cost, not by scope:** 9 are marked `live` (need a real key *and* built
  collections) and are excluded from push/PR runs, because test runs had repeatedly exhausted the
  free tier's daily token cap. Everything else runs **offline with no API key** — now enforced by
  tooling rather than true by accident. ✱
- **LLM-as-a-judge evaluation** — scores Clinical Safety (1–5), Constraint Adherence (1–5), and
  Brevity (1–5) on adversarial high-risk scenarios: premature 225 lb squatting, skipping prescribed
  PT, forcing shoulder ROM, 500 cal/day diets.
- **⭐ The bug worth presenting:** our safety evaluation **returned a hardcoded 5/5 PASS whenever the
  judge call threw an exception.** A crashed evaluation was scoring as a perfect safety result. We
  found it in an audit and fixed it to report score 0 / `verdict: ERROR`. **The old "100% pass on
  high-risk scenarios" number was therefore not trustworthy, and we are not presenting it.** The
  same lesson produced layer 7 on slide 10 — the compliance check reports `checked: False` rather
  than claiming a clean result it never established.

**Speaker note:** The bug is the best 20 seconds in this act — *volunteer it*. "The most dangerous
failure mode in an eval harness isn't a low score, it's a fake high one. Ours failed open, and it
failed open on the safety metric specifically. That's the kind of thing you only find by reading
the exception handler."

---

### Slide 14 ⭐ — Unit economics: what an agent architecture actually costs
**Speaker:** 3 · **Time:** 1:05

> **✱ NO LONGER A PLACEHOLDER.** `src/telemetry.py` now captures Groq's own token counts, latency,
> and 429s for every call in the pipeline, tagged by stage. These are measurements, not estimates.
> **Build this slide around the per-stage table — that is the whole point.**

**Cost per single-specialist question — the cheapest non-red-flag route:**

| Stage | Tokens | Latency |
|---|---|---|
| `consult:pt` | 3,643 | 3,655 ms |
| `synthesize` | 2,641 | 2,320 ms |
| `extract_constraints:pt` | 2,475 | 2,323 ms |
| `compliance_check` | 1,364 | 580 ms |
| `route` | 988 | 410 ms |
| `plan` | 453 | 213 ms |
| **Total** | **11,564** | **6 calls** |

**The three things to say:**

1. **We were wrong by 5.7×, and we can prove it now.** The estimator in the app prices the visible
   question and answer at chars/4 — it logged a comparable question at 2,011 tokens. Real: 11,564.
   And that is the *cheapest* route.
2. **Constraint extraction costs nearly as much as the consult it summarises** — 2,475 vs 3,643.
   That is the price of the structured-handoff mechanism from slide 9, and it was invisible until we
   instrumented it. *This is the number that makes the slide interesting: we can now cost an
   architectural decision, not just a query.*
3. **The planner is almost free** — 453 tokens. Routing and planning on the small model was a bet;
   this is the receipt.

**⚠️ The constraint that actually bites is per-MINUTE, not per-day:** `gpt-oss-120b` is capped at
**8,000 tokens/minute** on the free tier. One specialist question exceeds a full minute of budget.
When it runs out the client backs off silently, and the app looks frozen. We hit this live.

**Presenter script (~65s):**

> "We instrumented every model call, and the first thing it told us was that our own cost estimate
> was wrong by almost six times. The estimator priced the question and the answer; it never saw the
> router, the planner, the constraint extractions, or the compliance check. A single-specialist
> question is eleven and a half thousand tokens across six calls.
>
> But the number I actually care about is this one — constraint extraction costs almost as much as
> the specialist consult it summarises. That's the mechanism from three slides ago, the thing that
> makes this a team instead of four chatbots, and it roughly doubles the cost of every specialist in
> the chain. We couldn't see that before. Now we can put a price on an architectural decision rather
> than on a query, which is the thing you actually need to make tradeoffs.
>
> And the real constraint turned out not to be money at all. It's eight thousand tokens a minute on
> the free tier — one question exceeds that, so the client backs off and the app looks frozen. We
> found that by watching our own demo hang. The fix is a paid tier; the lesson is that for a
> multi-agent system the binding constraint is throughput, not price."

**Still open:** dollar cost per route (gpt-oss pricing not yet confirmed — see 0.2) and the
human-consult ROI comparison ($150–$350/hr). Leave those two as `— TBD —`; everything else on this
slide is real.

---

### Slide 15 — Limitations, roadmap, and demo handoff
**Speaker:** 3 → demo driver · **Time:** 0:20

**What we know is missing** — all real, none embarrassing:

- **⭐ We traded a safety guarantee for flexibility, knowingly.** ✱ Ordering used to be hardcoded
  most-restrictive-first, which *guaranteed by construction* that constraints reached everyone
  downstream. A small LM now picks the order. We contain it three ways — RED_FLAG still pre-empts
  planning, ordering inversions are detected in Python and logged, and the compliance check
  re-verifies the answer regardless of order — but **none of them fully restores the invariant.**
- **Naive retrieval.** Top-k cosine only. No BM25 hybrid, no reranking, no metadata filtering.
- **Corpus breadth ≠ clinical depth.** Public-domain *patient-education* material, not clinical
  protocols. Exactly why the disclaimer exists.
- **Health data is now *written to disk* in plaintext SQLite.** ✱ Persistence shipped this cycle,
  so this stopped being "held in memory" and became "stored." No encryption at rest, no
  authentication, no retention policy. Fine for a local single-user demo; genuinely blocking for any
  hosted deployment.
- **Guardrails and GraphRAG are partly wired** — CLI-only, and Kùzu falls back to in-memory.

**Next:** per-call cost instrumentation · guardrails on the app path · hybrid retrieval · restoring
an ordering invariant that survives a learned planner.

**Then hand off — four things to watch in the demo:**

1. **The route chip and badges** — which specialists the system chose
2. **The trace** — the plan, its stated reasoning, and the tool calls
3. **The red-flag question** — answered instantly, with no model call at all
4. **The follow-up** — a question that only makes sense in context, resolved
5. **The reload** — close the browser, reopen the conversation, everything comes back ✱

> **↑↑↑ END OF SLIDESHOW PLAN ↑↑↑**

---

# PART 2 — LIVE DEMO SCRIPT

**Driver:** Speaker 1 · **Target:** 6:00 · **Cap:** 7:00 · **Mode:** live Streamlit app

## Pre-flight — do this before class, not on the clock

- [ ] **⚠️ Check remaining Groq token budget at console.groq.com.** A TEAM question is 12–18 calls
      and the free tier caps at 200k tokens/day. **Do not burn the budget rehearsing that morning.**
- [ ] `.venv` activated; `GROQ_API_KEY` and `GOOGLE_API_KEY` present in `.env`
- [ ] **All four collections built and verified non-empty** — `pt_docs` · `trainer_docs` ·
      `surgeon_docs` · `nutrition_kb`. This has silently broken once; check, don't assume.
- [ ] **Warm-up run.** One throwaway question, fully completed — the first question of a process
      pays for loading MiniLM and CLIP. The class must not watch that.
- [ ] Sidebar toggle **"Show routing debug trace" = ON** — the trace is half the point
- [ ] **Pre-seed one saved conversation** so beat 6 has something to reopen instantly ✱
- [ ] Have one photo ready on the desktop if you plan to demo the upload beat
- [ ] Browser zoom 125–150%; pick light or dark and stick with it
- [ ] Second terminal at the repo root for the CLI fallback
- [ ] Phone hotspot ready; notifications off; second monitor mirrored not extended

## Timing reality

**✱ MEASURED: a three-specialist TEAM question took 204.8 seconds — 3 minutes 25 seconds.** 14
calls, 38,141 tokens. On the free tier that is **more than half your entire demo budget spent on one
question**, because Groq throttles rather than rejects (see 0.3b).

**This is the single biggest risk to the live demo.** Upgrade the Groq tier, or restructure beat 2.

**Turn the latency into content.** Type, press Enter, and *keep talking*. The beat-2 narration is
written to be delivered over the wait. Never stand in silence, and never apologize for it.

---

## Beat 1 — Orientation · 0:00–0:25

Show the app without typing. One chat box. Sidebar: knowledge-base rebuild buttons, debug toggle,
unit economics.

> **Say:** "Everything on the architecture slide is behind this one text box. Four agents, four
> corpora, a router, a planner, and an orchestrator — the user sees a chat window."

---

## Beat 2 — The flagship: planning, tools, constraint handoff · 0:25–2:30

**Type exactly:**

```
I'm 8 weeks post-meniscus surgery - how do I get back into lifting safely, and how much protein should I eat?
```

**Press Enter, then narrate over the spinner** (~40s of material):

> "Right now: the router is classifying this, and that's a small-model call. It comes back TEAM.
> Then a *second* model call — the planner — decides which specialists to wake up and what order to
> run them in, and it writes down its reasoning. The surgeon goes first because post-op restrictions
> have to bound everything downstream. Its draft gets turned into a structured constraint list, and
> that list is prepended to the next specialist's prompt as *binding restrictions* — so the PT is
> writing under the surgeon's constraints, not alongside them. The nutritionist will probably call a
> calculator tool for the protein number rather than doing that arithmetic in its head. Then a
> synthesizer merges the drafts, and a final check re-reads the answer against every restriction
> that came out of the chain."

**When it lands, point at these in order — rehearse this sequence:**

1. **Route chip** — `TEAM` with its confidence
2. **Badges** — the roster the *planner* chose
3. **Routing trace (debug)** ⭐ — **spend the most time here.** Read the `plan_consultation` line
   aloud, including its reasoning. Then find `tools=[...]` on a consult line and say: *"that's the
   agent calling a function, not guessing."*
4. **Binding restrictions expander** — the structured constraints as a checklist
5. **Sources expander** — per-agent file lists. Separate specialists, separate document sets.

> **Say:** "That trace is the difference between an agent system and a prompt. I can *prove* the
> trainer read the surgeon, and I can show you which of these numbers came from a calculator."

---

## Beat 3 — Multi-turn: the follow-up ✱ · 2:30–3:05

**New this cycle — and it replaces a limitation the old deck had to apologize for.**

Immediately after beat 2, type only:

```
what about swimming?
```

That question is meaningless standalone. Watch it resolve against the 8-weeks-post-meniscus context
and route correctly.

> **Say:** "That question has no meaning on its own. Before anything else runs, a call resolves it
> against the last few turns into a standalone question that carries the surgical context forward.
> We deliberately do that *once, up front*, rather than injecting chat history into every
> specialist's prompt — because chat history isn't retrieval evidence, and mixing it into their
> context would blur the grounding rule that's the whole anti-hallucination story."

*(Bonus if it fires: swimming is thin in all four corpora, so this may double as the honest-ignorance
beat — the system saying it doesn't have material rather than inventing a protocol.)*

---

## Beat 4 — Deterministic safety · 3:05–3:40

**Type exactly:**

```
My calf is swollen, hot, and I have sharp pain when I stand.
```

It returns **instantly**. Let the speed make the point before explaining it.

- Route chip: `RED_FLAG`, ~0.97 · **no badges** · trace is **two lines** · no retrieval, no LLM,
  no token cost

> **Say:** "That's a possible DVT. It never reached a language model. A regex caught it and a fixed
> Python string answered it. Nothing on that path varies between runs, and nothing in a prompt can
> talk it out of firing — which is exactly what you want from the one branch where being wrong is
> dangerous."

---

## Beat 5 — Honest ignorance · 3:40–4:15

*Skip if beat 3's swimming question already produced a refusal.*

**Reliable fallback — second terminal, single agent, no router:**

```
python -m src.agents.gym_trainer "How much protein should I eat to build muscle?"
```

Verified behavior, and worth showing regardless: it isolates the mechanism — the *trainer
specifically*, refusing to leave its lane, with no router or orchestrator involved.

> ⚠️ **Trap — do not use the protein question in the app.** It *used* to produce the trainer's
> famous refusal, but we shipped a nutritionist since; the router now correctly sends it to 🥗 and it
> gets a real answer. That's an upgrade, not a bug, but it kills the beat.

> **Say:** "This is behavior a general assistant essentially never gives you. The refusal isn't
> politeness — it's structural. There's nothing about nutrition in that collection, and the base
> class prompt forbids answering from anything else."

---

## Beat 6 ✱ NEW — It's a product, not a notebook · 4:15–4:55

**This beat was aspirational in the last draft. It works now** (Evan's PR #10).

1. **Reload the browser (F5) in front of the class.** The chat vanishes from the screen.
2. Reopen it from the sidebar picker → **📂 Open**.
3. Everything returns: the answer, badges, per-agent sources, binding restrictions, the trace, and
   the accumulated spend.
4. Click **🧹 New chat** — two independent recovery scenarios now sit side by side.

> **Say:** "Every turn is a row in SQLite — question, answer, route, which specialists ran, sources,
> restrictions, tokens, cost. Route and cost are *typed columns*, deliberately, so we can aggregate
> them: what does routing look like across a hundred users, and what did it cost. That's the
> difference between a demo and a product."

*Small detail worth pointing at if you have the second:* reopening is an explicit **Open** button
rather than the dropdown's change event, so browsing past conversations never clobbers the chat you
have open. And if a save fails, the sidebar says so out loud — same principle as the compliance
check reporting "could not check" instead of quietly implying success.

---

## Beat 7 — Optional: the photo upload ✱ · 4:55–5:15

**Cut this first if running long.** Click the paperclip in the chat input, attach a photo, and ask
about it.

> **Say:** "Our specialists run on a text-only model. So the image goes to a vision model once, up
> front, becomes a factual description, and that description enters the pipeline as text — which
> means routing, grounding, and citation all work exactly as they did. We didn't build a second
> architecture for images."

---

## Beat 8 ✱ — Unit economics, live · 5:15–5:45

**No longer a placeholder — there is a real tab to show now.**

1. Switch to the **📊 Observability** tab. It is live data from the questions the class just watched.
2. Point at the **per-stage table** — that is the beat.
3. Point at the **tokens/minute vs the 8,000 ceiling** chart.

> **Say:** "We instrumented every model call, and the first thing it told us was that our own cost
> estimate was wrong by almost six times — it priced the question and the answer and never saw the
> router, the planner, the extractions, or the compliance check. But look at this row: constraint
> extraction costs almost as much as the specialist consult it summarises. That's the mechanism that
> makes this a team rather than four chatbots, and now we can put a price on it. And the real
> constraint isn't money — it's eight thousand tokens a minute. One question exceeds it."

*If the app stalled earlier in the demo, come back to this chart and show the ceiling being hit.
"That wasn't a hang, that was backoff" is a much better recovery than an apology.*

---

## Beat 9 — Close · 5:45–6:00

> **Say:** "Four agents, four siloed corpora, a planner that explains itself, tools instead of
> mental arithmetic, a safety branch that never touches a model, and a full audit trail for every
> answer. You can ask ChatGPT about your meniscus. You can't ask it to prove the trainer heard the
> surgeon."

---

## Contingency

| If… | Then… |
|---|---|
| **Groq 429s / long spinner** ⚠️ | **The likeliest failure, and it is per-MINUTE not per-day (0.3b).**  Open the Observability tab and show tokens/minute against the 8,000 ceiling — *"that is backoff, not a hang."* Then pivot to beat 4, which needs no API.  Original note: The fallback names the cause and stays graceful — you can honestly say "that's layer 8, and you're watching it work." Then pivot to beat 4, which needs no API. Check the budget beforehand so this doesn't happen. |
| Groq is merely slow | Keep narrating. If it fails outright: `python -m src.orchestrator "…"` in terminal two. |
| Network dies completely | Beat 4 (red flag) still works — it never calls out. **So does beat 6**: a reopened conversation renders entirely from SQLite. Two fully offline beats. |
| A knowledge base is missing | The fallback names the exact rebuild command. Embarrassing but *demonstrates layer 8*. Rebuild is local-only, no API needed. |
| Running long | Cut beat 7 (photo) first, then beat 5. **Do not cut beat 3 or 6** — multi-turn and persistence are both new this cycle, and beat 3 retires an old limitation. |
| Running short | Ask a `NUTRITION_ONLY` question for single-specialist contrast with TEAM — doubles as cost-contrast setup for beat 8. |
| Asked to see the guardrails | CLI path only: `python -m src.cli "…"`, or defer to Q&A. |

---

# PART 3 — Q&A PREP

**⭐ "How is this different from just calling an LLM with a good prompt?"** *(the question the deck is built to answer)*
Three concrete differences, not one. **Steps:** a question passes through seven distinct stages —
follow-up resolution, routing, planning, consultation, constraint extraction, a peer back-channel,
and synthesis-plus-verification — each a separate decision, each logged. **Tools:** the specialists
call deterministic calculators for anything a patient might act on, can re-query their own corpus
when retrieval is thin, and get a gated PubMed lookup only on a genuine miss. **Boundaries:** each
agent physically cannot retrieve outside its own collection. A single call gives you one shot, no
corpus, no record, and arithmetic done in-weights. If you don't need provenance or enforced scope,
one model with a good prompt is cheaper and faster — that's a real answer, not a dodge.

**"Isn't 90 documents nothing compared to what GPT-5 knows?"**
Correct, and not the claim. We trade knowledge breadth for provenance, enforced scope boundaries,
deterministic safety, and auditability. Our corpus is public-domain *patient-education* material,
not clinical protocols — exactly why the disclaimer exists.

**"Does it remember the conversation?"** ✱ *(answer changed — the old deck said no)*
Yes, as of this cycle. A follow-up is resolved against up to six prior turns into a standalone
question before anything else runs. We do it once up front rather than injecting history into every
specialist's prompt, because chat history isn't retrieval evidence and mixing it in would blur the
grounding rule.

**⭐ "You said the order is fixed for safety — but a model picks it?"** ✱ *(the sharpest available question)*
Right, and we changed that deliberately and gave something up. Fixed ordering guaranteed *by
construction* that a restrictive specialist's constraints reached everyone downstream. A small LM
now picks roster and order, which is more flexible and strictly less guaranteed. Three
compensations: RED_FLAG still runs on regex before the planner is ever called; ordering inversions
are detected in Python and written to the trace; and a compliance check re-verifies the finished
answer against every extracted constraint regardless of what order ran. That recovers after the fact
what we used to have up front — it is not the same thing, and we don't claim it is.

**"How good is the routing, really?"**
15/15 on our frozen battery, run live in July. Be precise about the caveat: **that run predates both
the model migration and the planner.** Two gaps found in July are fixed — a vague "what's the best
gym?" that resolved to `TRAINER_ONLY` instead of asking for clarification, and a question with
explicit surgeon language that under-chained. Both fixes were prompt-level: few-shot examples, plus
an explicit rule that a *past* surgical clearance is still an *ongoing* constraint. That second one
is the more interesting failure — the model treated "my surgeon already cleared me" as a resolved
past event rather than a live restriction.

**"Why is the safety check a regex when everything else is an LLM?"**
Deliberate, and we went both directions. We *replaced* a regex router with an LLM classifier because
hand-tuned cue lists were brittle — a pattern for "stitches out" didn't match "when do my stitches
come out." But a safety gate must behave identically every time, and an LLM can't promise that. The
regex went from being *the router* to being *the floor*, and RED_FLAG never moved off it.

**"What stops a specialist from using the corpus tool to read another specialist's documents?"** ✱
The collection name is injected by the agent object, never read from the model's arguments. There's
a test that calls the dispatcher with `collection_name: "surgeon_docs"` as a trainer and asserts the
trainer's own collection is what actually gets searched.

**"Isn't PubMed access a hole in your grounding story?"** ✱
It would be if it were always available. The schema isn't offered to the model at all unless that
agent's own retrieval returned nothing — enforced in code, not requested in a prompt. A capability
the model can't see is a policy it can't violate. Results are cited `[research: PMID …]`, never
`[source: filename]`, and can't override a restriction. It's metadata-only, which also sidesteps the
full-text licensing problem.

**"What's your retrieval strategy?"**
Naive top-k cosine, k=6, 384-dim MiniLM, per-agent collection. No BM25 hybrid, no reranking, no
metadata filtering. Fine at ~1,900 chunks; it's on the list.

**"Why not use an off-the-shelf guardrail library?"** ✱
We evaluated `llm-guard` and rejected it on dependency grounds: it required downgrading
`transformers` 5.14.1 → 4.51.3, which breaks `sentence-transformers` — and that would take out all
four agents' retrieval *and* CLIP image search. The guardrail would have cost us the retrieval layer.

**"Is it secure? What about prompt injection?"**
A scanner module for prompt injection, jailbreaks, SQL injection, and PII redaction, with a red-team
suite. Be accurate: currently on the **CLI** path (`src/cli.py`), not the Streamlit app.

**"You're storing health information."** ✱ *(answer got sharper — we now write it to disk)*
Yes, and as of this cycle we mean that literally: chat persistence shipped, so every turn is a row
in a local SQLite file — question, answer, route, specialists, sources, restrictions, tokens, cost.
Plaintext, no encryption at rest, no auth, no retention policy. It never leaves the machine, which
is fine for a single-user local demo and genuinely blocking for anything hosted. We'd rather state
that than let "it's local" do more work than it can carry.

**"Why persist route and cost as typed columns instead of dumping JSON?"** ✱
Because the interesting questions are aggregate ones. Typed columns let us ask what routing looks
like across a hundred users, which routes are expensive, and whether the planner's choices correlate
with anything — none of which you can do over a blob without reprocessing every row. It cost us
almost nothing at write time and it's the difference between a transcript log and a dataset.

**"What happens if a knowledge base is missing?"**
Verified live: polite fallback naming the cause plus the exact rebuild command, no stack trace.
Agents capture errors into a return field instead of raising, so the graph treats a broken agent as
a routing condition. On a TEAM route, one broken knowledge base degrades the answer instead of
killing it.

**"Why not fine-tune?"**
Corpus changes shouldn't require retraining, we need file-level citation for every claim, and the
whole thing runs on a free API tier plus local embeddings. Swap `data/` and you have a different
vertical.

**"What does a query actually cost?"** ✱ *(we can answer this properly now)*
Measured, not estimated: a single-specialist question is **11,564 tokens across 6 calls**. Cost is
entirely Groq inference — embeddings, vector store, graph, and persistence are local and free. The
interesting breakdown is by stage: constraint extraction (2,475) costs nearly as much as the
specialist consult it summarises (3,643), so the structured-handoff mechanism roughly doubles the
price of every specialist in the chain. The planner is almost free at 453. Our own chars/4 estimator
said 2,011 for a comparable question — it was wrong by 5.7×, and we only found that by instrumenting
it.

**"So what's your actual bottleneck?"** ✱
Not dollars — **throughput**. `gpt-oss-120b` is capped at 8,000 tokens per *minute* on the free tier,
and one single-specialist question exceeds that. When the budget runs out the client backs off
silently, so the app looks frozen. We diagnosed it by watching our own demo appear to hang. For a
multi-agent system the binding constraint is rate, not price — which is a different engineering
problem than the one we expected to have.

**"Isn't the multi-agent overhead just latency and cost you invented for yourselves?"**
Fair, and yes — 12–18 sequential calls and 30–60 seconds. We buy three specific things: enforced
scope boundaries, a provable constraint handoff, and a per-node audit trail. If you don't need
those, one model with a good prompt is cheaper and faster. The moment you need to prove *why* an
answer was safe, you need the structure.

---

# PART 4 — FACT SHEET

Verified against the repo on **2026-08-07 (evening revision)** — git history, `src/`, `app.py`, live
`chroma_db/`, and a live orchestrator run. ✱ = new or corrected in this revision.

| Fact | Value |
|---|---|
| Specialist agents | 4 — 🦴 surgeon · 🩺 PT · 🏋️ trainer · 🥗 nutritionist |
| Corpus | **90 documents** ✱ across 4 siloed collections — PT 40 · trainer 22 · surgeon 18 · nutrition 10 |
| Chunks | **1,886** ✱ — **PT 1,050** · trainer 536 · nutrition 179 · surgeon 121 |
| Visual assets (CLIP) | **279** ✱ — PT 112 · trainer 156 · surgeon 9 · nutrition 2 |
| Chunking / embeddings | ~1,000 chars, 150 overlap · `all-MiniLM-L6-v2`, 384-dim, local, CPU, free |
| Retrieval | top-k cosine, k=6, per-agent collection |
| **LLM — specialists, synthesis** | **Groq `openai/gpt-oss-120b`**, temp 0.2 ✱ |
| **LLM — router, planner, compliance** | **Groq `openai/gpt-oss-20b`**, `reasoning_effort="low"` ✱ |
| **Vision** | **Google `gemini-flash-latest`** — the only non-Groq call ✱ |
| Retired model | `llama-3.3-70b-versatile` — Groq retirement **2026-08-16**; migrated 2026-08-07 ✱ |
| **Groq calls, 4-specialist TEAM** | **12–18** ✱ — was 7–9 before the planner/tools |
| Groq calls, single specialist | ~3 (router + planner + consult) ✱ |
| Groq calls, RED_FLAG | **0** |
| **⚠️ Free-tier PER-MINUTE cap** ✱ | **8,000 tokens/min on `gpt-oss-120b`** — verified from `x-ratelimit-limit-tokens`. **The binding constraint, not the daily cap.** Groq *stalls* rather than rejecting, so this raises **no 429** — only latency |
| **Measured, 3-specialist TEAM** ✱ | **204.8 s · 14 calls · 38,141 tokens · 0 recorded 429s.** Worst stages: `extract_constraints:nutrition` 34.7 s, `consult:nutrition` 30.6 s (vs `consult:surgeon` 1.1 s unthrottled) |
| Free-tier daily cap | 200,000 tokens/day — verified by hitting it |
| **Measured cost, single specialist** ✱ | **11,564 real tokens / 6 calls** — consult 3,643 · synthesize 2,641 · extract_constraints 2,475 · compliance 1,364 · route 988 · plan 453 |
| **Estimator error** ✱ | The app's chars/4 heuristic logged a comparable question at **2,011** — understates by **~5.7×** on the cheapest route |
| **Telemetry** ✱ | `src/telemetry.py` — LangChain callback on both ChatGroq clients; real usage, latency, and 429s per pipeline stage into an `llm_calls` table; surfaced in the app's **Observability** tab |
| Token pricing ✱ | **VERIFIED 2026-08-08** against console.groq.com: `gpt-oss-120b` **$0.15/1M in · $0.60/1M out**; `gpt-oss-20b` **$0.075/1M in · $0.30/1M out**. The old $0.59/$0.79 was Llama-3.3-70B and is gone from the code (`src/business/pricing.py` is now the only place a price lives) |
| **Measured cost to serve** ✱ | **$0.0024** single-specialist · **~$0.009** TEAM — against $0.12/question overage, i.e. **~98% gross margin**. Cost is NOT the constraint |
| **The real constraint** ✱ | **Two** free-tier caps. **8,000 tok/min** = latency (one TEAM question = 4.8 min of the whole account's budget → the 3m25s stall). **200,000 tok/day** = volume, and it BINDS: ~5.2 TEAM questions/day, **157/month for the whole account** = **1 Recovery subscriber, $45/mo ceiling**. A TPM-only model overstates capacity ~58× — do not use one |
| **Production stack (D35)** ✱ | Economics are modelled on **Sonnet 5** ($3/$15) specialists + **Haiku 4.5** ($1/$5) orchestration, applied to measured token counts. TEAM question **$0.0092 → $0.185 (~20×)**. Plans re-derived at a 75% margin target: **Free $0/10, Recovery $45/100, Clinic $225/500** (both paid clear 77.6%). The old $19/250 plan would run at **−32% margin**. Projected, not metered — ±20–30%, disclosed on every screen |
| Monetization ✱ | Accounts (scrypt, stdlib), Free/Recovery $19/Clinic $99 with overage, quota enforcement, admin-only business console at `pages/1_Business_Dashboard.py`. **Nothing is charged**; invoices marked `status='simulated'` |
| Specialist tools ✱ | 5 calculators + `search_my_corpus` + gated `search_pubmed`; **max 2 tool rounds** |
| PubMed gate ✱ | Schema not offered unless the agent's own retrieval returned empty — enforced in code |
| Plan bounds ✱ | `MAX_PLAN_LENGTH = 4`, de-duplicated, sanitized against hallucinated agent names |
| Peer back-channel ✱ | `MAX_CONSULT_ROUNDS = 1` — one round-trip, straight-through node, DAG preserved |
| Conversation memory ✱ | ≤6 prior turns, resolved to a standalone question **before** routing |
| Constraint extraction | runs after surgeon, PT, nutritionist — **not** the trainer *(wasted call fixed this revision)* ✱ |
| Compliance check ✱ | Re-verifies the answer vs. every constraint; distinguishes `checked: False` from clean |
| TEAM chain order | **LM-planned** ✱ (was hardcoded most-restrictive-first); inversions detected and logged |
| Red-flag confidence | 0.97, regex, pre-model |
| **Test suite** | **74 test functions across 10 modules** ✱ (was 44); 9 marked `live` and excluded from push/PR CI — split by *cost*, not scope |
| **Routing battery** | **15/15**, run live 2026-07-18 — ⚠️ **predates the model migration and the planner** ✱ |
| High-risk stress tests | ⚠️ **Old "100% pass" is not trustworthy** — the judge scored 5/5 PASS on exception. Fixed to score 0 / `ERROR`. Re-run before quoting. ✱ |
| GraphRAG | ⚠️ **Kùzu not installed on this machine — falls back to in-memory data** ✱ |
| Guardrails | Wired into `src/cli.py` only, not `app.py` |
| `llm-guard` | Evaluated and **rejected** — would downgrade `transformers` and break retrieval + CLIP ✱ |
| Persistence ✱ | `src/database.py` — SQLAlchemy/SQLite, WAL + foreign keys, one row per turn; sessions reopenable from the sidebar, save failures surfaced not swallowed (D31, Evan PR #10) |
| Licensing | US-gov public domain; NHS under OGL v3.0; provenance in `data/SOURCES.md` |

---

## Open items before we present

- [ ] **⚠️ Check the Groq token budget** and decide whether to upgrade tiers for the presentation
      window. At 12–18 calls per TEAM question, the free tier is ~a dozen consults/day. **Highest
      priority — this is the one that can kill the live demo.**
- [x] ~~Verify all four Chroma collections are non-empty~~ — done: PT 1,050 · trainer 536 ·
      nutrition 179 · surgeon 121 = **1,886**. Still re-check the morning of; `pt_docs` vanished once.
- [ ] **`pip install kuzu`** or correct slide 11's GraphRAG claim.
- [ ] **Look up current gpt-oss token pricing** — the deck must not carry the Llama-3.3 numbers.
- [ ] **Re-run the 15-question routing battery** on the new model + planner, or present it as
      "verified in July on the previous model." Budget the tokens.
- [ ] **Re-run the high-risk scenario suite** now that the judge no longer fails open — then decide
      whether the number is quotable.
- [x] ~~Regenerate the architecture diagram~~ — done (`1f90e94`). Still needs cropping or splitting
      before it goes on a projected slide; see 0.8.
- [x] ~~Decide the unit-economics call~~ — **shipped.** `src/telemetry.py` captures real per-call
      usage; slide 14 and demo beat 8 now use measurements. Two values still `— TBD —`: dollar cost
      per route (needs gpt-oss pricing, see 0.2) and the human-consult ROI figure. ✱
- [ ] **⚠️ Upgrade the Groq tier for the presentation window** — the per-minute cap (0.3b), not the
      daily one, is what will stall the live demo. Highest-priority spend. ✱
- [ ] Consider `k=6 → k=3` for the demo run only — retrieved context dominates each consult's input
      tokens, so this roughly halves them. ✱
- [ ] Assign Speaker 1 / 2 / 3 to Evan, Ben, James, and confirm the demo driver.
- [ ] **One full timed rehearsal — the day before, not the morning of** (token budget).
- [ ] Merge the stale-docs fix so `Capabilities_Overview.md` and `PROJECT_PLAN.md` don't contradict
      the deck if a TA reads the repo.
- [ ] **Pre-seed a saved conversation the morning of** so demo beat 6 has something to reopen. ✱
- [ ] **Re-time the demo — it grew.** Persistence added beat 6 (~40s) and pushed everything after it
      later. The 6:00 target still holds on paper but has not been rehearsed end to end at this
      length. ✱
