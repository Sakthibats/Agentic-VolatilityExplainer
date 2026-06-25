"""Reusable Streamlit UI components — Apple-esque fintech design."""

from __future__ import annotations

import re

import streamlit as st

from ui.placeholders import AgentTile, QuickStat
from ui.theme import BLUE, PAGE_BG

_AGENT_ICONS: dict[str, str] = {
    "price":   "📊",
    "options": "📉",
    "news":    "📰",
    "macro":   "🌐",
    "events":  "📅",
}


# ── Markdown → HTML converter (for the analysis box) ─────────────────────────

def _md_to_html(text: str) -> str:
    """Convert Claude's markdown output to safe inline HTML."""
    lines = text.split("\n")
    out: list[str] = []
    in_list: str | None = None  # "ol" or "ul"

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append(f"</{in_list}>")
            in_list = None

    def fmt(s: str) -> str:
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"_([^_\n]+)_", r"<em>\1</em>", s)
        s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", s)
        return s

    for line in lines:
        stripped = line.strip()
        if not stripped:
            close_list()
            continue

        # Numbered list
        m = re.match(r"^(\d+)\.\s+(.+)$", stripped)
        if m:
            if in_list == "ul":
                close_list()
            if not in_list:
                out.append('<ol class="analysis-list" style="margin:0.5rem 0 0.75rem 1.4rem;padding:0;">')
                in_list = "ol"
            out.append(f'<li style="margin-bottom:0.45rem;font-size:0.875rem;line-height:1.65;color:#1D1D1F;">{fmt(m.group(2))}</li>')
            continue

        # Bullet list
        m2 = re.match(r"^[-•]\s+(.+)$", stripped)
        if m2:
            if in_list == "ol":
                close_list()
            if not in_list:
                out.append('<ul class="analysis-list" style="margin:0.5rem 0 0.75rem 1.4rem;padding:0;">')
                in_list = "ul"
            out.append(f'<li style="margin-bottom:0.45rem;font-size:0.875rem;line-height:1.65;color:#1D1D1F;">{fmt(m2.group(1))}</li>')
            continue

        close_list()

        # Headings
        m3 = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if m3:
            out.append(
                f'<p style="font-weight:700;font-size:0.925rem;color:#1D1D1F;'
                f'margin:0.85rem 0 0.3rem;letter-spacing:-0.01em;">{fmt(m3.group(2))}</p>'
            )
            continue

        # Regular paragraph
        out.append(
            f'<p style="font-size:0.875rem;line-height:1.75;color:#3D3D3F;margin:0 0 0.55rem 0;">{fmt(stripped)}</p>'
        )

    close_list()
    return "\n".join(out)


# ── Components ────────────────────────────────────────────────────────────────

def render_brand_header() -> None:
    st.markdown(
        '<div class="app-header">'
        '<div class="header-brand">'
        '<div class="header-logo">WD</div>'
        '<div>'
        '<span class="header-title">WhyDip</span>'
        '<span class="header-sub">Ask why any stock moved — AI explains the volatility</span>'
        '</div>'
        '</div>'
        '<span class="header-tag">Beta</span>'
        '</div>',
        unsafe_allow_html=True,
    )


