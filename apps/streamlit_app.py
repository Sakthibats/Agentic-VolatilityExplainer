"""Streamlit frontend for the Agentic Volatility Explainer."""

from __future__ import annotations

import time

import streamlit as st

from ui.components import (
    render_agent_tiles_section,
    render_brand_header,
    render_final_output_box,
    render_guardrail_error,
    render_right_panel,
    render_search_bar,
    render_ticker_chip,
)
from ui.placeholders import parse_search_input, run_analysis, validate_financial_query
from ui.theme import inject_theme

st.set_page_config(
    page_title="Agentic Volatility Explainer",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_theme()
render_brand_header()

# ── Session defaults ──────────────────────────────────────────────────────────
st.session_state.setdefault("analysis_phase", "idle")
st.session_state.setdefault("submitted_query", "")
st.session_state.setdefault("visible_tiles", 0)
st.session_state.setdefault("analysis_result", None)
st.session_state.setdefault("all_tiles", [])
st.session_state.setdefault("chart_period", "6M")
st.session_state.setdefault("guardrail_message", "")

render_search_bar()

phase     = st.session_state["analysis_phase"]
submitted = st.session_state["submitted_query"]
ticker, question = parse_search_input(submitted) if submitted else (None, "")

# Guardrail check — runs only when a new query is submitted (phase == "running")
if phase == "running" and submitted:
    is_valid, err_msg = validate_financial_query(submitted, ticker)
    if not is_valid:
        st.session_state["analysis_phase"] = "guardrail"
        st.session_state["guardrail_message"] = err_msg
        phase = "guardrail"

left_col, right_col = st.columns([11, 7], gap="large")

# ── Left panel ────────────────────────────────────────────────────────────────
with left_col:
    if phase == "idle":
        render_final_output_box(thinking=False, content=None)

    elif phase == "guardrail":
        render_guardrail_error(st.session_state["guardrail_message"])

    elif phase == "running":
        if ticker:
            render_ticker_chip(ticker)
        render_final_output_box(thinking=True)

        if not st.session_state["all_tiles"]:
            with st.spinner(""):
                result = run_analysis(ticker or "VTI", question)
            st.session_state["all_tiles"] = result.tiles
            st.session_state["analysis_result"] = result
            st.session_state["visible_tiles"] = 0
            st.rerun()

        all_tiles = st.session_state["all_tiles"]
        visible   = st.session_state["visible_tiles"]
        render_agent_tiles_section(all_tiles, visible)

        if visible < len(all_tiles):
            time.sleep(0.4)
            st.session_state["visible_tiles"] = visible + 1
            st.rerun()
        else:
            st.session_state["analysis_phase"] = "complete"
            st.rerun()

    elif phase == "complete":
        result = st.session_state["analysis_result"]
        if result:
            render_ticker_chip(result.ticker)
            render_final_output_box(thinking=False, content=result.final_output)
            render_agent_tiles_section(result.tiles, len(result.tiles))

# ── Right panel ───────────────────────────────────────────────────────────────
with right_col:
    display_ticker = ticker
    if phase == "complete" and st.session_state["analysis_result"]:
        display_ticker = st.session_state["analysis_result"].ticker
    render_right_panel(display_ticker)
