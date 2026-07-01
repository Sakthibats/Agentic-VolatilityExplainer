"""Design system — Apple-inspired fintech aesthetic."""

# Palette
WHITE       = "#FFFFFF"
PAGE_BG     = "#F1F3F7"
BLUE        = "#2563EB"
BLUE_DARK   = "#1D4ED8"
BLUE_LIGHT  = "#EFF6FF"
BLUE_MUTED  = "#BFDBFE"
TEXT        = "#0F172A"
TEXT_MUTED  = "#64748B"
TEXT_LIGHT  = "#94A3B8"
BORDER      = "rgba(15,23,42,0.08)"
SUCCESS     = "#16A34A"
DANGER      = "#DC2626"


def inject_theme() -> None:
    import streamlit as st

    st.markdown(
        f"""
        <style>
          @import url('https://fonts.googleapis.com/css2?family=Inter:ital,opsz,wght@0,14..32,300;0,14..32,400;0,14..32,500;0,14..32,600;0,14..32,700;0,14..32,800;1,14..32,400&display=swap');

          /* ── Base ── */
          html, body, [class*="css"] {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
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
            max-width: 1360px;
          }}

          /* ── App header ── */
          .app-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 1.2rem 0 1rem;
            border-bottom: 1px solid {BORDER};
            margin-bottom: 1.6rem;
          }}

          .header-brand {{
            display: flex;
            align-items: center;
            gap: 0.9rem;
          }}

          .header-logo {{
            width: 40px;
            height: 40px;
            border-radius: 11px;
            background: linear-gradient(145deg, #3B82F6 0%, {BLUE_DARK} 100%);
            color: white;
            font-weight: 800;
            font-size: 0.68rem;
            letter-spacing: 0.01em;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 4px 14px rgba(37,99,235,0.32), inset 0 1px 0 rgba(255,255,255,0.2);
            flex-shrink: 0;
          }}

          .header-title {{
            font-size: 1rem;
            font-weight: 700;
            color: {TEXT};
            letter-spacing: -0.03em;
            display: block;
            line-height: 1.25;
          }}

          .header-sub {{
            font-size: 0.68rem;
            color: {TEXT_MUTED};
            font-weight: 400;
            display: block;
            margin-top: 0.06rem;
            letter-spacing: -0.01em;
          }}

          .header-tag {{
            font-size: 0.6rem;
            font-weight: 600;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: {BLUE};
            background: {BLUE_LIGHT};
            border: 1px solid {BLUE_MUTED};
            padding: 0.2rem 0.65rem;
            border-radius: 999px;
          }}

          /* ── Search form card ── */
          /* st.form renders as [data-testid="stForm"] — the only reliable container
             we can style around Streamlit native inputs + buttons. */
          [data-testid="stForm"] {{
            background: {WHITE} !important;
            border: 1.5px solid {BORDER} !important;
            border-radius: 18px !important;
            padding: 0.25rem 0.35rem 0.25rem 0.9rem !important;
            box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 6px 20px rgba(0,0,0,0.05) !important;
            margin-bottom: 1.4rem !important;
            transition: box-shadow 0.2s ease, border-color 0.2s ease !important;
          }}

          [data-testid="stForm"]:focus-within {{
            border-color: {BLUE} !important;
            box-shadow: 0 0 0 4px rgba(37,99,235,0.1), 0 6px 20px rgba(0,0,0,0.05) !important;
          }}

          /* ── Analysis box ── */
          .analysis-box {{
            border-radius: 16px;
            border: 1.5px solid {BORDER};
            background: {WHITE};
            padding: 1.5rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 6px 20px rgba(0,0,0,0.04);
          }}

          .analysis-box.empty-panel {{
            min-height: 300px;
            display: flex;
            align-items: center;
            justify-content: center;
          }}

          .analysis-box.thinking {{
            border-color: {BLUE_MUTED};
            background: linear-gradient(155deg, {BLUE_LIGHT} 0%, {WHITE} 55%);
            min-height: 200px;
          }}

          .analysis-box.complete {{
            border-color: rgba(37,99,235,0.15);
          }}

          .analysis-content p {{
            font-size: 0.88rem;
            line-height: 1.85;
            color: {TEXT};
            margin: 0 0 0.65rem 0;
          }}

          .analysis-content strong {{ color: {TEXT}; font-weight: 700; }}

          .analysis-content ol, .analysis-content ul {{
            padding-left: 1.25rem;
            margin: 0.5rem 0;
          }}

          .analysis-content li {{
            font-size: 0.88rem;
            line-height: 1.75;
            color: {TEXT};
            margin-bottom: 0.45rem;
          }}

          /* ── Shimmer skeleton ── */
          @keyframes shimmer {{
            0%   {{ background-position: -700px 0; }}
            100% {{ background-position: 700px 0; }}
          }}

          .shimmer-bar {{
            height: 8px;
            border-radius: 6px;
            background: linear-gradient(90deg, {BLUE_LIGHT} 25%, {BLUE_MUTED} 50%, {BLUE_LIGHT} 75%);
            background-size: 700px 100%;
            animation: shimmer 1.6s infinite linear;
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
            margin-bottom: 1.1rem;
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

          /* ── Guardrail error box ── */
          .guardrail-box {{
            background: #FFF7ED;
            border: 1.5px solid #FED7AA;
            border-radius: 16px;
            padding: 2rem 1.5rem;
            text-align: center;
            min-height: 220px;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 0.5rem;
          }}

          .guardrail-icon {{
            font-size: 2rem;
            margin-bottom: 0.25rem;
            opacity: 0.8;
          }}

          .guardrail-title {{
            font-size: 0.95rem;
            font-weight: 700;
            color: #9A3412;
            letter-spacing: -0.015em;
          }}

          .guardrail-body {{
            font-size: 0.85rem;
            color: #C2410C;
            line-height: 1.7;
            max-width: 380px;
          }}

          .guardrail-body em {{ font-style: italic; }}
          .guardrail-body strong {{ font-weight: 700; color: #9A3412; }}

          /* ── Empty state ── */
          .empty-state {{
            color: {TEXT_LIGHT};
            font-size: 0.85rem;
            text-align: center;
            line-height: 1.75;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 0.15rem;
          }}

          .empty-icon {{
            font-size: 2rem;
            display: block;
            margin-bottom: 0.5rem;
            opacity: 0.28;
          }}

          .empty-title {{
            font-size: 0.88rem;
            font-weight: 600;
            color: #CBD5E1;
            display: block;
            margin-bottom: 0.2rem;
            letter-spacing: -0.01em;
          }}

          .empty-hint {{
            font-size: 0.78rem;
            color: #CBD5E1;
            margin-top: 0.3rem;
          }}

          .empty-hint em {{ color: #94A3B8; }}

          /* ── Ticker chip ── */
          .ticker-chip {{
            display: inline-flex;
            align-items: center;
            gap: 0.3rem;
            background: {BLUE_LIGHT};
            color: {BLUE};
            font-weight: 700;
            font-size: 0.72rem;
            letter-spacing: 0.05em;
            padding: 0.22rem 0.72rem;
            border-radius: 999px;
            border: 1px solid {BLUE_MUTED};
            margin-bottom: 0.75rem;
          }}

          /* ── Labels ── */
          .section-label, .panel-label {{
            font-size: 0.6rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            color: {TEXT_LIGHT};
            margin-bottom: 0.5rem;
          }}

          .section-label {{ margin: 1rem 0 0.55rem 0; }}

          /* ── Agent tiles ── */
          @keyframes slideUp {{
            from {{ opacity: 0; transform: translateY(8px); }}
            to   {{ opacity: 1; transform: translateY(0); }}
          }}

          .agent-tile {{
            border: 1.5px solid {BORDER};
            border-radius: 14px;
            padding: 0.95rem 1.1rem 0.95rem 1.3rem;
            background: {WHITE};
            margin-bottom: 0.5rem;
            animation: slideUp 0.28s ease-out;
            transition: box-shadow 0.18s ease, border-color 0.18s ease, transform 0.18s ease;
            position: relative;
            overflow: hidden;
            box-shadow: 0 1px 2px rgba(0,0,0,0.03);
          }}

          .agent-tile::before {{
            content: '';
            position: absolute;
            left: 0; top: 0; bottom: 0;
            width: 3px;
            background: linear-gradient(180deg, {BLUE} 0%, {BLUE_DARK} 100%);
            border-radius: 0 2px 2px 0;
          }}

          .agent-tile:hover {{
            box-shadow: 0 4px 18px rgba(37,99,235,0.1);
            border-color: {BLUE_MUTED};
            transform: translateY(-1px);
          }}

          .tile-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.28rem;
          }}

          .tile-title {{
            font-weight: 600;
            color: {TEXT};
            font-size: 0.84rem;
            letter-spacing: -0.015em;
          }}

          .tile-badge {{
            font-size: 0.58rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: {BLUE};
            background: {BLUE_LIGHT};
            padding: 0.14rem 0.48rem;
            border-radius: 999px;
            border: 1px solid {BLUE_MUTED};
          }}

          .tile-body {{
            color: {TEXT_MUTED};
            font-size: 0.82rem;
            line-height: 1.65;
            margin: 0;
          }}

          /* ── Stat grid ── */
          .stat-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 0.48rem;
          }}

          .stat-card {{
            background: {WHITE};
            border: 1.5px solid {BORDER};
            border-radius: 12px;
            padding: 0.8rem 0.95rem;
            transition: border-color 0.18s ease, box-shadow 0.18s ease;
            box-shadow: 0 1px 2px rgba(0,0,0,0.03);
          }}

          .stat-card:hover {{
            border-color: {BLUE_MUTED};
            box-shadow: 0 2px 10px rgba(37,99,235,0.07);
          }}

          .stat-label {{
            font-size: 0.58rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.09em;
            color: {TEXT_LIGHT};
            margin-bottom: 0.2rem;
          }}

          .stat-value {{
            font-size: 1.05rem;
            font-weight: 700;
            color: {TEXT};
            letter-spacing: -0.025em;
          }}

          .stat-delta.pos {{ font-size: 0.7rem; font-weight: 600; color: {SUCCESS}; margin-top:0.1rem; }}
          .stat-delta.neg {{ font-size: 0.7rem; font-weight: 600; color: {DANGER}; margin-top:0.1rem; }}
          .stat-delta.neu {{ font-size: 0.7rem; font-weight: 600; color: {TEXT_MUTED}; margin-top:0.1rem; }}

          /* ── Native Streamlit overrides ── */
          [data-testid="stTextInput"] input,
          .stTextInput > div > div > input {{
            border: none !important;
            box-shadow: none !important;
            background: transparent !important;
            background-color: transparent !important;
            font-size: 0.93rem !important;
            font-weight: 400 !important;
            color: {TEXT} !important;
            padding-left: 0.2rem !important;
            letter-spacing: -0.01em !important;
          }}

          [data-testid="stTextInput"] input::placeholder {{
            color: {TEXT_LIGHT} !important;
            font-weight: 400 !important;
          }}

          [data-testid="stTextInput"] > div,
          [data-testid="stTextInput"] > div > div {{
            border: none !important;
            background: transparent !important;
            box-shadow: none !important;
          }}

          /* Primary button */
          .stButton > button[kind="primary"] {{
            background: linear-gradient(145deg, #3B82F6 0%, {BLUE_DARK} 100%) !important;
            border: none !important;
            color: white !important;
            border-radius: 12px !important;
            font-weight: 600 !important;
            font-size: 0.875rem !important;
            padding: 0.58rem 1rem !important;
            box-shadow: 0 2px 8px rgba(37,99,235,0.28), inset 0 1px 0 rgba(255,255,255,0.12) !important;
            transition: all 0.18s ease !important;
            letter-spacing: -0.01em !important;
          }}

          .stButton > button[kind="primary"]:hover {{
            background: linear-gradient(145deg, {BLUE} 0%, #1E3A8A 100%) !important;
            box-shadow: 0 4px 16px rgba(37,99,235,0.38) !important;
            transform: translateY(-1px);
          }}

          .stButton > button[kind="primary"]:active {{
            transform: translateY(0) !important;
            box-shadow: 0 1px 4px rgba(37,99,235,0.25) !important;
          }}

          /* Secondary button (period selector) */
          .stButton > button[kind="secondary"] {{
            background: transparent !important;
            border: 1.5px solid {BORDER} !important;
            color: {TEXT_MUTED} !important;
            border-radius: 8px !important;
            font-weight: 500 !important;
            font-size: 0.74rem !important;
            padding: 0.22rem 0.35rem !important;
            transition: all 0.15s ease !important;
          }}

          .stButton > button[kind="secondary"]:hover {{
            background: {BLUE_LIGHT} !important;
            border-color: {BLUE_MUTED} !important;
            color: {BLUE} !important;
          }}

          /* Remove stray borders */
          div[data-testid="stVerticalBlockBorderWrapper"] > div {{
            border: none !important;
            box-shadow: none !important;
            border-radius: 0 !important;
            background: transparent !important;
          }}

          [data-testid="column"] {{ background: transparent; }}

          div[data-testid="stPlotlyChart"] {{
            border-radius: 8px;
            overflow: hidden;
          }}

          /* Scrollbar */
          ::-webkit-scrollbar {{ width: 4px; }}
          ::-webkit-scrollbar-track {{ background: transparent; }}
          ::-webkit-scrollbar-thumb {{ background: rgba(0,0,0,0.1); border-radius: 3px; }}
          ::-webkit-scrollbar-thumb:hover {{ background: {BLUE_MUTED}; }}
        </style>
        """,
        unsafe_allow_html=True,
    )