def render_search_bar() -> str:
    st.markdown('<div class="search-card">', unsafe_allow_html=True)
    col_input, col_btn = st.columns([8, 1], gap="small", vertical_alignment="center")
    with col_input:
        query = st.text_input(
            "Search",
            placeholder="e.g. why did tesla dip?  or  rklb  or  why is AAPL IV elevated?",
            label_visibility="collapsed",
            key="search_input",
        )
    with col_btn:
        submitted = st.button("Analyze →", type="primary", use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

    if submitted and query.strip():
        st.session_state["submitted_query"] = query.strip()
        st.session_state["analysis_phase"] = "running"
        st.session_state["visible_tiles"] = 0
        st.session_state["analysis_result"] = None
        st.session_state["all_tiles"] = []
    return query


def render_final_output_box(*, thinking: bool, content: str | None = None) -> None:
    st.markdown('<p class="panel-label">Analysis</p>', unsafe_allow_html=True)

    if thinking:
        st.markdown(
            '<div class="analysis-box thinking">'
            '<div class="thinking-label">Agents collecting market data'
            '<span class="thinking-dots"><span>·</span><span>·</span><span>·</span></span>'
            '</div>'
            '<div class="shimmer-bar w80"></div>'
            '<div class="shimmer-bar w60"></div>'
            '<div class="shimmer-bar w45"></div>'
            '<div class="shimmer-bar w80" style="margin-top:0.5rem;"></div>'
            '<div class="shimmer-bar w60"></div>'
            '</div>',
            unsafe_allow_html=True,
        )
    elif content:
        # Convert markdown to HTML so everything renders in one block (no overflow)
        body_html = _md_to_html(content)
        st.markdown(
            f'<div class="analysis-box complete">'
            f'<div class="analysis-content">{body_html}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="analysis-box">'
            '<div class="empty-state">'
            '<span class="empty-icon">📈</span>'
            'Enter a ticker above to get an AI-powered breakdown<br>'
            'of why implied volatility is elevated or depressed.'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )


def render_agent_tile(tile: AgentTile) -> None:
    icon = _AGENT_ICONS.get(tile.agent, "🔍")
    st.markdown(
        f'<div class="agent-tile">'
        f'<div class="tile-header">'
        f'<span class="tile-title">{icon}&nbsp;{tile.title}</span>'
        f'<span class="tile-badge">{tile.source}</span>'
        f'</div>'
        f'<p class="tile-body">{tile.summary}</p>'
        f'</div>',
        unsafe_allow_html=True,
    )


def render_agent_tiles_section(tiles: list[AgentTile], visible_count: int) -> None:
    if not tiles and visible_count == 0:
        return
    st.markdown('<p class="section-label">Agent findings</p>', unsafe_allow_html=True)
    for tile in tiles[:visible_count]:
        render_agent_tile(tile)


def render_price_chart(df, ticker: str) -> None:
    st.markdown(
        f'<p class="panel-label">{ticker} · 6-Month Price</p>',
        unsafe_allow_html=True,
    )
    chart_df = df.set_index("date")[["close"]]
    st.line_chart(chart_df, color=BLUE, height=195)


def render_quick_stats(stats: list[QuickStat]) -> None:
    st.markdown('<p class="section-label" style="margin-top:1rem;">Quick stats</p>', unsafe_allow_html=True)
    cards: list[str] = []
    for stat in stats:
        if stat.delta:
            css = "pos" if stat.delta.startswith("+") else ("neg" if stat.delta.startswith("-") else "neu")
            delta_html = f'<div class="stat-delta {css}">{stat.delta}</div>'
        else:
            delta_html = ""
        cards.append(
            f'<div class="stat-card">'
            f'<div class="stat-label">{stat.label}</div>'
            f'<div class="stat-value">{stat.value}</div>'
            f'{delta_html}'
            f'</div>'
        )
    st.markdown(f'<div class="stat-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


def render_right_panel(ticker: str | None) -> None:
    if not ticker:
        st.markdown(
            '<div class="analysis-box" style="min-height:360px;">'
            '<div class="empty-state">'
            '<span class="empty-icon">📋</span>'
            'Price chart and key stats<br>will appear here once you enter a ticker.'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )
    else:
        from ui.placeholders import fetch_price_history, fetch_quick_stats

        render_price_chart(fetch_price_history(ticker), ticker)
        render_quick_stats(fetch_quick_stats(ticker))


def render_ticker_chip(ticker: str) -> None:
    st.markdown(
        f'<div class="ticker-chip">▲&nbsp;{ticker}</div>',
        unsafe_allow_html=True,
    )


