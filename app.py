"""
app.py — Streamlit chat UI for the Recovery Team (Phase 5).

The ONLY thing this file touches from the backend is answer_question() (§5.4
contract) -- no agent, router, or orchestrator internals leak into the UI.
Polished styling on top of Streamlit's defaults (custom CSS for message
bubbles and specialist badges) rather than a different framework, so setup
stays exactly `pip install -r requirements.txt` for the whole team.

Run:
    python -m src.ingest --agent pt
    python -m src.ingest --agent trainer
    python -m src.ingest --agent surgeon
    streamlit run app.py
"""

from __future__ import annotations

import subprocess
import sys

import streamlit as st

from src.orchestrator import answer_question


@st.cache_resource
def _get_visual_search():
    """Cached across reruns -- avoids rescanning every visuals/ folder from
    scratch on every chat message on every Streamlit rerun."""
    from src.multimodal.clip_search import MultimodalVisualSearch

    return MultimodalVisualSearch()


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

if "messages" not in st.session_state:
    st.session_state.messages = []


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


with st.sidebar:
    st.markdown("## 🩹 Recovery Team")
    st.caption(
        "A care team of specialist RAG agents -- Orthopedic Surgeon, Physical "
        "Therapist, and Gym Trainer -- coordinated by an LLM router and "
        "LangGraph orchestrator. Ask one question; the right specialist(s) answer."
    )

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

            st.markdown("**Token pricing:** Groq `llama-3.3-70b-versatile`")
            st.caption("Input: $0.59/1M tokens | Output: $0.79/1M tokens")
            st.caption(
                "Token counts are a length/4 heuristic (CostCalculator.estimate_tokens), "
                "not real Groq usage metadata -- treat as an approximation."
            )

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
                    st.warning(f"Session budget guard: exceeded ${guard.max_session_budget:.2f} estimated cost.")
                else:
                    st.caption(f"Budget guard: healthy (max ${guard.max_session_budget:.2f}/session, estimate-only -- does not block requests)")
            else:
                st.caption("No exchanges yet this session.")
        except Exception as exc:
            st.caption(f"(unit economics unavailable: {exc})")

    st.divider()
    if st.button("Clear chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

st.title("Recovery Team")
st.caption(
    "Educational support only -- not a substitute for advice from a licensed clinician."
)

for msg in st.session_state.messages:
    avatar = "🙂" if msg["role"] == "user" else "🩹"
    with st.chat_message(msg["role"], avatar=avatar):
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

            try:
                matched_imgs = _get_visual_search().search_visuals(msg.get("content", ""), top_k=2)
                if matched_imgs:
                    with st.expander("🖼️ Visual Guides & Diagrams"):
                        for img in matched_imgs:
                            st.caption(f"**{img['title']}**")
                            st.image(img["file_path"], use_container_width=True)
            except Exception as exc:
                st.caption(f"(visual search unavailable: {exc})")

question = st.chat_input("Ask about an injury, rehab, or getting back into training...")

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user", avatar="🙂"):
        st.markdown(question)

    with st.chat_message("assistant", avatar="🩹"):
        with st.spinner("Consulting the care team..."):
            result = answer_question(question)
        st.markdown(
            f'<span class="route-chip">{result["route"]} '
            f'({result["route_confidence"]:.2f})</span>',
            unsafe_allow_html=True,
        )
        st.markdown(_badges_html(result["agents_consulted"]), unsafe_allow_html=True)
        st.markdown(result["final_answer"])

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
            },
        }
    )
    st.rerun()
