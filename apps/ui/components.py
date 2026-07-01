"""Reusable Streamlit UI components."""

from __future__ import annotations

import re

import streamlit as st

from ui.placeholders import AgentTile, QuickStat
from ui.theme import BLUE, BLUE_DARK, BLUE_LIGHT, BLUE_MUTED, DANGER

_AGENT_ICONS: dict[str, str] = {
    "price":   "📊",
    "options": "📉",
    "news":    "📰",
    "macro":   "🌐",
    "events":  "📅",
}

_PERIODS = ["1W", "1M", "6M", "YTD", "1Y"]


# ── Markdown → HTML ──────────────────────────────────────────────────────────

def _md_to_html(text: str) -> str:
    lines = text.split("\n")
    out: list[str] = []
    in_list: str | None = None

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

        m = re.match(r"^(\d+)\.\s+(.+)$", stripped)
        if m:
            if in_list == "ul":
                close_list()
            if not in_list:
                out.append('<ol class="analysis-list" style="margin:0.5rem 0 0.75rem 1.4rem;padding:0;">')
                in_list = "ol"
            out.append(f'<li style="margin-bottom:0.5rem;font-size:0.88rem;line-height:1.7;color:#0F172A;">{fmt(m.group(2))}</li>')
            continue

        m2 = re.match(r"^[-•]\s+(.+)$", stripped)
        if m2:
            if in_list == "ol":
                close_list()
            if not in_list:
                out.append('<ul class="analysis-list" style="margin:0.5rem 0 0.75rem 1.4rem;padding:0;">')
                in_list = "ul"
            out.append(f'<li style="margin-bottom:0.5rem;font-size:0.88rem;line-height:1.7;color:#0F172A;">{fmt(m2.group(1))}</li>')
            continue

        close_list()

        m3 = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if m3:
            out.append(
                f'<p style="font-weight:700;font-size:0.95rem;color:#0F172A;'
                f'margin:0.9rem 0 0.3rem;letter-spacing:-0.015em;">{fmt(m3.group(2))}</p>'
            )
            continue

        out.append(
            f'<p style="font-size:0.88rem;line-height:1.8;color:#334155;margin:0 0 0.6rem 0;">{fmt(stripped)}</p>'
        )

    close_list()
    return "\n".join(out)


# ── Ticker autocomplete ───────────────────────────────────────────────────────

# ── Components ────────────────────────────────────────────────────────────────

def render_brand_header() -> None:
    st.markdown(
        '<div class="app-header">'
        '<div class="header-brand">'
        '<div class="header-logo">AVE</div>'
        '<div>'
        '<span class="header-title">Agentic Volatility Explainer</span>'
        '<span class="header-sub">AI investigates why any stock or market moved — multi-agent analysis</span>'
        '</div>'
        '</div>'
        '<span class="header-tag">Beta</span>'
        '</div>',
        unsafe_allow_html=True,
    )


def render_search_bar() -> str:
    # st.form gives us a real DOM container we can style as a card via CSS.
    # A custom <div> wrapper around st.columns() doesn't work — Streamlit
    # renders its own column containers outside any preceding markdown div.
    with st.form(key="search_form", clear_on_submit=False, border=False):
        col_input, col_btn = st.columns([8, 1], gap="small", vertical_alignment="center")
        with col_input:
            query = st.text_input(
                "Search",
                placeholder="Try: TSLA · why did Tesla dip? · what happened to gold? · market down?",
                label_visibility="collapsed",
                key="search_input",
            )
        with col_btn:
            submitted = st.form_submit_button(
                "Analyze →",
                type="primary",
                width="stretch",
            )

    if submitted and query.strip():
        st.session_state["submitted_query"] = query.strip()
        st.session_state["analysis_phase"] = "running"
        st.session_state["visible_tiles"] = 0
        st.session_state["analysis_result"] = None
        st.session_state["all_tiles"] = []
    return query


