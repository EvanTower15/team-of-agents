"""
app.py — Streamlit chat UI for the Recovery Team (Phase 5).

The ONLY backend answer path this file touches is answer_question() (§5.4
contract) -- no agent, router, or orchestrator internals leak into the UI.
Polished styling on top of Streamlit's defaults (custom CSS for message
bubbles and specialist badges) rather than a different framework, so setup
stays exactly `pip install -r requirements.txt` for the whole team.

Chat history is persisted to SQLite through src/database.py, so a user can keep
several conversations going -- each browser tab holds its own active session --
and reload any of them from the sidebar later. Streamlit session_state stays the
render cache; the database is the source of truth across reloads.

Run (one ingest per specialist — there is no --agent all):
    python -m src.ingest --agent pt
    python -m src.ingest --agent trainer
    python -m src.ingest --agent surgeon
    python -m src.ingest --agent nutrition
    streamlit run app.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone

import streamlit as st

from src.business.unit_economics import CostCalculator
from src.database import (
    create_session,
    delete_session,
    get_session,
    get_session_transcripts,
    init_db,
    list_sessions,
    save_result,
    session_stats,
    transcript_meta,
)
from src.orchestrator import answer_question


@st.cache_resource
def _get_visual_search():
    """Cached across reruns -- avoids rescanning every visuals/ folder from
    scratch on every chat message on every Streamlit rerun."""
    from src.multimodal.clip_search import MultimodalVisualSearch

    return MultimodalVisualSearch()


def _render_observability() -> None:
    """Real per-call token accounting, read from src/telemetry.py.

    Deliberately distinct from the sidebar's unit-economics panel: that one
    estimates cost from string length, this one reports what Groq actually
    charged us. Where they disagree, this is the truthful one.
    """
    from src import telemetry

    st.caption(
        "Actual token counts from Groq response metadata — not the chars/4 "
        "estimate used in the sidebar. Covers every call in the pipeline: "
        "router, planner, each specialist, tool rounds, constraint extraction, "
        "the peer back-channel, synthesis, and the compliance check."
    )

    s = telemetry.summary()
    if not s["calls"]:
        st.info(
            "No model calls recorded yet. Ask a question in the Chat tab and "
            "this fills in."
        )
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Model calls", f"{s['calls']:,}")
    c2.metric("Tokens (real)", f"{s['tokens']:,}")
    c3.metric("Avg latency", f"{s['avg_latency_ms']:,} ms")
    c4.metric("Throttled calls", f"{s.get('throttled', 0):,}",
              help=f"Calls slower than {telemetry.SLOW_CALL_MS // 1000}s. Counting 429s does "
                   "NOT detect Groq throttling -- the SDK retries below the callback layer, so "
                   "the call succeeds and no error is ever raised. Latency is the only signal.")

    # The ceiling that actually stalls a live demo. The 200k/day cap is the one
    # everyone notices; 8k/minute on gpt-oss-120b is the one that makes the
    # spinner sit there while the client backs off silently.
    st.markdown(
        f"**Tokens per minute vs the free-tier ceiling "
        f"({telemetry.TPM_LIMIT_120B:,}/min on `gpt-oss-120b`)**"
    )
    tpm = telemetry.tokens_per_minute()
    if tpm:
        import pandas as pd

        df = pd.DataFrame(tpm).set_index("minute")
        df["ceiling"] = telemetry.TPM_LIMIT_120B
        st.line_chart(df[["tokens", "ceiling"]], height=220)
        if any(r["rate_limits"] for r in tpm):
            st.warning(
                "429s recorded. When the per-minute budget is exhausted the "
                "client backs off silently — from the UI that is "
                "indistinguishable from a hang."
            )

    st.markdown("**Where the tokens actually go, by pipeline stage**")
    rows = telemetry.by_node()
    if rows:
        import pandas as pd

        st.dataframe(
            pd.DataFrame(rows).rename(columns={
                "node": "Stage", "calls": "Calls", "tokens": "Tokens",
                "avg_latency_ms": "Avg ms", "rate_limits": "429s",
                "throttled": "Throttled",
            }),
            use_container_width=True, hide_index=True,
        )

    with st.expander("Recent calls"):
        import pandas as pd

        st.dataframe(
            pd.DataFrame(telemetry.recent_calls()),
            use_container_width=True, hide_index=True,
        )

    _ls = os.getenv("LANGCHAIN_PROJECT", "recovery-team-eval")
    st.caption(
        f"Full request/response traces live in LangSmith (project `{_ls}`) — "
        "https://smith.langchain.com . It cannot be embedded here: it is hosted "
        "SaaS and blocks framing."
    )


SPECIALIST_META = {
    "orthopedic_surgeon": {"icon": "🦴", "label": "Orthopedic Surgeon", "color": "#6366f1"},
    "physical_therapist": {"icon": "🩺", "label": "Physical Therapist", "color": "#0d9488"},
    "gym_trainer": {"icon": "🏋️", "label": "Gym Trainer", "color": "#ea580c"},
    "nutritionist": {"icon": "🥗", "label": "Nutritionist", "color": "#16a34a"},
}

AGENT_FLAGS = ("pt", "trainer", "surgeon", "nutrition")

st.set_page_config(page_title="Recovery Team", page_icon="🩹", layout="wide")

st.markdown(
    """
    <style>
    .stChatMessage { border-radius: 14px; }

    .specialist-badges { display: flex; gap: 0.4rem; flex-wrap: wrap; margin: 0.35rem 0 0.6rem 0; }
    .specialist-badge {
        display: inline-flex; align-items: center; gap: 0.35rem;
        padding: 0.15rem 0.65rem; border-radius: 999px;
        font-size: 0.8rem; font-weight: 600; color: white;
        opacity: 0.92;
    }

    .route-chip {
        display: inline-block; padding: 0.1rem 0.55rem; border-radius: 999px;
        font-size: 0.75rem; font-weight: 600; letter-spacing: 0.02em;
        background: rgba(120, 120, 120, 0.18); color: inherit;
        border: 1px solid rgba(120, 120, 120, 0.35);
    }

    .restriction-line {
        padding: 0.25rem 0; border-bottom: 1px dashed rgba(120, 120, 120, 0.25);
        font-size: 0.9rem;
    }
    .restriction-line:last-child { border-bottom: none; }

    @media (prefers-color-scheme: dark) {
        .route-chip { background: rgba(255, 255, 255, 0.08); border-color: rgba(255, 255, 255, 0.18); }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Create the DB file/tables if needed. Cheap on every rerun -- the engine is
# cached per URL inside src/database.py.
init_db()

if "messages" not in st.session_state:
    st.session_state.messages = []

if "session_id" not in st.session_state:
    # Created lazily on the first saved turn, so merely opening the page (or a
    # second tab) never leaves an empty conversation in the sidebar.
    st.session_state.session_id = None

if "persist_error" not in st.session_state:
    # A failed write must not silently swallow the turn; stash it here so it
    # survives the st.rerun() and can be surfaced in the sidebar.
    st.session_state.persist_error = None


def _badges_html(agents_consulted: list[str]) -> str:
    chips = []
    for name in agents_consulted:
        meta = SPECIALIST_META.get(name)
        if not meta:
            continue
        chips.append(
            f'<span class="specialist-badge" style="background:{meta["color"]}">'
            f'{meta["icon"]} {meta["label"]}</span>'
        )
    return f'<div class="specialist-badges">{"".join(chips)}</div>' if chips else ""


def _run_ingest(agent: str, fresh: bool = True) -> tuple[bool, str]:
    cmd = [sys.executable, "-m", "src.ingest", "--agent", agent]
    if fresh:
        cmd.append("--fresh")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    ok = result.returncode == 0
    output = (result.stdout or "") + (result.stderr or "")
    return ok, output.strip()[-1500:]


# ─────────────────────────────────────────────────────────────────────────────
# Chat persistence glue (all DB access goes through src/database.py)
# ─────────────────────────────────────────────────────────────────────────────


def _messages_from_transcripts(transcripts: list) -> list[dict]:
    """Rebuild st.session_state.messages from persisted turns.

    Route, badges, sources, binding restrictions, and the debug trace are all
    stored, so a reloaded turn renders exactly like a live one. Matched exercise
    images are the one exception -- they're a CLIP lookup, not part of the answer,
    so replayed turns carry a `from_history` flag and skip that search rather
    than paying for one embedding pass per historical message on every rerun.
    """
    messages: list[dict] = []
    for t in transcripts:
        messages.append({"role": "user", "content": t.user_query})
        messages.append(
            {
                "role": "assistant",
                "content": t.agent_response or "",
                "meta": transcript_meta(t),
                "from_history": True,
            }
        )
    return messages


def _cost_meta(question: str, answer: str) -> dict:
    """Estimated token/cost metrics for one turn (the estimator src/cli.py uses)."""
    cost = CostCalculator.calculate_query_cost(question, answer)
    return {
        "tokens": {
            "input_tokens": cost.input_tokens,
            "output_tokens": cost.output_tokens,
            "total_tokens": cost.total_tokens,
        },
        "cost_usd": cost.groq_cost_usd,
    }


def _persist_turn(question: str, result: dict, cost_meta: dict) -> None:
    """Save one turn, creating the DB session lazily on the first saved turn."""
    if st.session_state.session_id is None:
        st.session_state.session_id = create_session({"client": "streamlit"})
    save_result(
        st.session_state.session_id,
        question,
        result,
        tokens=cost_meta["tokens"],
        cost_usd=cost_meta["cost_usd"],
    )


def _local_stamp(value: datetime | None) -> str:
    """Format a stored timestamp in the viewer's local time.

    Timestamps are written as UTC but come back from SQLite tz-naive, so they
    have to be re-tagged before converting — otherwise the sidebar shows a user
    in Connecticut a time four hours in their future.
    """
    if value is None:
        return "unsaved"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return f"{value.astimezone():%b %d %H:%M}"


def _session_label(session) -> str:
    """Sidebar label: the conversation's title, dated, with a uuid tiebreaker."""
    return (
        f"{session.title or 'Untitled chat'} · "
        f"{_local_stamp(session.updated_at)} · {session.session_id[:6]}"
    )


with st.sidebar:
    st.markdown("## 🩹 Recovery Team")
    st.caption(
        "Four specialist RAG agents -- Orthopedic Surgeon, Physical Therapist, "
        "Gym Trainer, and Nutritionist. Ask one question; a planner picks who "
        "answers and in what order."
    )

    st.divider()
    st.markdown("**Conversations**")

    if st.session_state.persist_error:
        st.warning(f"Last turn was not saved: {st.session_state.persist_error}")

    _sid = st.session_state.session_id
    if _sid:
        _stats = session_stats(_sid)
        _active = get_session(_sid)
        st.caption(
            f"Active: **{(_active.title if _active else None) or 'New chat'}** · "
            f"{_stats['turns']} turn{'' if _stats['turns'] == 1 else 's'} · "
            f"{_stats['total_tokens']:,} tokens · ${_stats['cost_usd']:.4f}"
        )
    else:
        st.caption("Active: _new chat (nothing saved yet)_")

    if st.button("🧹 New chat", use_container_width=True):
        # Leaves the current conversation on disk; the next question starts a
        # fresh session row.
        st.session_state.session_id = None
        st.session_state.messages = []
        st.session_state.persist_error = None
        st.rerun()

    # Reloading a past conversation is an explicit button (not the selectbox's
    # own change event) so that browsing the list never clobbers the open chat.
    _past = [s for s in list_sessions(limit=25) if s.session_id != _sid]
    if _past:
        _labels = {s.session_id: _session_label(s) for s in _past}
        _pick = st.selectbox(
            "Reopen a past conversation",
            options=list(_labels.keys()),
            format_func=lambda i: _labels[i],
        )

        _open_col, _del_col = st.columns([3, 1])
        with _open_col:
            if st.button("📂 Open", use_container_width=True):
                st.session_state.session_id = _pick
                st.session_state.messages = _messages_from_transcripts(
                    get_session_transcripts(_pick)
                )
                st.session_state.persist_error = None
                st.rerun()
        with _del_col:
            if st.button("🗑️", help="Delete the selected conversation", use_container_width=True):
                delete_session(_pick)
                st.rerun()
    else:
        st.caption("No other saved conversations yet.")

    st.divider()
    st.markdown("**Knowledge bases**")
    for agent in AGENT_FLAGS:
        if st.button(f"Rebuild {agent}_docs", key=f"rebuild_{agent}", use_container_width=True):
            with st.spinner(f"Ingesting data/{agent}/ ..."):
                ok, output = _run_ingest(agent)
            (st.success if ok else st.error)(f"{'Done' if ok else 'Failed'}: {agent}")
            with st.expander("Ingest output", expanded=not ok):
                st.code(output or "(no output)")

    st.divider()
    show_debug = st.toggle("Show routing debug trace", value=False)

    st.divider()
    with st.expander("Business unit economics (this session)"):
        try:
            from src.business.unit_economics import CostCalculator, BudgetOverrunGuard, VerticalStrategyMetrics

            st.caption("Groq `gpt-oss-120b` - costs are estimated, not metered.")

            # Real per-exchange cost computed from the actual chat history in
            # this session, not a hardcoded placeholder number. Pair each user
            # message with the assistant reply that immediately follows it.
            guard = BudgetOverrunGuard()
            msgs = st.session_state.messages
            for i, msg in enumerate(msgs):
                if msg["role"] == "user" and i + 1 < len(msgs) and msgs[i + 1]["role"] == "assistant":
                    metrics = CostCalculator.calculate_query_cost(msg["content"], msgs[i + 1]["content"])
                    guard.check_and_update(metrics.groq_cost_usd)

            if guard.query_count:
                st.markdown(f"**This session:** {guard.query_count} exchange(s)")
                st.caption(f"- Estimated Groq cost so far: ${guard.accumulated_session_cost:.4f}")
                if guard.accumulated_session_cost > 0:
                    roi = VerticalStrategyMetrics.calculate_roi_versus_human_care(
                        guard.accumulated_session_cost / guard.query_count, 15.0
                    )
                    st.caption(f"- vs. human consult equivalent: ${roi['human_care_equivalent_usd']:.2f} ({roi['cost_reduction_multiplier']})")
                if guard.accumulated_session_cost > guard.max_session_budget:
                    st.warning(f"Over the ${guard.max_session_budget:.2f} session estimate.")
            else:
                st.caption("No exchanges yet this session.")
        except Exception as exc:
            st.caption(f"(unit economics unavailable: {exc})")

st.title("Recovery Team")
st.caption(
    "Educational support only -- not a substitute for advice from a licensed clinician."
)

# Chat and observability are tabs over the CONTENT area only. st.chat_input is
# still called at page level further down, so Streamlit keeps it pinned to the
# bottom of the window rather than burying it inside a tab.
_tab_chat, _tab_obs = st.tabs(["💬 Chat", "📊 Observability"])

with _tab_obs:
    _render_observability()

with _tab_chat:
  for msg in st.session_state.messages:
      avatar = "🙂" if msg["role"] == "user" else "🩹"
      with st.chat_message(msg["role"], avatar=avatar):
          if msg["role"] == "user" and msg.get("image_description"):
              with st.expander("🖼️ What the vision model saw in your photo"):
                  st.caption(msg["image_description"])
          if msg["role"] == "assistant":
              meta = msg.get("meta", {})
              st.markdown(
                  f'<span class="route-chip">{meta.get("route", "?")} '
                  f'({meta.get("route_confidence", 0):.2f})</span>',
                  unsafe_allow_html=True,
              )
              st.markdown(_badges_html(meta.get("agents_consulted", [])), unsafe_allow_html=True)
          st.markdown(msg["content"])

          if msg["role"] == "assistant":
              meta = msg.get("meta", {})
              sources = meta.get("sources") or {}
              if sources:
                  with st.expander("Sources"):
                      for agent, files in sources.items():
                          label = SPECIALIST_META.get(agent, {}).get("label", agent)
                          st.markdown(f"**{label}:** " + ", ".join(files))

              constraints = meta.get("constraints") or {}
              if constraints:
                  with st.expander("Binding restrictions"):
                      for agent, items in constraints.items():
                          label = SPECIALIST_META.get(agent, {}).get("label", agent)
                          st.markdown(f"**From your {label}:**")
                          for c in items:
                              part = f" ({c['body_part']})" if c.get("body_part") else ""
                              dur = f" -- {c['duration']}" if c.get("duration") else ""
                              st.markdown(
                                  f'<div class="restriction-line">{c["restriction"]}{part}{dur}</div>',
                                  unsafe_allow_html=True,
                              )

              if show_debug and meta.get("execution_trace"):
                  with st.expander("Routing trace (debug)"):
                      st.markdown(f"**Route:** {meta.get('route')} "
                                  f"(confidence {meta.get('route_confidence', 0):.2f})")
                      for line in meta["execution_trace"]:
                          st.code(line, language=None)

              tokens = meta.get("tokens") or {}
              if tokens.get("total_tokens"):
                  st.caption(
                      f"🪙 {tokens['total_tokens']:,} tokens "
                      f"(in {tokens.get('input_tokens', 0):,} / out {tokens.get('output_tokens', 0):,}) "
                      f"· ${meta.get('cost_usd', 0.0):.6f}"
                  )

              # Reloaded turns skip the CLIP lookup: it is a live image-embedding
              # search over the whole visuals corpus, not part of the saved answer,
              # so replaying it would cost one search per historical message on
              # every rerun (see _messages_from_transcripts).
              if msg.get("from_history"):
                  st.caption("↩️ Reloaded from saved history — ask again to regenerate visual guides.")
              else:
                  try:
                      matched_imgs = _get_visual_search().search_visuals(msg.get("content", ""), top_k=2)
                      if matched_imgs:
                          with st.expander("🖼️ Visual Guides & Diagrams"):
                              for img in matched_imgs:
                                  st.caption(f"**{img['title']}**")
                                  st.image(img["file_path"], use_container_width=True)
                  except Exception as exc:
                      st.caption(f"(visual search unavailable: {exc})")

_submission = st.chat_input(
    "Ask about an injury, rehab, or getting back into training...",
    accept_file=True,
    file_type=["jpg", "jpeg", "png", "webp"],
)

# With accept_file=True, chat_input returns a dict-like object rather than a
# plain string. Normalize both shapes so the rest of the flow is unchanged.
question, uploaded_image = None, None
if _submission:
    question = getattr(_submission, "text", None) or ""
    files = getattr(_submission, "files", None) or []
    uploaded_image = files[0] if files else None
    if not question and uploaded_image:
        question = "What can you tell me about this photo?"

if question:
    # If a photo is attached, describe it with a vision model first and fold
    # that description into the question -- the specialists themselves run on
    # a text-only model, so this is what lets them "see" it (src/vision.py).
    image_description, image_error = "", None
    if uploaded_image is not None:
        with st.spinner("Looking at your photo..."):
            from src.vision import describe_image, build_question_with_image

            vision_result = describe_image(uploaded_image.getvalue(), uploaded_image.name)
            image_description = vision_result["description"]
            image_error = vision_result["error"]

    effective_question = question
    if image_description:
        from src.vision import build_question_with_image

        effective_question = build_question_with_image(question, image_description)

    # Snapshot the prior turns BEFORE appending this one -- otherwise the
    # current question would appear in its own history. This is what lets a
    # follow-up like "what about my knee?" resolve against earlier context
    # instead of being answered from scratch.
    prior_history = [
        {"role": m["role"], "content": m["content"]} for m in st.session_state.messages
    ]

    st.session_state.messages.append(
        {"role": "user", "content": question, "image_description": image_description}
    )
    with st.chat_message("user", avatar="🙂"):
        st.markdown(question)
        if image_error:
            st.warning(f"Couldn't read that photo: {image_error}")
        elif image_description:
            with st.expander("🖼️ What the vision model saw in your photo"):
                st.caption(image_description)

    with st.chat_message("assistant", avatar="🩹"):
        with st.spinner("Consulting the care team..."):
            result = answer_question(effective_question, history=prior_history)
        st.markdown(
            f'<span class="route-chip">{result["route"]} '
            f'({result["route_confidence"]:.2f})</span>',
            unsafe_allow_html=True,
        )
        st.markdown(_badges_html(result["agents_consulted"]), unsafe_allow_html=True)
        st.markdown(result["final_answer"])

    cost_meta = _cost_meta(question, result["final_answer"])
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": result["final_answer"],
            "meta": {
                "route": result["route"],
                "route_confidence": result["route_confidence"],
                "agents_consulted": result["agents_consulted"],
                "sources": result["sources"],
                "constraints": result.get("constraints", {}),
                "execution_trace": result["execution_trace"],
                **cost_meta,
            },
        }
    )

    # Persist after the answer is already on screen and in session_state: a DB
    # problem should cost the user the history row, never the answer itself.
    try:
        _persist_turn(question, result, cost_meta)
        st.session_state.persist_error = None
    except Exception as exc:  # surfaced in the sidebar, survives the rerun below
        st.session_state.persist_error = f"{type(exc).__name__}: {exc}"

    st.rerun()
