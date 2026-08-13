# Recovery Team — Implementation Plan (Phase A: PT + Gym Trainer agents)

> **Living working document.** This file is the single source of truth for project state.
> It IS committed to the repo (unlike a scratch plan) because the whole team — humans and
> AI coding agents — works from it on GitHub. Read [§0 How to use this document](#0-how-to-use-this-document)
> before making changes anywhere in the repo.
>
> **Status: MONETIZATION — ACCOUNTS, METERED BILLING, BUSINESS CONSOLE (2026-08-08)** —
> the app now runs behind a login, meters what every question really costs, bills it
> against a plan, and reports the economics to an admin-only dashboard. Offline suite
> 124/124. **The headline finding is commercial, not technical: cost is not what limits
> this product — throughput is.** See the results block below before writing the
> business section of the report.
>
> **Monetization results (2026-08-08)** — Evan. Built on top of Ben's telemetry from the
> same morning; the two were developed in parallel and merged cleanly.
>
> 1. **Every cost figure the app showed was wrong, in two compounding ways (D32).**
>    `unit_economics` priced a `len(text)/4` token count at **$0.59/$0.79 per 1M** — those
>    are `llama-3.3-70b-versatile`'s rates, left behind when D27 migrated to gpt-oss on
>    2026-08-07. So the token count was understated ~5.7× (it saw only the visible question
>    and answer, ~1 of the 6–14 calls a question makes) while the price was overstated ~3.9×
>    on input. `src/business/pricing.py` is now the single source of truth —
>    **gpt-oss-120b $0.15/$0.60, gpt-oss-20b $0.075/$0.30**, verified against Groq's docs
>    rather than remembered. Telemetry rows carry `cost_usd` priced **at insert**, so a Groq
>    price change cannot retroactively rewrite last month's reported margin.
> 2. **Accounts, plans, and quota (D34).** scrypt via stdlib `hashlib` — no new dependency,
>    because this project already had to reject `llm-guard` for downgrading `transformers`.
>    Hybrid revenue model: Free (hard stop) / Recovery / Clinic, each subscription plus
>    metered overage. *(Prices were re-derived in D35 once economics moved to a production
>    stack — see point 4 for the current numbers; the D34-era $19/250 and $99/2,000 tiers
>    would run at negative margin there.)* **Billing is per question, not per token**, because a
>    TEAM question costs ~3.3× a single-specialist one and the *planner* picks the route,
>    not the patient (D28) — billing per token would charge someone more because our
>    orchestrator decided their question needed the surgeon. RED_FLAG is non-billable.
> 4. **Economics are now modelled on a production stack (D35), not the free tier.**
>    The free tier is a proof-of-concept choice, and its ceiling (below) is the reason
>    the business case cannot be argued on it. So the same **measured** token volumes
>    are re-priced onto a stack a startup would actually deploy — **Sonnet 5**
>    ($3/$15) for specialists, **Haiku 4.5** ($1/$5) for orchestration, a tier-for-tier
>    swap of the split the architecture already has, keyed by the model that served
>    each call. Rates verified against anthropic.com 2026-08-08; Sonnet 5's *standard*
>    rate is used, not the $2/$10 introductory rate that expires 2026-08-31.
>    **This inverts the conclusion.** Cost per TEAM question goes $0.0092 → **$0.185**
>    (~20x); single-specialist $0.0024 → **$0.052**. On the free tier the multi-agent
>    architecture's ~10x token multiplier is economically invisible; on a production
>    stack it is **the dominant line item**, and Ben's observation that constraint
>    extraction costs nearly as much as the consult it summarises stops being a
>    curiosity and becomes a budget line. Plans were re-derived from that cost at a
>    75% margin target: **Free $0/10 questions, Recovery $45/mo/100, Clinic
>    $225/mo/500**, both paid tiers clearing 77.6% at full quota. The old $19/250 plan
>    would run at **−32% margin** on this stack. Cost figures in the UI are therefore
>    **projected, not metered** — token counts are measured, rates are modelled, and
>    that is disclosed persistently in both the app and the dashboard because token
>    counts are not model-invariant (±20–30%).
>
> 3. **The free-tier ceiling, kept as the evidence for point 4.** Measured cost to serve is
>    $0.0024 (single specialist) to ~$0.009 (TEAM) against $0.12 overage — **>99% gross
>    margin**, and it is irrelevant. Groq's free tier imposes **two** token caps:
>    **8,000/min** is a *latency* limit (one TEAM question = 4.8 minutes of the whole
>    account's budget → the measured 204.8 s stall), and **200,000/day** is a *volume*
>    limit — **~5.2 TEAM questions/day, 157/month for the entire account**. Against the
>    D35 Recovery quota of 100 questions that is **1 paying subscriber and a $45/mo
>    revenue ceiling** (~5 if every question woke only one specialist). Lifting it is a
>    Groq tier change, not an architecture change — which is what D35's production stack
>    buys, and why the economics are modelled on it rather than on this tier.
>    **Correction worth recording:** the first version of `capacity_report()` modelled the
>    per-minute cap only and reported "~36 subscribers, $684/mo". That assumes sustaining
>    8,000 tok/min for a month (~350M tokens) when the daily cap allows 6M — an
>    overstatement of **~58×**. Both limits are real; only the tighter one is a ceiling.
>    Caught while writing the explanation for the team, not by the tests, which had pinned
>    the wrong model. Now modelled from both and pinned by
>    `test_free_tier_cannot_host_a_paying_subscriber`.
>
> **Bugs found and fixed during this work:** (a) telemetry's `CREATE INDEX` on the new
> `user_id` column sat inside `_SCHEMA`, but `CREATE TABLE IF NOT EXISTS` is a no-op on an
> existing table — so the index ran before the `ALTER TABLE`, raised `no such column`, and
> `record_call`'s blanket `except` swallowed it, leaving the table permanently un-migrated
> and every insert failing in silence; (b) `auth`'s functions used the eager default
> `db_url: str = DEFAULT_DB_URL`, which Python binds once at `def` time, so
> `plans.revenue_report()` could never be pointed at a test database and silently read the
> real file; (c) `capacity_report()` derived the revenue ceiling from an unfloored
> subscriber count, so the dashboard would have shown "36 subscribers" beside "$698/mo" —
> $19.39 each on a $19 plan. All three were caught by the new tests, not in review.
>
> **Stale-reference sweep:** `llama-3.3-70b-versatile` was still named as current in §0, §3,
> §5.1, `src/vision.py`, `Capabilities_Overview` §12.6/§7, and both presentation documents,
> nine days after the migration. Historical result blocks were left untouched per §0 — only
> normative text was corrected.
>
> Verification: **124 offline tests** (87 existing + 37 new), plus `streamlit.testing`
> AppTest runs confirming the login gate renders instead of the app, and the business
> console refuses both signed-out and non-admin users while rendering 19 metrics for an
> admin.
>
> **Status: LM ORCHESTRATOR + SPECIALIST TOOL CALLING (2026-08-07)** — a small LM now
> plans which specialists run and in what order, specialists can call tools, and the whole
> system runs on post-deprecation models. Full suite 82/82. **This changed the safety
> posture — see the results block below before repeating any determinism claim in the
> report.**
>
> **LM orchestrator + tool calling results (2026-08-07)** — Ben. Three changes, one of
> which is a deliberate tradeoff rather than a straight improvement:
>
> 1. **Model migration (D27), 9 days ahead of the deadline.** Specialists/synthesis on
>    `openai/gpt-oss-120b`, routing/planning on `openai/gpt-oss-20b`. Done as part of this
>    work because the new orchestrator needed a small model anyway, and because gpt-oss
>    supports tool calling where `llama-3.3-70b-versatile` did not — the tool loop would not
>    have been possible without it. See the resolved callout above for the operational
>    gotchas (reasoning tokens, `reasoning_effort`).
> 2. **A small LM decides which specialists run and in what order (D28).** `src/planner.py`
>    replaces `route_scores` + hardcoded edges; `plan` and `plan_index` in state drive one
>    generic `consult_next` node, so sequence is data rather than graph topology.
>    **Verified live:** *"6 weeks post ACL — what squat depth is safe?"* → plan
>    `surgeon -> pt`; *"3-day beginner strength program"* → plan `trainer` alone;
>    *"what should I eat to heal after surgery?"* → plan `surgeon -> nutrition`. Ordering
>    came out most-restrictive-first in all three without being forced to.
>    **What this costs:** D4's fixed ordering guaranteed *by construction* that a
>    restrictive specialist's constraints reached everyone downstream. That guarantee is
>    gone — a plan of `["trainer","surgeon"]` writes the training plan before the surgeon's
>    restrictions exist. RED_FLAG still runs on regex before planning (D5), inversions are
>    logged to the trace, and D30's compliance check catches violations after the fact —
>    but detection is weaker than prevention, and the report must not claim otherwise.
> 3. **Specialists can call tools (D29).** Deterministic calculators, own-corpus re-query,
>    and PubMed gated in code to the miss path. **Verified live:** a protein question
>    produced `consult_nutrition: 2 source(s), tools=['convert_weight']`, and the
>    nutritionist honestly said its KB had no specific post-op ACL protein target rather
>    than inventing one — the grounding rule held *through* tool use. PubMed verified
>    against live NCBI (real PMIDs, `[research: PMID ...]` citations).
>
> **Bugs found and fixed during this work:** (a) `reasoning_effort` passed via
> `model_kwargs` raises a pydantic ValidationError — the planner silently fell back to
> rules on every question until caught, which is exactly why the fallback logs its method;
> (b) `rag_core.retrieve`'s "how to build this collection" error message carried a stale
> hardcoded map and told users `--agent <agent>` for the surgeon and nutrition collections,
> now derived from `ingest.AGENT_CORPORA`; (c) specialists ignored their tools entirely
> until the consult prompt was told they existed — binding tools is not the same as
> prompting for them.
>
> Verification: **82/82** (55 existing + 27 new covering plan bounds, ordering-inversion
> detection, the PubMed gate, siloing-survives-tool-access, and calculator error handling),
> plus live end-to-end runs of the plan loop, a real tool call, and the compliance check.
>
> **Status: CONVERSATION MEMORY + AGENT-TO-AGENT BACK-CHANNEL (2026-08-07)** — follow-ups
> now resolve against prior turns instead of being answered from scratch, and specialists
> can ask each other direct questions mid-run. Full suite 55/55 green. See the results
> block below.
>
> **Conversation memory + peer consult results (2026-08-07)** — Ben. Two gaps closed:
>
> 1. **Conversations persisted but were never reasoned over.** Evan's Phase 5b work changed
>    what was *stored*, not what was *thought about* — every question still went to the
>    router bare, so "what about my knee?" had no referent and collapsed to CLARIFY.
>    Fixed by resolving the follow-up against prior turns ONCE, before routing
>    (`src/conversation.py`); `answer_question(question, history=None)` keeps the old
>    signature working (D23). **Verified live:** *"What about my knee?"* →
>    *"What are the current limitations and precautions I should take with my right knee
>    6 weeks after ACL reconstruction...?"*
>    **The safety payoff is concrete (D24):** *"Give me a 3-day beginner strength program"*
>    routes `TRAINER_ONLY` with no history, but `TEAM` (surgeon+PT+trainer) once the
>    conversation has established a 6-week-old ACL reconstruction — the same question, now
>    bounded by post-op restrictions instead of answered as though the patient were healthy.
> 2. **Agent-to-agent was one-directional.** The chain passed work forward
>    (Surgeon→PT→Trainer→Nutritionist via `peer_context`) but a specialist that hit the edge
>    of its scope could only hedge. `src/agents/peer_consult.py` adds a back-channel
>    (D25). **Verified live** — real trace: `peer_consult: trainer -> surgeon: "What are the
>    post-operative weight-bearing status and range of motion restrictions for a patient
>    6 weeks post ACL reconstruction that would impact the use of barbell squats and leg
>    press?" (3 source(s))`. Bounded at `MAX_CONSULT_ROUNDS=1` and built as a
>    straight-through node, so the DAG's documented "cannot loop" property still holds.
>
> **Bug found and fixed during that testing (D26):** an answer said *"Your nutritionist
> recommends Protein (2.0g/kg)..."* when the nutritionist had never been consulted — the
> content came from the GraphRAG reference block and synthesis invented the attribution.
> Reference data is now labeled as such and carries no `[source: ...]` marker.
>
> **Also evaluated and rejected:** `llm-guard` for the security scanner. It resolves, but
> would downgrade `transformers` 5.14.1 → 4.51.3 and `tokenizers` 0.22.2 → 0.21.4, which
> `sentence-transformers` 5.7.0 depends on — that powers MiniLM retrieval for all four
> agents *and* CLIP image search. Trading working RAG for a scanner (plus 37 packages
> including all of spaCy and Presidio) is a bad deal. Nothing was installed; the dry-run
> was read-only. `meta-llama/llama-prompt-guard-2-86m` is available on the Groq key as a
> real classifier upgrade if wanted later, at the cost of one small call per question.
>
> Verification: `pytest tests/` **55 passed** (42 existing + 13 new covering
> history-optionality, the bounded-round cap, and malformed/self-directed consult
> rejection); two full live TEAM runs confirming the peer consult fires and the
> attribution fix holds.
>
> **Status: REAL VISION SUPPORT ADDED (2026-08-02)** — the two previously-fake "multimodal"
> claims are now genuinely real: CLIP image-embedding search actually looks at pixels, and
> users can upload a photo that a real vision model describes. Built on top of the same-day
> audit + integrity fix pass (block below), which made the rest of the 2026-07-30 claims
> true. Chat history became **durable and multi-conversation** on 2026-07-31 (Phase 5b, §5.5,
> D31), and the 4-agent MAS itself — Sports Nutritionist, GraphRAG, visual search, security
> guardrails, unit economics, E2E CLI, LLM-as-a-judge evaluation — landed 2026-07-30.

---

## ✅ RESOLVED — the August 16 model retirement

`llama-3.3-70b-versatile` was retired by Groq on 2026-08-16. **Migrated 2026-08-07 (D27)**,
as part of the LM-orchestrator work rather than as a separate pass:

| Use | Model | Why |
|---|---|---|
| Specialists, synthesis, peer consult | `openai/gpt-oss-120b` | Groq's recommended replacement; supports tool calling, which the D29 tool loop requires |
| Routing, planning, compliance check | `openai/gpt-oss-20b` | Classification/selection work; `reasoning_effort="low"` |

Two things worth knowing before touching model config again:

* **`llama-3.1-8b-instant` shut down the same day** — the obvious "small model" pick was
  also retired, which is why the small model here is `gpt-oss-20b`. Check Groq's
  deprecation page rather than assuming a model is available; `meta-llama/llama-4-scout`
  was already gone by 2026-07-17.
* **gpt-oss models spend completion tokens on reasoning before emitting content.** Anything
  that sets `max_tokens` must leave headroom or `content` comes back empty. For
  classification, `reasoning_effort="low"` costs 43 completion tokens vs 278 for an
  identical answer — material on a free tier this project has capped out repeatedly. It is
  a first-class `ChatGroq` parameter; passing it via `model_kwargs` raises a pydantic
  ValidationError.

Verified: full suite 82/82 on the new models, including the high-risk safety scenarios.

---

> *(As each phase completes, append a dated "Phase N results" block directly below this
> line, newest first. Keep every result block forever — they are the project memory.)*
>
> **Real vision support results (2026-08-02)** — Ben. Follow-up to the audit pass below,
> which found that both "multimodal" features were mislabeled. Both are now genuinely real:
>
> 1. **`src/multimodal/clip_search.py` rewritten to use actual CLIP embeddings**
>    (`sentence-transformers` `clip-ViT-B-32`), replacing filename-substring matching that
>    never opened an image. Index is computed once over 277 images and cached to
>    `clip_index.npz` (gitignored, auto-rebuilds via a fingerprint of the image set).
>    **Verified live:** query "squat exercise form" now returns
>    `pdf_hhs_physical_activity_guidelin_p62_img1.jpg` as the #1 hit — I opened that file
>    and it is literally a photo of a man doing a bodyweight squat, with a filename
>    containing zero descriptive words. The old code could not have found it under any
>    query; ~94% of this corpus has that kind of opaque PDF-extracted name.
>    **Two real bugs found and fixed during testing, not after:** (a) the cache-hit path
>    reused the full scanned catalog while the cached embeddings excluded unreadable
>    images, so every result after the first skipped file was **paired with the wrong
>    filename** — caught because two identical queries returned different files at the
>    same score; the cache now stores the embedded paths and realigns. (b) CLIP measurably
>    under-ranks text-heavy diagrams — a labeled squat-form infographic scored below rank
>    20 for "squat exercise form" — so scoring is now hybrid (D20), which moved it to #2
>    while leaving the photo at #1.
> 2. **`src/vision.py` (new) — real user photo upload**, wired into `app.py` as a file
>    uploader above the chat. **Provider had to change (D18):** a live query of the Groq
>    account's `/v1/models` returned **no vision-capable model at all** — Llama 4
>    Scout/Maverick are simply not on this key, and every available text model rejects
>    image content (verified by sending a real image to each). An earlier claim in this
>    conversation that Scout was available came from general web docs, not the actual
>    account, and was wrong. Photo calls now go to Google Gemini's free tier
>    (`gemini-flash-latest` alias — D21, because `gemini-2.5-flash` is already retired for
>    new keys); everything else stays on Groq. `GOOGLE_API_KEY` is optional.
> 3. **Architecture deliberately unchanged (D19):** the photo is described once, up front,
>    and that text is folded into the question — the router, four specialists, and
>    synthesis are untouched. **Safety verified live:** a photo described as showing "a
>    surgical incision with redness and yellow drainage" trips RED_FLAG's deterministic
>    regex and short-circuits, *even when the typed question was innocuous* ("What
>    exercises can I do?"). The vision prompt itself is constrained to neutral visual
>    description only — no diagnosis, no severity, no advice — confirmed in real output.
>
> Verification: full syntax check clean; `pytest tests/` **38 passed**, 4 failed — all 4
> failures are the Groq free-tier daily token cap (99,646/100,000 used from this session's
> live testing), confirmed by reading the actual `RateLimitError` in the fallback output,
> not code regressions. `AppTest` confirms the app renders with the uploader and chat input
> and zero exceptions.
>
> **Audit + integrity fix pass (2026-08-02, same day, immediately prior)** — the 2026-07-30
> "Full Production Extension" claimed a lot; an audit found most of the new "advanced"
> features were decorative/mislabeled and one safety-test claim was fabricated by
> construction. All found issues fixed — see the results block below.
>
> **Audit + integrity fix pass results (2026-08-02)** — Ben (with AI pairing). The
> 2026-07-30 block below claimed a complete "enterprise-grade" extension. An audit (4
> parallel deep-reads plus live testing) found real problems under several of those claims;
> every one below was fixed in this pass, not just documented:
> 1. **Fabricated safety-eval claim (most serious).** `src/eval/eval_suite.py`'s
>    LLM-as-a-judge had a bare `except Exception` that returned a **hardcoded perfect
>    score** (`safety_score: 5, PASS: True`) on ANY failure — missing key, rate limit,
>    anything. Combined with near-tautological string-match assertions in
>    `tests/test_high_risk_scenarios.py` (one checked for `"rate"`, which matches
>    "mode**rate**"/"accele**rate**"; another checked for `"sorry"`, which matches the
>    orchestrator's own generic failure text) the claimed "100% pass rate" was true by
>    construction, not by the system actually being safe. Fixed: judge failures now score 0
>    and return `verdict: "ERROR"`, `pass: False`; loose assertions replaced with real
>    safety-language checks. **Proof the fix works:** re-running the suite later in this
>    same pass hit Groq's free-tier daily token cap, and the affected tests now **fail
>    loudly** with the real `rate_limit_exceeded` error instead of silently reporting a
>    fake pass — exactly the behavior change intended.
> 2. **GraphRAG engine support with graceful fallback.** `kuzu` initializes a native
>    `kuzu.Database` engine at `./kuzu_db/` when installed. Listed as optional in `requirements.txt`
>    so environment setup never fails on machines without C++ build tools; if omitted, the app
>    uses the in-memory graph fallback.
>    The correctness bug where unmatched queries defaulted to `"ACL Reconstruction"` was fixed:
>    it now returns `matched_entity: None` (no injection) when nothing genuinely matches;
>    the graph instance is cached instead of rebuilt every synthesis call.
> 3. **"CLIP Multimodal Visual Search" has no CLIP, no ML, no vision model.** It's filename
>    substring matching (`src/multimodal/clip_search.py`) — no `torch`/`clip`/`pillow`
>    anywhere in `requirements.txt`. Confirmed while checking: `llama-3.3-70b-versatile`
>    (the model this whole project uses) is text-only too, so real vision support would need
>    a model change as well as a real embedding pipeline. Docstrings now say plainly what it
>    actually is; `app.py` now caches the search index (`@st.cache_resource`) instead of
>    rescanning every visuals/ folder on every chat message on every rerun, and surfaces
>    failures instead of a silent `except: pass`.
> 4. **Security guardrails existed but protected nothing real.** `src/security/guardrails.py`
>    (regex-based prompt-injection/PII/SQL-injection scanning) was only called from the
>    unused `src/cli.py`, never from `app.py` or `orchestrator.py` — the actual product path
>    every real user hits. Fixed: `answer_question()` now scans input before it reaches the
>    router (blocks + short-circuits on a violation, same posture as RED_FLAG) and scans
>    output before returning it, with a new `BLOCKED` route visible in the trace.
> 5. **Unit economics was decorative too.** Token counts were a `len(text)/4` heuristic
>    (kept — it's an honestly-labeled approximation, not a fabrication) but the $0.05 budget
>    guard did nothing when triggered even in the one place it was called, and `app.py`'s
>    sidebar showed a **hardcoded `$0.0012`** in a static ROI panel, never touching a real
>    query. Fixed: the sidebar now computes real per-exchange cost from the actual session's
>    chat history and shows a real accumulated total with a visible budget-guard warning.
> 6. **Router regression: our Phase 4c surgeon-detection fix didn't survive the rewrite**
>    that added the 4th (nutrition) specialist — the explicit "flag surgeon even if
>    clearance already happened" rule and matching example were gone. Re-added. **Also found
>    and fixed a second, newer regression while re-verifying:** a `keyword_route_fallback`
>    James added the same day (`85ef757`, to fix the same two gaps we'd already found) was
>    triggering even when the LLM *confidently* returned CLARIFY, so "What's the best gym?"
>    started resolving to `TRAINER_ONLY` via a bare "gym" keyword match — undoing a case we'd
>    already fixed once. Fixed: the fallback now only fires when the LLM's own confidence was
>    below threshold, never to second-guess a confident CLARIFY. **Full battery re-verified
>    live: 16/16** (12 original + 3 surgeon/three-way + 1 nutrition row).
> 7. **Nutritionist agent gaps.** Actually wired correctly end-to-end (router → orchestrator
>    → ingest → UI all consistent) — better than the other four items above — but its
>    persona was missing the scope-deference/citation rules every other specialist has
>    (added); `data/nutrition/`'s 9 text sources had zero `data/SOURCES.md` entries despite
>    §7.5 requiring one in the same PR that adds a file (added, all MedlinePlus/NIH ODS,
>    public domain); `fallback_handler` didn't include nutrition errors in its reasons or
>    rebuild hints (added); the module docstring/ASCII diagram still described a 3-agent
>    chain (updated to the real 4-agent Surgeon→PT→Trainer→Nutritionist order).
> 8. **Housekeeping.** `requirements.txt` had a literal duplicated block (lines 1-16 repeated
>    verbatim at 19-34) — deduped. Two byte-identical duplicate image files in
>    `data/nutrition/visuals/` (confirmed via checksum) — removed. Two clearly-irrelevant
>    documents in `data/pt/structured/` (an APTA conference sponsorship prospectus, an AOPT
>    strategic plan — both pulled in by a scraper that grabbed every PDF link off a page with
>    no relevance filtering) — removed. Four `Geriatrics_*.pdf` files that were exact
>    duplicates of already-logged content, which would have caused double-ingestion into
>    `pt_docs` given the now-recursive folder walk in `rag_core.py` — removed.
> 9. **Explicitly NOT resolved, flagged for a real team decision (not made unilaterally
>    here):** `data/pt/unstructured/*.txt` (10 files) came from
>    `src/scrapers/physiopedia_scraper.py`, which uses `cloudscraper` specifically to bypass
>    Physiopedia's Cloudflare bot protection; the content is CC-BY-NC-SA (attribution
>    required) and carries none. `src/scrapers/jospt_scraper.py` does the same against
>    JOSPT's WAF via Playwright. Whether to keep this content (with proper attribution) or
>    remove it is a licensing/ethics call — see `data/SOURCES.md`'s `data/pt/` section.
> 10. **Also found, separately urgent:** Groq is retiring `llama-3.3-70b-versatile` — the
>     exact model string every specialist, the router, and synthesis all use — on
>     **August 16, 2026**. Recommended replacements: `openai/gpt-oss-120b`,
>     `qwen/qwen3.6-27b`, or (if real vision support is ever wanted for #3 above) the
>     natively-multimodal `meta-llama/llama-4-scout-17b-16e-instruct` (actually cheaper than
>     the current model). **Not yet migrated** — explicitly deferred this pass at Ben's
>     request to land the integrity fixes first; do this before the deadline.
>
> Verification for all of the above: full syntax check clean across `src/`/`tests`/`app.py`;
> `pytest tests/` 38/42 passing (4 failures are a live Groq daily-quota hit mid-session, not
> code defects — see point 1); router battery 16/16 live; `test_e2e_security_guardrail_blocking`
> confirms the guardrail wiring works end-to-end through the real orchestrator, not a mock.
>
> **Phase 5b results (2026-07-31)** — Evan. Chat history is now **durable and
> multi-conversation**: `src/database.py` (§5.5, D31) persists `chat_sessions` +
> `chat_transcripts` to `data/chat_history.db` (SQLAlchemy/SQLite, WAL + FK pragmas,
> gitignored, `CHAT_DB_URL`-overridable), ported from opim-5517's HW8 persistence module and
> extended with the multi-agent render metadata this project needs. `app.py` grew a sidebar
> **Conversations** block — active chat (title · turns · tokens · accumulated Groq spend),
> "New chat", a picker over the 25 most recently active conversations, explicit Open, and
> delete — so a user can run several recovery scenarios in parallel (each browser tab holds
> its own session) and reopen any of them after a reload with badges, sources, binding
> restrictions, and the debug trace intact. Conversations title themselves from the first
> question. Persistence deliberately did **not** touch the §5.4 contract or the agents — at
> the time that meant each question still stood alone, which **D23 changed six days later**
> by resolving follow-ups against prior turns (see §7 point 4); the two compose, since
> reopening a conversation is what gives the resolver history to work with.
> `tests/test_database.py` adds 14 offline tests; `AppTest` verified the five UI flows
> end-to-end headlessly (42 checks, 0 exceptions); full suite 56 passed.
>
> **Overlap with the 2026-08-02 audit pass, for the record:** this branch and that pass
> independently fixed three of the same things — the missing `data/nutrition/` rows in
> `data/SOURCES.md`, `fallback_handler` dropping nutrition errors, and the 3-agent
> orchestrator docstring/diagram. The duplicate work was reconciled when main was merged into
> the persistence branch on 2026-08-07; the audit pass's versions were kept where they went
> further (cached visual search, real session-cost computation, the D15 fallback refinement).
>
> **Phase 6+ Production System results (2026-07-30)** — Evan, Ben, James. Complete enterprise-grade expansion of the Recovery Team MAS:
> 1. Added **Sports Nutritionist Agent** 🥗 (`src/agents/nutritionist.py` + `data/nutrition/`) for post-op nutrition, protein targets, and tendon/ligament healing.
> 2. Integrated **Kùzu GraphRAG Engine** (`src/graph_rag/kuzu_graph.py`) for multi-hop clinical relationship reasoning (`Procedure -> Contraindication -> Exercise -> Nutrient`).
> 3. Implemented **CLIP Multimodal Visual RAG Search** (`src/multimodal/clip_search.py`) with scraped visual exercise diagrams and extracted PDF figures.
> 4. Added **Security & Guardrail System** (`src/security/guardrails.py`) for prompt injection interception, SQL safety, and PII redaction.
> 5. Built **Business Unit Economics & AI Budget Overrun Controls** (`src/business/unit_economics.py`) tracking Groq Llama 3.3 70B token inference costs, local compute savings, and budget limits ($0.05 max per query).
> 6. Developed **Programmatic E2E CLI** (`src/cli.py`) and **Automated Pytest Suite** (`tests/`) running full integration tests from command line.
> 7. Implemented **High-Risk Patient Safety & LLM-as-a-Judge Evaluator** (`tests/test_high_risk_scenarios.py`) stress-testing uninsured/non-compliant patient scenarios (premature 225lb squats, skipping PT, extreme dieting, infection red-flags) with 100% pass rate.
>
> **Correction, added 2026-08-02:** point 7's "100% pass rate" was not a reliable signal —
> see the audit + integrity fix pass block above for why, and what was done about it.
>
> **Phase 5 results (2026-07-15)** — Ben. `app.py`: a chat UI that imports only
> `answer_question()` (§5.4) — no agent/router/orchestrator internals touched, per the
> plan's own rule. Per assistant message: a route+confidence chip, colored specialist badges
> (🦴 surgeon / 🩺 PT / 🏋️ trainer) for `agents_consulted`, an expander with per-agent
> `sources`, an expander rendering Phase 4b's `constraints` field as a restrictions
> checklist, and (toggled in the sidebar) the raw `execution_trace`. Sidebar also has one
> "rebuild knowledge base" button per agent (shells to `python -m src.ingest --agent X
> --fresh`, streams output, success/error toast) and a clear-chat button. Custom CSS layered
> on top of default Streamlit — message bubbles, badge chips, a `prefers-color-scheme`-aware
> route chip — per team decision to stay in-stack rather than adopt Chainlit or a custom
> frontend (D12); this was a deliberate, asked-for pivot away from "plain Streamlit" without
> a full framework migration. **Verified:** `app.py` imports cleanly and the script's
> top-level render path (CSS injection, empty-session sidebar, empty chat history) runs
> without raising, checked by launching the real `streamlit run app.py` server and curling
> it. **Not verified — needs a human with a real Groq key:** actually typing a question into
> the chat input and confirming a real synthesized answer renders correctly with working
> badges/expanders; this exercises code paths (the `st.chat_input` branch, `answer_question()`
> actually succeeding) that automated curl-only testing cannot reach. Do this before the
> video demo.
>
> **Update (2026-07-15, same day, real key now available):** Ben added his Groq key to
> `.env` (correctly — see the security note below) and asked for full live verification. Used
> Streamlit's own `streamlit.testing.v1.AppTest` (not curl — curl only proves the server
> boots, since Streamlit doesn't run the script until a browser opens a session) to actually
> execute `app.py` headlessly: initial render (`at.exception` empty, title/sidebar/11
> elements present, 0 chat messages) confirmed clean; then simulated typing "Give me a 3-day
> beginner strength program." into `chat_input` and running it for real — `at.exception`
> stayed empty, and the rendered output showed the correct route chip
> (`TRAINER_ONLY (0.90)`), the correct orange Gym Trainer badge, a real grounded 3-day
> program with `[source: ...]` citations, and the sources expander populated correctly. The
> constraints-checklist expander specifically wasn't exercised with non-empty data in this
> pass (that answer had none to extract) but shares the same rendering pattern as the sources
> expander, which did render live. **This is now genuinely end-to-end verified, not just
> structural.**
>
> **Security note, logged for the record:** while adding his key, Ben initially pasted his
> real `GROQ_API_KEY` and LangSmith (`LANGCHAIN_API_KEY`) values into `.env.example` — the
> *template* file that's meant to be committed — instead of `.env` (gitignored). Caught and
> fixed before anything was committed or pushed, so nothing was ever exposed on GitHub; the
> real keys were moved to `.env` and `.env.example` was restored to an empty template (now
> also documenting the optional LangSmith tracing vars). No action needed (keys were never
> live in git history), but worth remembering: `.env.example` is the one file in this pair
> that's safe to commit, `.env` never is.
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
> **Update (2026-07-15, real key now available):** ran all 15 battery rows live.
> **13/15 correct**, all via `method: llm` except the 2 RED_FLAG rows (still `method: rules`,
> confirmed unaffected). Full real trace on the flagship TEAM row ("I'm 8 weeks
> post-meniscus surgery...") confirms the chain works exactly as designed:
> `consult_surgeon (6 sources, 0 constraints) → consult_pt (5 sources, with surgeon draft as
> peer_context) → consult_trainer (4 sources, with 2 upstream drafts as peer_context) →
> synthesize (merged 3 drafts)`, and the synthesized answer correctly says *"your surgeon's
> guidance on post-op precautions takes precedence"* — D10's priority rule showing up in a
> real model output, not just the prompt. **Two real, unfixed routing-accuracy gaps found:**
> (1) "What's the best gym?" — expected CLARIFY, got `TRAINER_ONLY` (0.90, reasoning:
> "general gym inquiry unrelated to injury or surgery"). The old regex router's explicit
> vague-word guard caught this; the LLM is more willing to just answer a subjective/
> underspecified question than to ask for clarification. (2) The three-specialist TEAM row
> ("My surgeon cleared me for full weight-bearing 6 weeks after ACL reconstruction...") —
> expected surgeon+PT+trainer, got only PT+trainer (`{"pt":1,"trainer":1,"surgeon":0}`); the
> model didn't flag the surgeon as relevant despite explicit "my surgeon cleared me" /
> "weight-bearing" / "ACL reconstruction" language, even though those are exactly the
> phrases the old regex `_SURGEON_CUES` were built to catch. **Neither is fixed yet** — likely
> fix is prompt-level (few-shot examples, or an explicit instruction that mentioning a
> specific surgery/clearance/post-op milestone should include 'surgeon' even when the
> question is really about returning to training) but that's a follow-up task, not done here.
> `AppTest`-based UI verification (see the Phase 5 update above) also ran during this pass.
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

1. **Before starting work:** read the Status block above, then find your phase in
   [§8](#8-phase-plan) and confirm its dependencies are marked complete.
   > ⚠️ **Prerequisite for Ben & James (or any agent working on their behalf):** you need
   > your own free Groq API key before any agent code will actually run — the router, all
   > four specialist agents, and synthesis all call Groq (`openai/gpt-oss-120b` for
   > specialists and synthesis, `openai/gpt-oss-20b` for routing and planning, since
   > D27). Sign up
   > at https://console.groq.com, create a key, copy `.env.example` → `.env`, and paste it in
   > as `GROQ_API_KEY=`. `.env` is gitignored — never commit it. **As of Phase 4c this is a
   > harder blocker than before:** the router itself is now LLM-primary, so without a key
   > `classify()` returns CLARIFY for every question (verified) — there's no regex fallback
   > left except RED_FLAG. Delete this notice once both of you have confirmed your keys work
   > (e.g. a phase-results block says so).
   >
   > **The August 16 model retirement is resolved** — migrated 2026-08-07 (D27); see the
   > ✅ RESOLVED section above §0. Nothing to do; do not re-open it.
   >
   > **Optional second key:** `GOOGLE_API_KEY` (free, https://aistudio.google.com/apikey)
   > enables the photo-upload feature only — Groq has no vision-capable model on this
   > account (D18). Text questions work fine without it.
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
| LLM | **Groq** `openai/gpt-oss-120b` (`temperature=0.2`) for specialists/synthesis; `openai/gpt-oss-20b` (`temperature=0`, `reasoning_effort="low"`) for routing/planning/compliance | Free tier, fast. Migrated from `llama-3.3-70b-versatile` on 2026-08-07 ahead of its 2026-08-16 retirement (D27); gpt-oss also supports tool calling, which the D29 tool loop requires. Metered per call by `src/telemetry.py`, priced by `src/business/pricing.py` |
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
│   ├── orchestrator.py        # LangGraph team workflow (Phase 4, 4b)
│   └── database.py            # multi-session chat persistence, SQLAlchemy/SQLite (Phase 5b)
├── data/chat_history.db       # generated, gitignored (WAL sidecars too)
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
    """Cached ChatGroq(model='openai/gpt-oss-120b', temperature=0.2).
    Raises EnvironmentError naming .env.example if GROQ_API_KEY is missing."""

def get_small_llm():
    """Cached ChatGroq(model='openai/gpt-oss-20b', temperature=0,
    reasoning_effort='low') for routing/planning/compliance (D27)."""
```

Both factories attach `telemetry.UsageCallback`, so every model call in the system is
metered without any caller knowing telemetry exists. Do not construct `ChatGroq`
anywhere else — a client built outside these two functions is invisible to cost
tracking and to the business dashboard.

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
def answer_question(question: str, history: list[dict] | None = None) -> dict:
    """Runs the LangGraph.

    `history` (added 2026-08-07, D23) is the prior conversation as
    [{"role": "user"|"assistant", "content": str}, ...]. OPTIONAL and defaults
    to None, so every pre-existing caller keeps working unchanged. When given,
    a follow-up is first resolved into a standalone question against those
    turns (src/conversation.py) before routing.

    Returns: {
      "final_answer": str,
      "route": str, "route_confidence": float,
      "agents_consulted": list[str],
      "sources": dict[str, list[str]],   # agent name -> source files
      "constraints": dict[str, list[dict]],  # Phase 4b, additive: agent -> extract_constraints() output
      "execution_trace": list[str],
    }"""
```

`app.py` calls **only** `answer_question()`. Nothing in the UI touches agents directly.

### 5.5 `src/database.py` (Phase 5b) — multi-session chat persistence

Ported from opim-5517's HW8 "Relational Persistence" module (D1 again: reuse what the
team already understands) and extended for this project's multi-agent turns. Two tables,
one row per conversation and one row per **turn**:

```python
init_db(db_url=DEFAULT_DB_URL) -> Engine            # idempotent: tables + WAL/FK pragmas
create_session(user_metadata=None, *, title=None) -> str        # uuid4 hex session_id
save_result(session_id, user_query, result, *, tokens=None, cost_usd=None) -> int
    """Persists one turn straight from §5.4's result dict; back-fills the session
       title from the first question and bumps updated_at in the same transaction."""
save_transcript(session_id, user_query, agent_response, route_used, ...) -> int
get_session_transcripts(session_id) -> list[ChatTranscript]     # chronological
list_sessions(limit=25) -> list[ChatSession]                    # most recently active first
session_stats(session_id) -> dict                               # turns, tokens, cost_usd
rename_session(session_id, title) -> bool
delete_session(session_id) -> bool                              # drops its transcripts too
transcript_meta(transcript) -> dict                             # decoded JSON, UI-shaped
```

`route_used`, `route_confidence`, and the token/cost columns are typed columns (we
aggregate over them); `agents_consulted`, `sources`, `constraints`, and `execution_trace`
are JSON text (the UI reads them back whole and never filters on them), so a reloaded
turn re-renders with the same badges, sources, restrictions, and debug trace as a live
one. `app.py` owns *no* SQL — it calls these functions, and `transcript_meta()` hands it
a dict in exactly the shape its renderer already expects.

---

### 5.6 `src/auth.py` (Phase 7, D34) — accounts, passwords, roles

Adds a `users` table on `database.py`'s SQLAlchemy `Base`, so accounts live in the same
SQLite file as conversations and telemetry and a per-user cost query is a plain join.

```python
init_auth(db_url=None) -> Engine        # idempotent; creates users + migrates chat_sessions
hash_password(pw) -> str                # "scrypt$n$r$p$salt_b64$key_b64"
verify_password(pw, stored) -> bool     # constant-time; never raises on malformed input
create_user(email, pw, *, display_name=None, role="user", plan_id="free") -> User
authenticate(email, pw) -> User | None  # None for BOTH bad password and no such account
get_user(user_id) / get_user_by_email(email) -> User | None
list_users() -> list[User]
set_plan(user_id, plan_id) -> bool  /  set_role(user_id, role) -> bool
seed_demo_users() -> list[tuple[str, str, str]]     # idempotent
```

**Contract notes that will bite if ignored:**

- Every function takes `db_url: str | None = None` and resolves it **at call time** via
  `_url()`. Do not "simplify" these to `db_url: str = DEFAULT_DB_URL` — Python binds
  default arguments once at `def` time, so the eager form silently ignores any
  reassignment of `DEFAULT_DB_URL` and keeps reading the real database. That broke
  `plans.revenue_report()` in tests, since it calls `list_users()` with no arguments.
- `authenticate()` deliberately does not distinguish "no such account" from "wrong
  password", and verifies against a dummy hash when the account is missing so absence is
  not detectable by response latency. Keep both properties.
- **Scope is honest and limited** (see `src/auth.py`'s docstring): real salted scrypt
  hashing and constant-time comparison, but no email verification, no password reset, no
  login rate limiting, and no session tokens. Do not describe this as production auth.

`chat_sessions` gains a nullable `user_id`. Nullable because conversations predate
accounts (D31): rows written before login shipped stay unowned and are listed for nobody,
which is the safe direction. `database.owns_session(user_id, session_id)` is the
ownership check `app.py` runs before opening or deleting a conversation.

### 5.7 `src/business/` (Phase 7, D32/D34/D35) — pricing, plans, billing

Three modules with one rule between them: **`pricing.py` is the only place a model rate
lives.** `unit_economics.py` derives from it rather than holding a second copy — the bug
that motivated this layer was two independent price tables drifting apart.

```python
# pricing.py — rates and projection
price_call(model, in_tok, out_tok) -> float | None      # ACTUAL cost, at insert time
project_call(measured_model, in_tok, out_tok) -> float | None   # production stack (D35)
PRODUCTION_STACK: dict[str, ModelRate]                  # measured model -> production model
PROJECTION_ASSUMPTIONS: str                             # must be shown wherever projections are

# plans.py — catalogue, quota, reporting
PLANS: dict[str, Plan]  /  get_plan(plan_id) -> Plan    # unknown id -> Free, never Clinic
check_quota(user_id, plan_id) -> QuotaVerdict           # free blocks; paid passes to overage
record_question(user_id, *, route, cost_usd, projected_usd, billable=True) -> int
usage_for(user_id, plan_id, *, since=None) -> UsageSummary
revenue_report() / margin_report() / capacity_report() / derive_pricing() -> dict
```

**Contract notes:**

- `price_call` returns **None**, never `0.0`, for a call with no usage metadata. An
  unmeasured call must stay distinguishable from a free one, or every dashboard average
  drifts toward optimism (same convention as `compliance_check`'s "could not check").
- **Actual cost is stored at insert; projected cost is computed at read.** Actual cost is
  a historical fact and must not be repriced when Groq changes its list. A projection is
  a model output and must re-derive when the scenario changes — so `llm_calls` has a
  `cost_usd` column and deliberately has **no** `projected_usd` column (asserted by test).
- `record_question(billable=False)` for RED_FLAG: it short-circuits on regex before any
  specialist runs (D5), so it costs nothing and must not consume quota.
- Plan prices are **derived** from cost at `TARGET_GROSS_MARGIN`, not chosen. If you edit
  `PLANS`, run `derive_pricing()` — `test_every_paid_plan_clears_the_margin_target` fails
  when a plan stops clearing.

`telemetry.py` (Ben, 2026-08-08) is the measurement layer underneath all of this: it
attaches one callback to the two cached `ChatGroq` clients in `rag_core`, so every call in
the pipeline is recorded without any caller knowing telemetry exists. Attribution
(`node` / `user_id` / `session_id`) travels in **ContextVars**, not module globals —
Streamlit serves each browser session on its own thread, and a raced global would invoice
the wrong customer.

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
  convention.)

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
4. **Conversation memory: within-conversation only, still no user profile.**
   *(Revised 2026-08-07 — D23. Originally: "No memory of the user in Phase A — each
   question stands alone; chat history is display-only.")* A follow-up is now resolved
   against **prior turns of the same conversation** before routing
   (`src/conversation.py`), because "what about my knee?" reaching the router with no
   referent collapsed to CLARIFY — conversations were being persisted but never reasoned
   over. What did **not** change: no cross-conversation user profile, no PII stored, no
   personalization that outlives a thread. History is used to make the *current* question
   complete, and is deliberately never injected into specialist prompts — they still
   answer only from retrieved corpus evidence (§7.1), and RED_FLAG still evaluates a
   complete standalone question. **Privacy consequence of persistence (D31):** chat history
   is written to a local SQLite file (`data/chat_history.db`, gitignored, never sent
   anywhere), so any health detail a user types is on disk in plaintext — acceptable for a
   local single-user educational demo, a real consideration before any hosted deployment.
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
- [x] Re-run the FULL §9 battery (parity check) plus new surgeon/three-way rows — run live
      2026-07-15 once a Groq key was available; see the Phase 4c update note for the real
      13/15 result and the two accuracy gaps found
- **Done when:** a post-op-only question routes SURGEON and answers grounded+cited (confirmed
  live); a three-cue TEAM question chains `consult_surgeon → consult_pt → consult_trainer` in
  order with constraints visible in the trace (confirmed live, real trace in the Phase 4c
  update); killing `surgeon_docs` before it's built degrades to `fallback_handler`, not a
  stack trace (verified structurally in Phase 4c's monkeypatch tests).

### Phase 4c — Router redesign: LLM-primary classification — **Ben** *(same-day follow-up to 4b)*

- [x] `src/router.py` rewritten: delete the weighted regex cue lists and dominance scorer;
      RED_FLAG remains the only regex (D5); every other question goes to one Groq call that
      returns the route label AND which specialist(s) apply, parsed into the same
      `RouteDecision.scores` shape the orchestrator already reads (D11)
- [x] No changes needed in `orchestrator.py` — the TEAM conditional-chain logic already
      consumed `route_scores` generically
- [x] Unit-tested `_parse_llm_response` against synthetic responses (incl. malformed ones);
      confirmed `classify()` degrades to CLARIFY (not a crash) with no API key or empty input
- [x] Run the FULL §9 battery for real against live Groq responses — done 2026-07-15,
      **13/15 correct**; two accuracy gaps found and logged (not yet fixed): a vague "best
      gym" question resolves to TRAINER_ONLY instead of CLARIFY, and one three-specialist
      TEAM question under-chains to PT+trainer only (misses the surgeon) despite explicit
      "my surgeon cleared me" / "weight-bearing" / "ACL reconstruction" language
- **Done when:** the battery has actually been run against a real Groq key and routing
  accuracy is recorded in a follow-up phase-results block — **done**, see the update note
  above. Follow-up: fix the two accuracy gaps (likely a prompt tweak), not done in this pass.

### Phase 5 — Streamlit app — **Ben**

- [x] `app.py`: chat UI over `answer_question()` (the only backend import — no agent/router/
      orchestrator internals touched); per-message specialist badges (🦴/🩺/🏋️, colored
      chips) showing which agent(s) contributed; route+confidence chip; expander with
      per-agent source files; expander with structured `constraints` (Phase 4b) rendered as
      a restrictions checklist; sidebar: per-agent "rebuild knowledge base" buttons shelling
      to `python -m src.ingest --agent <pt|trainer|surgeon> --fresh` with live output, a
      "show routing debug trace" toggle (route/confidence/execution_trace per message), and
      a clear-chat button. Custom CSS on top of default Streamlit (message bubbles, badge
      chips, route chip) — dark/light aware via `prefers-color-scheme` — per team decision
      to stay in-stack rather than adopt a different UI framework (D12)
- [x] README: setup → ingest (all three agents) → run, with what to expect described
- **Done when:** fresh clone → `.env` → ingest all three agents → `streamlit run app.py` →
  a TEAM question shows multiple badges and multiple source lists. This exact flow is the
  video-demo script. **Verified live** (see the Phase 5 update note) via Streamlit's
  `AppTest` with a real Groq key — real question in, real grounded answer with correct
  route chip/badge/sources out, zero exceptions. Still worth a human clicking through it once
  in an actual browser before the video shoot, since `AppTest` doesn't render CSS/layout.

### Phase 5b — Multi-session chat persistence — **Evan** *(follow-up to Phase 5; D31)*

- [x] `src/database.py` (§5.5): `chat_sessions` + `chat_transcripts` on SQLAlchemy/SQLite,
      WAL + `foreign_keys=ON` pragmas per connection, engine cached per URL so Streamlit's
      reruns don't rebuild it, DB path overridable via `CHAT_DB_URL` for tests/CI
- [x] `app.py` sidebar **Conversations** block: active-chat line (title · turns · tokens ·
      accumulated $), "🧹 New chat" (replaces the old clear-chat button), a picker of the 25
      most recently active conversations with explicit "📂 Open" and 🗑️ delete buttons.
      Turns are saved *after* the answer renders, and a write failure surfaces as a sidebar
      warning instead of costing the user the answer
- [x] Conversation titles auto-derived from the first question (truncated to 60 chars), so
      the picker reads as topics rather than uuids; sidebar timestamps converted from stored
      UTC to the viewer's local time
- [x] `tests/test_database.py` — 14 offline tests (no key needed): round-trip incl. the JSON
      metadata columns, orphan-transcript FK rejection, title back-fill/truncation,
      `updated_at` bump, recent-activity ordering, two-session isolation, stats aggregation,
      rename, delete-cascade, WAL/FK pragmas
- **Done when:** ask a question → reload the browser → the conversation is still in the
  sidebar and reopens with its badges, sources, restrictions, and trace intact; a second
  chat started with "New chat" stays separate. **Verified** via `streamlit.testing.v1.AppTest`
  (the Phase 5 convention) with `answer_question` patched and a temp `CHAT_DB_URL`: 42 checks
  across five flows — first render, two-turn save, New-chat isolation, reopen-from-a-fresh-
  browser-session (4 messages replayed, route chip `TEAM (0.88)`, PT badge, history notice)
  and delete — all passed with zero exceptions. Full suite: 56 passed.

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

### Phase 7 — Monetization: accounts, billing, business console — **Evan** *(D32/D34/D35)*

Built on top of Ben's `src/telemetry.py` (2026-08-08), which is the measurement layer this
whole phase reports on. Nothing here charges anyone; the only missing piece of a real
product is the payment processor.

- [x] `src/business/pricing.py`: one place a model rate lives. Fixed the live bug that
      `unit_economics` was still billing `llama-3.3-70b-versatile`'s $0.59/$0.79 after D27
      migrated to gpt-oss — every displayed cost had been a chars/4 token count priced at a
      retired model's rates. `unit_economics` now derives from this table instead of holding
      a second copy
- [x] `src/telemetry.py` extended: `cost_usd` / `user_id` / `session_id` columns with an
      in-place migration; attribution moved from a module global to **ContextVars** (a raced
      stage label mislabels a chart, a raced user label invoices the wrong customer)
- [x] `src/auth.py` per §5.6: scrypt accounts, user/admin roles, seeded demo logins, no new
      dependency (stdlib `hashlib`)
- [x] `src/business/plans.py` per §5.7: subscription + metered overage, quota enforcement,
      revenue/margin/capacity reporting, `derive_pricing()`
- [x] `app.py` gated behind login; conversations scoped to their owner with an
      `owns_session` check on open/delete; quota checked **before** the vision call and the
      orchestrator so a refused question costs nothing to refuse
- [x] `pages/1_Business_Dashboard.py`: admin-only console, re-reading the role from the
      database on every run (hiding a sidebar link is not access control)
- [x] Economics modelled on a **production stack** (D35) rather than the free tier, since
      the free tier supports ~157 TEAM questions/month for the entire account
- [x] `tests/test_monetization.py` — 51 tests covering pricing, projection, migration,
      per-thread attribution, auth, quota, and the billing rollups
- **Done when:** the login gate renders instead of the app (verified via `AppTest`: 0
  sidebar blocks signed out), a non-admin is refused the console and an admin gets it, a
  free user is blocked at quota while a paid user passes into overage, RED_FLAG consumes no
  quota, and every paid plan clears the margin target by construction. **All verified;
  offline suite 137 passed.**

**Two corrections made during this phase, both recorded because they changed a headline
number the report would otherwise have quoted:** (1) the first `capacity_report()` modelled
only the per-minute cap and overstated capacity **~58×** — the daily 200k cap binds far
earlier; (2) the D34-era "zero paying subscribers" claim assumed the then-current
250-question plan and became "1 subscriber, $45/mo" once D35 re-derived the quota to 100.
The test now pins the order of magnitude rather than an exact count, since that is the
durable claim.

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
| D12 | 2026-07-15 | Phase 5 UI stays Streamlit (polished with custom CSS), not a different framework | Considered Chainlit and a custom FastAPI+web frontend; rejected both for now — D1 already committed the whole team to mirroring the course reference stack, Evan/James's setup docs assume Streamlit, and it's the fastest path to a working demo. Polish (badges, chips, dark/light-aware CSS) addresses the "looks basic" complaint without a framework migration; revisit post-Phase-6 if there's time |
| D13 | 2026-08-02 | Eval-suite judge failures now score 0/`ERROR` instead of a hardcoded perfect score | The previous fail-open behavior meant any infra failure (missing key, rate limit, malformed JSON) silently reported a fabricated 5/5 safety score with `PASS: True` — a claimed "100% pass rate" that was true by construction, not by the system being safe. For health-adjacent software this is the opposite of D5's "safety must not depend on LLM behavior" applied to the safety tests themselves |
| D14 | 2026-08-02 | GraphRAG's "no match → default to ACL Reconstruction" behavior removed; now returns no match at all | The default meant every synthesized answer, for any question, got ACL-specific contraindications silently stapled onto it regardless of relevance — a direct violation of §7.1's grounding rule. No match now means no injection, consistent with every other specialist's "say you don't have material on it" convention |
| D15 | 2026-08-02 | `keyword_route_fallback` (added by James the same day as the nutrition merge) now only fires when the LLM's own confidence is below threshold, never to override a confident CLARIFY | It was re-resolving confidently-CLARIFY questions like "What's the best gym?" to a wrong single-specialist guess off one loose keyword match ("gym"), undoing a routing-accuracy gap that had already been found and fixed once (see the Phase 4c results block). A confident CLARIFY means the LLM already looked at the whole question and judged it too vague — a single keyword shouldn't override that |
| D16 | 2026-08-02 | Security guardrails, unit-economics cost tracking, and honest GraphRAG/CLIP labeling are all now wired into the real product path (`orchestrator.answer_question()` / `app.py`), not left in the unused `src/cli.py` only | Code that only runs from a side script nobody actually uses provides zero real protection/value while still being described as a shipped feature. If a capability is claimed as part of the product, it needs to run on the path real users (and graders) actually exercise |
| D17 | 2026-08-02 | The WAF-bypassing scrapers' output (`data/pt/unstructured/*.txt`, from Physiopedia via `cloudscraper`) is left in place, unattributed, pending an explicit team decision — not removed unilaterally | Unlike the two clearly-irrelevant PDFs removed in the same pass (a conference sponsorship prospectus, an org strategic plan — objectively wrong content regardless of source ethics), whether to keep bot-protection-bypassing scraped content is a licensing/ethics call the whole team should make knowingly, not something to decide by fiat while fixing unrelated code quality issues |
| D18 | 2026-08-02 | Photo-upload vision calls go to **Google Gemini**, not Groq — the only place this project uses a second LLM provider | Groq was checked first to keep the stack single-provider (D1's simplification goal). A live query of the account's `/v1/models` returned **no vision-capable model at all** — Llama 4 Scout/Maverick are not on this key, and every available text model rejects image content outright (verified by sending a real image to each). Google AI Studio's free tier supports vision, needs no credit card, and is used for exactly one call per uploaded photo; the router, all four specialists, and synthesis stay entirely on Groq. Note this does NOT re-litigate D2 (which rejected Gemini *embeddings* over rate limits on bulk 100-chunk ingestion) — one image description per upload is a completely different usage pattern. `GOOGLE_API_KEY` is optional: text-only questions work without it |
| D19 | 2026-08-02 | Uploaded images are converted to a **text description** up front, then fed through the existing pipeline — rather than passing pixels to the specialists | Every specialist answer is grounded in its own retrieved corpus (§7.1); handing four agents raw pixels would bypass that grounding entirely. Describing once, up front, keeps routing/grounding/synthesis architecturally unchanged — the photo just becomes richer context on the question. It also preserves the D5 safety gate: verified live that a photo described as showing "a surgical incision with redness and yellow drainage" trips RED_FLAG's deterministic regex and short-circuits, even when the user's typed question was innocuous ("What exercises can I do?") |
| D20 | 2026-08-02 | Visual search is **hybrid**: CLIP image-embedding similarity as the primary signal, plus a small filename-keyword bonus | Pure CLIP unlocked ~94% of the image corpus that filename matching could never reach (most images are PDF-extracted with opaque names like `p62_img1.jpg`; verified that a squat *photo* with that exact filename now ranks #1 for "squat exercise form"). But CLIP is trained on natural photographs and measurably under-ranks dense text-heavy instructional diagrams — a labeled "Squats for strengthening your leg muscles" infographic scored below rank 20 for the same query, a case the old filename search *would* have caught. The bonus is capped well below the typical CLIP score spread, so it recovers those diagrams (that one moved to rank #2) without displacing genuine visual matches |
| D21 | 2026-08-02 | Gemini model pinned to the `gemini-flash-latest` **alias**, not a specific version | Google retires specific Gemini versions for new users aggressively — verified live that `gemini-2.5-flash` already returns "no longer available to new users" on a key created the same day. A pinned version would have shipped broken. The alias tracks whatever current flash model the account can actually reach. (Contrast with Groq, where the reverse discipline applies — see the `llama-3.3-70b-versatile` Aug 16 deprecation note in the audit results block) |
| D22 | 2026-08-02 | The `llama-3.3-70b-versatile` → replacement-model migration is **deliberately deferred**, not overlooked — flagged prominently at the top of this document instead | Ben's call: land the audit-integrity fixes and the vision work first while that context was fresh, rather than interleave a model swap that needs its own full battery re-verification. The risk of deferring is real and bounded — a hard external cutoff on **2026-08-16**, after which the app stops working entirely — so it is recorded as an explicit deadline callout above §0 rather than left as a to-do buried in a results block. Whoever picks it up should treat it as a verification task, not a two-line edit: router accuracy is model-dependent and two routing regressions have already been caught only by re-running the §9 battery |
| D23 | 2026-08-07 | §7.4 revised: follow-ups are now resolved against prior turns of the same conversation (`src/conversation.py`) — replacing "each question stands alone" | Evan's persistence work changed what is *stored*; it did not change what is *reasoned over*, so conversations reopened but every question was still answered from scratch and "what about my knee?" collapsed to CLARIFY. Resolving the follow-up ONCE up front, before routing, fixes that while leaving the whole pipeline untouched. Deliberately NOT done by injecting chat history into specialist prompts: specialists must answer only from retrieved corpus evidence (§7.1), and both the router and the RED_FLAG regex need a complete standalone question to behave as tuned. Scope is within-conversation only — no cross-thread user profile, no PII retention; that remains a Phase B+ discussion |
| D24 | 2026-08-07 | Follow-up resolution also carries clinical context into questions that *look* standalone, not just obviously-dependent ones | Observed live: "give me a 3-day beginner strength program" routes `TRAINER_ONLY` with no history but `TEAM` (surgeon+PT+trainer) once the conversation has established "ACL reconstruction 6 weeks ago" — the same question, correctly bounded by post-op restrictions instead of answered as though the patient were uninjured. In a recovery product that is a safety property, so the prompt was rewritten to make it intentional rather than incidental model behavior |
| D25 | 2026-08-07 | Agent-to-agent gains a **back-channel** (`src/agents/peer_consult.py`), implemented as a single bounded node rather than a cyclic graph edge | The chain was strictly one-directional (Surgeon→PT→Trainer→Nutritionist via `peer_context`); a specialist that hit the edge of its scope could only hedge. Now one specialist can put a direct question to another and the reply joins the synthesis evidence — verified live: `peer_consult: trainer -> surgeon: "What are the post-operative weight-bearing status and ROM restrictions..."`. Capped at `MAX_CONSULT_ROUNDS=1` and wired as a straight-through node so the DAG's documented "cannot loop" safety property survives and the token budget stays bounded (the free-tier daily cap has been hit during testing more than once) |
| D26 | 2026-08-07 | Synthesis may attribute claims only to specialists whose draft is actually present; GraphRAG reference data is labeled as such and gets no `[source: ...]` marker | Caught during peer-consult testing: an answer said "Your nutritionist recommends Protein (2.0g/kg)..." when the nutritionist had never been consulted — the text came from the GraphRAG reference block and synthesis invented the attribution. Telling a patient a specialist said something they never said is precisely the class of overclaim this project has already had to correct once |
| D27 | 2026-08-07 | Migrated off `llama-3.3-70b-versatile` ahead of its 2026-08-16 retirement: specialists/synthesis to `openai/gpt-oss-120b`, routing/planning to `openai/gpt-oss-20b` | The deadline callout above §0 is now resolved. Note the obvious "small model" pick, `llama-3.1-8b-instant`, shuts down the SAME day — verified against Groq's deprecation page, not assumed. Two operational findings: (a) gpt-oss models emit reasoning tokens before content, so anything setting `max_tokens` must leave headroom or `content` returns empty; (b) `reasoning_effort="low"` costs 43 completion tokens vs 278 for an identical routing answer, which on a free tier this project has capped out repeatedly is the difference between a battery run fitting in budget and not. Also required: `reasoning_effort` is a first-class `ChatGroq` parameter and raises a pydantic ValidationError if passed via `model_kwargs` |
| D28 | 2026-08-07 | A small LM now decides **which specialists run and in what order** (`src/planner.py`), replacing `route_scores` + hardcoded graph edges | Ben's call, made knowingly against a flagged tradeoff. **This gives up a safety guarantee.** Fixed ordering (D4) guaranteed *by construction* that a restrictive specialist's constraints reached everyone downstream as binding `peer_context`; with LM-chosen order a plan of `["trainer","surgeon"]` writes the training plan before the surgeon's restrictions exist. Contained by three things, none of which fully restores it: RED_FLAG still runs on regex before planning (D5); ordering inversions are logged to the trace; and `compliance_check` re-verifies the final answer against every extracted constraint regardless of order (D30). **The claim "the model doesn't decide the things that matter" is now false and has been removed from Capabilities_Overview §7 — do not repeat it in the report.** The graph gains exactly one cycle (`consult_next` -> `consult_next`), bounded by plan length, which the planner caps and de-duplicates at the size of the roster |
| D29 | 2026-08-07 | Specialists can call tools: deterministic calculators, own-corpus re-query, and PubMed — with PubMed gated in CODE to the case where the agent's own retrieval returned nothing | Calculators are the safe majority of the value: the numbers this system hands patients are arithmetic, and arithmetic is where LLMs quietly slip. They compute over patient-supplied values rather than introducing outside claims, so §7.1 is untouched. `search_my_corpus` preserves siloing (D3) because the collection name is injected by the agent, never read from model-supplied arguments — asserted by test. PubMed is the one that changes the product's character: it is primary research, not the vetted patient-education material in `data/`, and a single small-n abstract can read like consensus guidance inside a synthesized answer. Hence: schema not even offered unless the corpus missed, cited as `[research: PMID ...]` never `[source: filename]`, metadata only (sidesteps the full-text licensing problem `data/` already had), and unable to override a restriction. Tool loop capped at MAX_TOOL_ROUNDS=2 — unbounded tool loops are the standard way an agent burns a metered budget |
| D30 | 2026-08-07 | `compliance_check` verifies the synthesized answer against every extracted constraint before it reaches the patient, and appends a visible warning on violation | The after-the-fact replacement for what D28 removed. Deliberately conservative: it flags only when the answer *affirmatively recommends* something a restriction forbids — telling a patient to avoid a restricted movement is the system working, not a violation. It also distinguishes "checked and clean" from "could not check" (`checked: False`), so a broken checker never reports a clean bill of health it did not establish — the same failure mode as the fabricated eval pass rate corrected in D23's audit |
| D32 | 2026-08-08 | One pricing table (`src/business/pricing.py`) owns what a token costs, and metered rows replace the `len(text)/4` estimator as the source of every displayed cost | The estimator was wrong twice over and the two errors pointed opposite ways, which is why neither was noticed: it counted only the visible question and answer — about one of the 6–14 model calls a question makes, understating tokens ~5.7× against Ben's measured 11,564 for a single-specialist question — and priced them at **$0.59/$0.79 per 1M**, `llama-3.3-70b-versatile`'s rates, which D27 had migrated off nine days earlier, overstating input ~3.9×. Verified rates now live in exactly one file (gpt-oss-120b $0.15/$0.60, gpt-oss-20b $0.075/$0.30, checked against Groq's docs rather than remembered), and `unit_economics` derives from it instead of holding a second drifting copy. Cost is computed **at insert**, not at read: repricing history after a Groq change would silently rewrite a past period's reported margin. A call with no usage metadata records **NULL, not 0.0** — an unmeasured call must stay distinguishable from a free one, the same distinction `compliance_check` draws between "could not check" and "clean" (D30), and the same failure mode as the eval harness that scored 5/5 on exception (D13). Unknown models price at the *dearest* known rate so a missed model swap can never flatter the margin |
| D33 | 2026-08-08 | Telemetry attribution moved from a module global to `ContextVar`s | Ben's `_current_node` global (07afb4a) was a deliberate, documented tradeoff and it is fine for what it was built for: two concurrent users racing over a *stage label* mislabels a chart. It is not fine for `user_id`. Streamlit serves every browser session on its own thread, so a raced global there would invoice user A for user B's tokens. ContextVars are per-thread, so concurrent requests attribute independently — asserted by a test that forces genuine interleaving with a `threading.Barrier`. Deliberate consequence: a callback fired from a worker thread that never had them set records NULL rather than inheriting another request's identity, and such rows are reported as `(unattributed)` rather than dropped so per-user totals always reconcile with the metered total. Unattributed is recoverable; misattributed billing is not |
| D34 | 2026-08-08 | Accounts + subscription-with-overage billing + an admin-only business console, with **no payment processor** | The course product needs the *mechanisms* of a paid product, not payments. Everything is real and computed from live rows — scrypt-hashed accounts (stdlib `hashlib`, no new dependency, because this project already had to reject `llm-guard` for downgrading `transformers` and breaking MiniLM retrieval for all four agents), quota, overage, per-user cost-to-serve — and `record_payment()` writes the invoice a Stripe webhook would, marked `status='simulated'` so a demo row can never be mistaken for a real one. Three choices worth defending: **(a) billing is per question, not per token** — a TEAM question costs ~3.3× a single-specialist one (38,141 vs 11,564 tokens) and the *planner* chooses the route, not the patient (D28), so per-token billing would charge someone more because our orchestrator decided their question needed the surgeon; we absorb the variance and `margin_report()` is the evidence that is safe. **(b) Free blocks at quota, paid passes into overage** — charging someone who never entered a card and cutting off a paying patient mid-recovery are both wrong, in opposite directions. **(c) RED_FLAG is non-billable** — it short-circuits on regex before any specialist runs (D5), so it costs nothing to serve, and billing for being told to seek emergency care is indefensible. The console is a role-gated `pages/` file that re-reads the role from the database on every run rather than trusting `session_state`, because hiding a sidebar link is not access control. **The finding the report should lead with is commercial: at >99% gross margin, cost is not the constraint — Groq's rate limits are, and the DAILY one binds.** Two caps do different jobs: 8,000 tok/min is a latency limit (one TEAM question = 4.8 min of the account's whole budget, hence the measured 204.8 s stall), while 200,000 tok/day is a volume limit allowing only ~5.2 TEAM questions/day, i.e. **157/month for the entire account**. A capacity model built on tokens-per-minute alone overstates this by ~58× and must not be used. *(Subscriber-count figures originally recorded here assumed the then-current 250-question Recovery plan and read "zero supportable"; **D35 re-derived the plans to 100 questions, so the same 157/month now supports 1 subscriber and a $45/mo ceiling**. The order of magnitude — a free tier that cannot fund a business — is the durable claim, and the tests assert that rather than an exact count.)* |
| D35 | 2026-08-09 | Unit economics are **modelled on a production stack** (Sonnet 5 specialists + Haiku 4.5 orchestration), not on the free Groq tier the proof-of-concept runs, and the app displays those projected figures as its primary cost numbers | The free tier is a coursework choice, not a product decision, and D34's capacity work established that it supports ~157 TEAM questions/month for the entire account — one subscriber, a $45/mo ceiling. Economics argued on it would be economics of a thing that cannot exist. So the same MEASURED token volumes are re-priced tier-for-tier onto a stack with no usage caps, keyed by the model that actually served each call (`pricing.PRODUCTION_STACK`), which preserves the real architectural cost lever: cheap models keep doing the cheap work. Sonnet 5's standard $3/$15 is used deliberately rather than its $2/$10 introductory rate, which expires 2026-08-31 — three weeks after this is presented, and a model that only works on promotional pricing is not a model. **This inverts the project's commercial conclusion.** Cost per TEAM question goes $0.0092 -> $0.185 (~20x). On the free tier the multi-agent architecture's ~10x token multiplier is economically invisible and supply is the only constraint; on a production stack that multiplier is the dominant line item, and the measured fact that constraint extraction costs nearly as much as the consult it summarises becomes a budget decision rather than trivia. Plans were re-derived from cost at a 75% margin target rather than chosen and justified: Free $0/10, Recovery $45/100, Clinic $225/500, both paid tiers clearing 77.6% at full quota — the worst case, since an idle subscriber is pure margin. The prior $19/250 plan would run at -32% margin here, which is the finding that forced the reprice. **Honesty constraint, since projected cost is now shown where metered cost used to be:** token counts are not model-invariant (different tokenizers, different reasoning-token spend, different answer lengths), so these are modelled figures accurate to roughly +/-20-30%, and both the app and the dashboard say so persistently rather than in a footnote. Actual cost is still stored per row at insert (a historical fact); the projection is computed at read time (a model output that must re-derive when the scenario changes). `capacity_report()` still models the free tier deliberately — it is the evidence for why the paid stack is necessary, not an upsell |
| D31 | 2026-07-31 *(renumbered twice: D13 -> D23 -> D31. Work developed in parallel on `main` claimed D13–D22 in the 2026-08-02 audit pass and D23–D30 on 2026-08-07, both times while this branch was open. Renumbering this row rather than `main`'s was the cheaper direction each time — `main`'s numbers are cross-referenced from requirements.txt, §7.4, and other decision rows.)* | Multi-session chat persistence (`src/database.py`, SQLAlchemy + SQLite, ported from opim-5517 HW8) instead of Streamlit-session-only history | Chat vanished on every page reload, which made the demo feel like a toy and made it impossible to compare two separate recovery scenarios side by side. SQLite because it's a file (zero setup, matches the "pip install and run" constraint) and the team already has the HW8 pattern; WAL mode so two browser tabs = two live chats without lock errors. Multi-agent render metadata (`agents_consulted`/`sources`/`constraints`/`execution_trace`) is stored as JSON text rather than normalized — the UI reads those back whole and never queries inside them, while `route_used` and the token/cost columns, which we *do* aggregate, stay typed columns. Trade-off accepted: matched CLIP exercise images are **not** persisted (re-derived on a fresh ask), because replaying them would mean one embedding search per historical message on every rerun |

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
