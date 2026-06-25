"""Design system — Apple-esque minimalist fintech."""

# Palette
WHITE       = "#FFFFFF"
PAGE_BG     = "#F5F7FA"
BLUE        = "#0071E3"
BLUE_DARK   = "#0058B2"
BLUE_LIGHT  = "#EBF3FF"
BLUE_MUTED  = "#B8D6F8"
TEXT        = "#1D1D1F"
TEXT_MUTED  = "#86868B"
TEXT_LIGHT  = "#ADADB3"
BORDER      = "rgba(0,0,0,0.08)"
SUCCESS     = "#1A7F37"
DANGER      = "#CF222E"

# Keep legacy aliases so existing imports don't break
BLUE_PRIMARY = BLUE
BLUE_ACCENT  = BLUE
BLUE_HOVER   = BLUE_DARK
BLUE_SUBTLE  = BLUE_MUTED
SLATE        = TEXT
SLATE_MUTED  = TEXT_MUTED
SLATE_LIGHT  = TEXT_LIGHT
SURFACE      = PAGE_BG
SURFACE_BLUE = BLUE_LIGHT
BORDER_BLUE  = BLUE_MUTED


def inject_theme() -> None:
    import streamlit as st

    st.markdown(
        f"""
        <style>
          @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

          /* ── Base ── */
          html, body, [class*="css"] {{
            font-family: -apple-system, 'SF Pro Display', 'Inter', sans-serif;
            -webkit-font-smoothing: antialiased;
          }}

          .stApp {{
            background: {PAGE_BG};
          }}

          header[data-testid="stHeader"] {{
            background: transparent;
            height: 0;
          }}

          .block-container {{
            padding-top: 0 !important;
            padding-bottom: 3rem;
            max-width: 1320px;
          }}

          /* ── App header (replaces gradient nav bar) ── */
          .app-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 1.25rem 0 1.1rem;
            border-bottom: 1px solid {BORDER};
            margin-bottom: 1.75rem;
            background: {PAGE_BG};
          }}

          .header-brand {{
            display: flex;
            align-items: center;
            gap: 0.85rem;
          }}

          .header-logo {{
            width: 40px;
            height: 40px;
            border-radius: 11px;
            background: {BLUE};
            color: white;
            font-weight: 800;
            font-size: 0.88rem;
            letter-spacing: -0.03em;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 2px 8px rgba(0,113,227,0.35);
            flex-shrink: 0;
          }}

          .header-title {{
            font-size: 1.1rem;
            font-weight: 700;
            color: {TEXT};
            letter-spacing: -0.025em;
            display: block;
            line-height: 1.2;
          }}

          .header-sub {{
            font-size: 0.72rem;
            color: {TEXT_MUTED};
            font-weight: 400;
            display: block;
            margin-top: 0.05rem;
          }}

          .header-tag {{
            font-size: 0.65rem;
            font-weight: 600;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            color: {BLUE};
            background: {BLUE_LIGHT};
            border: 1px solid {BLUE_MUTED};
            padding: 0.22rem 0.65rem;
            border-radius: 999px;
          }}

          /* ── Search bar ── */
          .search-card {{
            background: {WHITE};
            border: 1px solid {BORDER};
            border-radius: 16px;
            padding: 0.5rem 0.5rem 0.5rem 1.1rem;
            display: flex;
            align-items: center;
            box-shadow: 0 1px 4px rgba(0,0,0,0.04), 0 4px 20px rgba(0,0,0,0.05);
            margin-bottom: 1.5rem;
            transition: box-shadow 0.2s ease, border-color 0.2s ease;
          }}

          .search-card:focus-within {{
            border-color: {BLUE};
            box-shadow: 0 0 0 4px rgba(0,113,227,0.1), 0 4px 20px rgba(0,0,0,0.05);
          }}

          /* ── Panels (white cards) ── */
          .panel {{
            background: {WHITE};
            border: 1px solid {BORDER};
            border-radius: 20px;
            padding: 1.5rem;
            box-shadow: 0 2px 8px rgba(0,0,0,0.04), 0 8px 32px rgba(0,0,0,0.04);
          }}

          /* ── Analysis box ── */
          .analysis-box {{
            min-height: 220px;
            border-radius: 14px;
            border: 1px solid {BORDER};
            background: {WHITE};
            padding: 1.5rem;
          }}

          .analysis-box.thinking {{
            border-color: {BLUE_MUTED};
            background: linear-gradient(145deg, {BLUE_LIGHT} 0%, {WHITE} 55%);
          }}

          .analysis-box.complete {{
            border-color: rgba(0,113,227,0.2);
            background: {WHITE};
          }}

          /* Analysis content typography */
          .analysis-content p {{
            font-size: 0.9rem;
            line-height: 1.75;
            color: {TEXT};
            margin: 0 0 0.6rem 0;
          }}

          .analysis-content strong {{
            color: {TEXT};
            font-weight: 700;
          }}

          .analysis-content ol, .analysis-content ul {{
            padding-left: 1.25rem;
            margin: 0.5rem 0;
          }}

          .analysis-content li {{
            font-size: 0.875rem;
            line-height: 1.65;
            color: {TEXT};
            margin-bottom: 0.4rem;
          }}

          .analysis-title {{
            font-size: 0.95rem;
            font-weight: 700;
            color: {TEXT};
            letter-spacing: -0.01em;
            margin-bottom: 0.75rem;
            padding-bottom: 0.6rem;
            border-bottom: 1px solid {BORDER};
          }}

          /* ── Shimmer skeleton ── */
          @keyframes shimmer {{
            0%   {{ background-position: -700px 0; }}
            100% {{ background-position: 700px 0; }}
          }}

          .shimmer-bar {{
            height: 9px;
            border-radius: 6px;
            background: linear-gradient(90deg, {BLUE_LIGHT} 25%, {BLUE_MUTED} 50%, {BLUE_LIGHT} 75%);
            background-size: 700px 100%;
            animation: shimmer 1.5s infinite linear;
            margin-bottom: 0.65rem;
          }}

          .shimmer-bar.w80 {{ width: 80%; }}
          .shimmer-bar.w60 {{ width: 60%; }}
          .shimmer-bar.w45 {{ width: 45%; }}

          .thinking-label {{
            font-size: 0.78rem;
            font-weight: 600;
            color: {BLUE_DARK};
            letter-spacing: 0.01em;
            margin-bottom: 1rem;
            display: flex;
            align-items: center;
            gap: 0.35rem;
          }}

          @keyframes blink {{
            0%, 80%, 100% {{ opacity: 0.2; }}
            40%            {{ opacity: 1; }}
          }}
          .thinking-dots span {{ animation: blink 1.4s infinite both; font-size: 1.1rem; line-height:0; }}
          .thinking-dots span:nth-child(2) {{ animation-delay: 0.2s; }}
          .thinking-dots span:nth-child(3) {{ animation-delay: 0.4s; }}

          /* ── Ticker chip ── */
          .ticker-chip {{
            display: inline-flex;
            align-items: center;
            gap: 0.3rem;
            background: {BLUE_LIGHT};
            color: {BLUE};
            font-weight: 700;
            font-size: 0.75rem;
            letter-spacing: 0.04em;
            padding: 0.24rem 0.72rem;
            border-radius: 999px;
            border: 1px solid {BLUE_MUTED};
            margin-bottom: 0.8rem;
          }}

          /* ── Section labels ── */
          .section-label {{
            font-size: 0.67rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.09em;
            color: {TEXT_MUTED};
            margin: 1.1rem 0 0.65rem 0;
          }}

          .panel-label {{
            font-size: 0.67rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.09em;
            color: {TEXT_MUTED};
            margin-bottom: 0.65rem;
          }}

          /* ── Agent tiles ── */
          @keyframes slideUp {{
            from {{ opacity: 0; transform: translateY(12px); }}
            to   {{ opacity: 1; transform: translateY(0); }}
          }}

          .agent-tile {{
            border: 1px solid {BORDER};
            border-radius: 14px;
            padding: 1rem 1.15rem;
            background: {WHITE};
            margin-bottom: 0.6rem;
            animation: slideUp 0.35s ease-out;
            transition: box-shadow 0.2s ease, transform 0.2s ease;
            position: relative;
            overflow: hidden;
          }}

          .agent-tile::before {{
            content: '';
            position: absolute;
            left: 0; top: 0; bottom: 0;
            width: 3px;
            background: {BLUE};
            border-radius: 0 2px 2px 0;
          }}

          .agent-tile:hover {{
            box-shadow: 0 4px 20px rgba(0,113,227,0.1);
            transform: translateY(-1px);
          }}

          .tile-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.35rem;
          }}

          .tile-title {{
            font-weight: 600;
            color: {TEXT};
            font-size: 0.875rem;
            letter-spacing: -0.01em;
          }}

          .tile-badge {{
            font-size: 0.62rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: {BLUE};
            background: {BLUE_LIGHT};
            padding: 0.16rem 0.5rem;
            border-radius: 999px;
            border: 1px solid {BLUE_MUTED};
          }}

          .tile-body {{
            color: {TEXT_MUTED};
            font-size: 0.835rem;
            line-height: 1.6;
            margin: 0;
          }}

          /* ── Stat grid ── */
          .stat-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 0.55rem;
          }}

          .stat-card {{
            background: {PAGE_BG};
            border: 1px solid {BORDER};
            border-radius: 12px;
            padding: 0.8rem 1rem;
            transition: border-color 0.2s ease;
          }}

          .stat-card:hover {{ border-color: {BLUE_MUTED}; }}

          .stat-label {{
            font-size: 0.63rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.07em;
            color: {TEXT_LIGHT};
            margin-bottom: 0.2rem;
          }}

          .stat-value {{
            font-size: 1.05rem;
            font-weight: 700;
            color: {TEXT};
            letter-spacing: -0.02em;
          }}

          .stat-delta.pos {{ font-size: 0.72rem; font-weight: 600; color: {SUCCESS}; margin-top:0.1rem; }}
          .stat-delta.neg {{ font-size: 0.72rem; font-weight: 600; color: {DANGER}; margin-top:0.1rem; }}
          .stat-delta.neu {{ font-size: 0.72rem; font-weight: 600; color: {TEXT_MUTED}; margin-top:0.1rem; }}

          /* ── Empty state ── */
          .empty-state {{
            color: {TEXT_LIGHT};
            font-size: 0.875rem;
            text-align: center;
            padding: 3rem 1.5rem;
            line-height: 1.65;
          }}

          .empty-icon {{ font-size: 2.2rem; display: block; margin-bottom: 0.6rem; opacity: 0.35; }}

          /* ── Streamlit native overrides ── */
          [data-testid="stTextInput"] input,
          .stTextInput > div > div > input {{
            border: none !important;
            box-shadow: none !important;
            background: {WHITE} !important;
            background-color: {WHITE} !important;
            font-size: 0.95rem !important;
            color: {TEXT} !important;
            padding-left: 0.25rem !important;
          }}

          [data-testid="stTextInput"] input::placeholder,
          .stTextInput > div > div > input::placeholder {{
            color: {TEXT_LIGHT} !important;
          }}

          [data-testid="stTextInput"] > div,
          [data-testid="stTextInput"] > div > div,
          .stTextInput > div,
          .stTextInput > div > div {{
            border: none !important;
            background: {WHITE} !important;
            background-color: {WHITE} !important;
            box-shadow: none !important;
          }}

          /* Primary button → Apple blue */
          .stButton > button[kind="primary"] {{
            background: {BLUE} !important;
            border: none !important;
            color: white !important;
            border-radius: 11px !important;
            font-weight: 600 !important;
            font-size: 0.875rem !important;
            padding: 0.6rem 1.1rem !important;
            box-shadow: 0 1px 4px rgba(0,113,227,0.3) !important;
            transition: background 0.2s ease, box-shadow 0.2s ease !important;
            letter-spacing: -0.01em !important;
          }}

          .stButton > button[kind="primary"]:hover {{
            background: {BLUE_DARK} !important;
            box-shadow: 0 2px 10px rgba(0,113,227,0.4) !important;
          }}

          .stButton > button[kind="primary"]:active {{
            background: #004A9A !important;
          }}

          /* Remove Streamlit container borders we don't want */
          div[data-testid="stVerticalBlockBorderWrapper"] > div {{
            border: none !important;
            box-shadow: none !important;
            border-radius: 0 !important;
            background: transparent !important;
          }}

          /* Hide default Streamlit element borders on columns */
          [data-testid="column"] {{
            background: transparent;
          }}

          /* Vega-lite chart */
          div[data-testid="stArrowVegaLiteChart"] {{
            border-radius: 10px;
            overflow: hidden;
          }}

          /* Scrollbar */
          ::-webkit-scrollbar {{ width: 5px; }}
          ::-webkit-scrollbar-track {{ background: transparent; }}
          ::-webkit-scrollbar-thumb {{ background: rgba(0,0,0,0.12); border-radius: 3px; }}
          ::-webkit-scrollbar-thumb:hover {{ background: {BLUE_MUTED}; }}
        </style>
        """,
        unsafe_allow_html=True,
    )