def render_guardrail_error(message: str) -> None:
    st.markdown('<p class="panel-label">Analysis</p>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="guardrail-box">'
        f'<div class="guardrail-icon">🚫</div>'
        f'<div class="guardrail-title">Out of scope</div>'
        f'<div class="guardrail-body">{message}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def render_thinking_step(placeholder, label: str) -> None:
    """Update a st.empty() placeholder with the current investigation step."""
    placeholder.markdown(
        f'<div class="analysis-box thinking">'
        f'<div class="thinking-label">{label}'
        f'<span class="thinking-dots"><span>·</span><span>·</span><span>·</span></span>'
        f'</div>'
        f'<div class="shimmer-bar w80"></div>'
        f'<div class="shimmer-bar w60"></div>'
        f'<div class="shimmer-bar w45"></div>'
        f'<div class="shimmer-bar w80" style="margin-top:0.5rem;"></div>'
        f'<div class="shimmer-bar w60"></div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def render_final_output_box(*, thinking: bool, content: str | None = None) -> None:
    st.markdown('<p class="panel-label">Analysis</p>', unsafe_allow_html=True)

    if thinking:
        st.markdown(
            '<div class="analysis-box thinking">'
            '<div class="thinking-label">Investigating price action'
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
        body_html = _md_to_html(content)
        st.markdown(
            f'<div class="analysis-box complete">'
            f'<div class="analysis-content">{body_html}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="analysis-box empty-panel">'
            '<div class="empty-state">'
            '<span class="empty-icon">🔍</span>'
            '<span class="empty-title">Start an investigation</span>'
            'Enter a ticker, company name, or ask a question.<br>'
            '<span class="empty-hint">Try: <em>why did AAPL dip?</em> or <em>what happened to gold?</em></span>'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )


def render_agent_tile(tile: AgentTile) -> None:
    icon = _AGENT_ICONS.get(tile.agent, "🔍")
    reasoning_html = (
        f'<p style="font-size:0.72rem;color:#64748B;font-style:italic;'
        f'margin:0 0 0.45rem 0;line-height:1.5;">→ {tile.reasoning}</p>'
        if tile.reasoning
        else ""
    )
    st.markdown(
        f'<div class="agent-tile">'
        f'{reasoning_html}'
        f'<div class="tile-header">'
        f'<span class="tile-title">{icon}&nbsp;{tile.title}</span>'
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


def render_price_chart(ticker: str) -> None:
    import plotly.graph_objects as go

    period = st.session_state.get("chart_period", "6M")

    st.markdown(
        f'<p class="panel-label" style="margin-bottom:0.4rem;">{ticker} · Price</p>',
        unsafe_allow_html=True,
    )

    # Period selector
    cols = st.columns(len(_PERIODS))
    for i, p in enumerate(_PERIODS):
        with cols[i]:
            is_active = period == p
            if st.button(p, key=f"period_{p}", type="primary" if is_active else "secondary", width="stretch"):
                st.session_state["chart_period"] = p
                st.rerun()

    from ui.placeholders import fetch_price_history
    df = fetch_price_history(ticker, period)

    if df.empty:
        st.markdown('<p style="color:#94A3B8;font-size:0.8rem;padding:1rem 0;">No price data available.</p>', unsafe_allow_html=True)
        return

    y_min = df["close"].min()
    y_max = df["close"].max()
    padding = max((y_max - y_min) * 0.1, y_max * 0.02)
    y_lo = y_min - padding
    y_hi = y_max + padding

    net_change = df["close"].iloc[-1] - df["close"].iloc[0]
    if net_change >= 0:
        line_color, fill_color = "#16A34A", "rgba(22,163,74,0.07)"
    else:
        line_color, fill_color = "#DC2626", "rgba(220,38,38,0.07)"

    tick_fmt = "%b %d" if period in ("1W", "1M") else "%b" if period in ("YTD", "6M") else "%b '%y"

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["date"],
        y=df["close"],
        mode="lines",
        line=dict(color=line_color, width=1.8),
        fill="tozeroy",
        fillcolor=fill_color,
        hovertemplate="<b>%{x|%b %d, %Y}</b><br>$%{y:,.2f}<extra></extra>",
    ))

    fig.update_layout(
        margin=dict(l=0, r=0, t=4, b=0),
        height=200,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(
            showgrid=False,
            showline=False,
            tickfont=dict(family="Inter, -apple-system, sans-serif", size=9.5, color="#94A3B8"),
            tickformat=tick_fmt,
            nticks=5,
        ),
        yaxis=dict(
            range=[y_lo, y_hi],
            showgrid=True,
            gridcolor="rgba(15,23,42,0.05)",
            gridwidth=1,
            showline=False,
            tickfont=dict(family="Inter, -apple-system, sans-serif", size=9.5, color="#94A3B8"),
            tickprefix="$",
            tickformat=",.0f",
            nticks=4,
            side="right",
        ),
        hovermode="x unified",
        font=dict(family="Inter, -apple-system, sans-serif"),
        hoverlabel=dict(
            bgcolor="white",
            bordercolor="rgba(15,23,42,0.1)",
            font=dict(family="Inter, -apple-system, sans-serif", size=12),
        ),
    )

    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def render_quick_stats(stats: list[QuickStat], title: str = "Quick stats") -> None:
    st.markdown(f'<p class="section-label" style="margin-top:0.6rem;">{title}</p>', unsafe_allow_html=True)
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
        st.markdown('<p class="panel-label">Price</p>', unsafe_allow_html=True)
        st.markdown(
            '<div class="analysis-box empty-panel" style="min-height:300px;">'
            '<div class="empty-state">'
            '<span class="empty-icon">📈</span>'
            '<span class="empty-title">Price chart</span>'
            'Chart and stats will appear<br>once you analyze a ticker.'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )
    else:
        from ui.placeholders import fetch_analyst_stats, fetch_options_stats, fetch_quick_stats
        render_price_chart(ticker)
        render_quick_stats(fetch_quick_stats(ticker))
        render_quick_stats(fetch_options_stats(ticker), title="Options stats")
        render_quick_stats(fetch_analyst_stats(ticker), title="Analyst targets")


def render_ticker_chip(ticker: str) -> None:
    st.markdown(
        f'<div class="ticker-chip">▲&nbsp;{ticker}</div>',
        unsafe_allow_html=True,
    )
