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

          /* Sticky footer: chain flex:1 down through Streamlit's real nesting
             (stAppViewContainer > stMain > stMainBlockContainer > stVerticalBlock), then
             margin-top:auto on the outer vertical block's last child (the footer, since
             render_footer() is always called last) pushes it to the bottom of the
             viewport instead of floating right under short content. Confirmed via the
             actual rendered DOM (Streamlit 1.58) rather than assumed. */
          [data-testid="stAppViewContainer"] {{
            min-height: 100vh;
            display: flex;
            flex-direction: column;
          }}

          [data-testid="stMain"] {{
            flex: 1;
            display: flex;
            flex-direction: column;
          }}

          .block-container, [data-testid="stMainBlockContainer"] {{
            padding-top: 0 !important;
            padding-bottom: 3rem;
            max-width: 1360px;
            flex: 1;
            display: flex;
            flex-direction: column;
          }}

          [data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] {{
            flex: 1;
            display: flex;
            flex-direction: column;
          }}

          [data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] > div:last-child {{
            margin-top: auto;
          }}

          /* ── App header ── */
          /* st.container(key="app_header_row") wraps the brand block, Beta tag, and the
             Home/About nav in one row — this carries the border/padding that used to live
             on a plain .app-header div, so the nav visually belongs to the header bar. */
          .st-key-app_header_row {{
            padding: 0.7rem 0 0.9rem;
            border-bottom: 1px solid {BORDER};
            margin-bottom: 1.6rem;
          }}

          .st-key-app_header_row [data-testid="stHorizontalBlock"] {{
            align-items: center !important;
          }}

          .header-brand {{
            display: flex;
            align-items: center;
            gap: 0.9rem;
          }}

          .header-tag-wrap {{
            display: flex;
            justify-content: flex-end;
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

          /* ── App footer ── */
          .app-footer {{
            margin-top: 2.4rem;
            padding: 1.4rem 0 2rem;
            border-top: 1px solid {BORDER};
          }}

          .footer-disclaimer {{
            font-size: 0.72rem;
            line-height: 1.65;
            color: {TEXT_LIGHT};
            max-width: 860px;
            margin: 0 0 0.9rem 0;
          }}

          .footer-disclaimer strong {{
            color: {TEXT_MUTED};
          }}

          .footer-bottom {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 0.6rem;
          }}

          .footer-meta {{
            font-size: 0.68rem;
            color: {TEXT_LIGHT};
          }}

          .footer-feedback-pill {{
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            font-size: 0.7rem;
            font-weight: 600;
            color: {BLUE} !important;
            background: {BLUE_LIGHT};
            border: 1px solid {BLUE_MUTED};
            padding: 0.32rem 0.8rem;
            border-radius: 999px;
            text-decoration: none !important;
            transition: background 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease;
          }}

          .footer-feedback-pill:hover {{
            background: {BLUE};
            color: {WHITE};
            transform: translateY(-1px);
            box-shadow: 0 4px 14px rgba(37,99,235,0.25);
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


          .tile-body {{
            color: {TEXT_MUTED};
            font-size: 0.82rem;
            line-height: 1.65;
            margin: 0;
          }}

          .citations-row {{
            display: flex;
            gap: 0.35rem;
            margin-top: 0.55rem;
          }}

          .citation-pill {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 1.15rem;
            height: 1.15rem;
            border-radius: 999px;
            background: {BLUE_LIGHT};
            border: 1px solid {BLUE_MUTED};
            color: {BLUE};
            font-size: 0.65rem;
            font-weight: 600;
            text-decoration: none;
            transition: background 0.15s ease, transform 0.15s ease;
          }}

          .citation-pill:hover {{
            background: {BLUE};
            color: {WHITE};
            transform: translateY(-1px);
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

          /* ── About page ── */
          .about-hero {{
            padding: 0.4rem 0 1.6rem;
          }}

          .about-hero-title {{
            font-size: 1.5rem;
            font-weight: 800;
            color: {TEXT};
            letter-spacing: -0.03em;
            margin: 0 0 0.4rem 0;
          }}

          .about-hero-sub {{
            font-size: 0.9rem;
            color: {TEXT_MUTED};
            line-height: 1.6;
            max-width: 720px;
            margin: 0;
          }}

          .about-section-title {{
            font-size: 0.68rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            color: {BLUE};
            margin: 2rem 0 0.9rem 0;
            display: flex;
            align-items: center;
            gap: 0.4rem;
          }}

          .about-section-title::before {{
            content: '';
            width: 0.4rem;
            height: 0.4rem;
            border-radius: 999px;
            background: {BLUE};
          }}

          .about-step {{
            display: flex;
            gap: 0.85rem;
            padding: 0.85rem 0;
            border-bottom: 1px solid {BORDER};
          }}

          .about-step:last-child {{
            border-bottom: none;
          }}

          .about-step-icon {{
            font-size: 1rem;
            flex-shrink: 0;
            line-height: 1.5;
            opacity: 0.85;
          }}

          .about-step-title {{
            font-weight: 700;
            font-size: 0.85rem;
            color: {TEXT};
            letter-spacing: -0.01em;
            margin-bottom: 0.2rem;
          }}

          .about-step-body {{
            font-size: 0.8rem;
            color: {TEXT_MUTED};
            line-height: 1.65;
            margin: 0;
          }}

          .about-tool-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 0.6rem;
          }}

          .about-tool-card {{
            border: 1.5px solid {BORDER};
            border-radius: 14px;
            background: {WHITE};
            padding: 0.85rem 1rem;
            box-shadow: 0 1px 2px rgba(0,0,0,0.03);
            transition: border-color 0.18s ease, box-shadow 0.18s ease;
          }}

          .about-tool-card:hover {{
            border-color: {BLUE_MUTED};
            box-shadow: 0 3px 14px rgba(37,99,235,0.08);
          }}

          .about-tool-head {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
            margin-bottom: 0.3rem;
          }}

          .about-tool-name {{
            font-family: 'SFMono-Regular', ui-monospace, Menlo, monospace;
            font-size: 0.76rem;
            font-weight: 700;
            color: {TEXT};
          }}

          .about-tool-module {{
            font-size: 0.62rem;
            color: {TEXT_LIGHT};
            background: {PAGE_BG};
            border-radius: 999px;
            padding: 0.1rem 0.5rem;
            margin-left: auto;
          }}

          .about-tool-desc {{
            font-size: 0.78rem;
            color: {TEXT_MUTED};
            line-height: 1.6;
            margin: 0;
          }}

          .about-limitations {{
            border: 1.5px solid {BORDER};
            border-radius: 14px;
            background: {WHITE};
            padding: 1.1rem 1.3rem;
            box-shadow: 0 1px 2px rgba(0,0,0,0.03);
          }}

          .about-limitations li {{
            font-size: 0.82rem;
            color: {TEXT_MUTED};
            line-height: 1.75;
            margin-bottom: 0.4rem;
          }}

          .about-limitations li:last-child {{ margin-bottom: 0; }}

          .roadmap-card {{
            display: flex;
            align-items: flex-start;
            gap: 0.75rem;
            border: 1.5px solid {BORDER};
            border-radius: 14px;
            background: {WHITE};
            padding: 0.85rem 1.1rem;
            margin-bottom: 0.55rem;
            box-shadow: 0 1px 2px rgba(0,0,0,0.03);
          }}

          .roadmap-badge {{
            flex-shrink: 0;
            font-size: 0.58rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            padding: 0.25rem 0.55rem;
            border-radius: 999px;
            margin-top: 0.1rem;
            white-space: nowrap;
          }}

          .roadmap-badge.planned {{
            background: {PAGE_BG};
            color: {TEXT_MUTED};
            border: 1px solid {BORDER};
          }}

          .roadmap-badge.in-progress {{
            background: {BLUE_LIGHT};
            color: {BLUE};
            border: 1px solid {BLUE_MUTED};
          }}

          .roadmap-badge.shipped {{
            background: #F0FDF4;
            color: {SUCCESS};
            border: 1px solid #BBF7D0;
          }}

          .roadmap-title {{
            font-weight: 700;
            font-size: 0.84rem;
            color: {TEXT};
            letter-spacing: -0.01em;
            margin-bottom: 0.2rem;
          }}

          .roadmap-body {{
            font-size: 0.8rem;
            color: {TEXT_MUTED};
            line-height: 1.6;
            margin: 0;
          }}

          [data-testid="stExpander"] {{
            border: 1.5px solid {BORDER} !important;
            border-radius: 14px !important;
            background: {WHITE} !important;
            box-shadow: 0 1px 2px rgba(0,0,0,0.03) !important;
            margin-bottom: 0.5rem !important;
          }}

          [data-testid="stExpander"] summary {{
            font-size: 0.85rem !important;
            font-weight: 600 !important;
            color: {TEXT} !important;
          }}

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

          /* ── Header nav (Home / About) ── */
          /* Rounded "segmented control" pill nav, built from st.button so a click is a
             normal Streamlit rerun (no browser navigation/page reload) rather than an
             <a href> — but Streamlit's own button skin has to be fully wiped first.
             `all: unset` resets every property (background image, border, box-shadow,
             outline, appearance) in one shot instead of chasing each one — a previous pass
             that overrode individual properties still lost fights over ones it forgot
             (box-shadow, outline) to Streamlit's own :hover/:focus rules. Repeating the
             reset in each pseudo-state block (not just the base rule) matters because
             those are separate rules the browser evaluates independently. */
          .st-key-nav_group {{
            display: inline-flex !important;
            margin-left: auto;
            background: {PAGE_BG};
            border: 1px solid {BORDER};
            border-radius: 999px;
            padding: 0.2rem;
          }}

          .st-key-nav_group [data-testid="stHorizontalBlock"] {{
            gap: 0.15rem !important;
          }}

          .st-key-nav_home, .st-key-nav_about {{
            width: auto !important;
          }}

          .st-key-nav_home .stButton, .st-key-nav_about .stButton {{
            display: flex !important;
            justify-content: center !important;
          }}

          .st-key-nav_home button[kind],
          .st-key-nav_about button[kind] {{
            all: unset !important;
            box-sizing: border-box !important;
            cursor: pointer !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
            font-size: 0.8rem !important;
            font-weight: 600 !important;
            color: {TEXT_MUTED} !important;
            padding: 0.3rem 0.85rem !important;
            border: 1.5px solid transparent !important;
            border-radius: 999px !important;
            white-space: nowrap !important;
          }}

          .st-key-nav_home button[kind]:hover,
          .st-key-nav_about button[kind]:hover {{
            all: unset !important;
            box-sizing: border-box !important;
            cursor: pointer !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
            font-size: 0.8rem !important;
            font-weight: 600 !important;
            padding: 0.3rem 0.85rem !important;
            border: 1.5px solid transparent !important;
            border-radius: 999px !important;
            white-space: nowrap !important;
            color: {BLUE_DARK} !important;
            background: rgba(37,99,235,0.08) !important;
          }}

          .st-key-nav_home button[kind]:focus,
          .st-key-nav_about button[kind]:focus,
          .st-key-nav_home button[kind]:focus-visible,
          .st-key-nav_about button[kind]:focus-visible,
          .st-key-nav_home button[kind]:active,
          .st-key-nav_about button[kind]:active {{
            all: unset !important;
            box-sizing: border-box !important;
            cursor: pointer !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
            font-size: 0.8rem !important;
            font-weight: 600 !important;
            padding: 0.3rem 0.85rem !important;
            border: 1.5px solid transparent !important;
            border-radius: 999px !important;
            white-space: nowrap !important;
            color: {TEXT_MUTED} !important;
          }}

          .st-key-nav_home button[kind="primary"],
          .st-key-nav_about button[kind="primary"] {{
            all: unset !important;
            box-sizing: border-box !important;
            cursor: pointer !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
            font-size: 0.8rem !important;
            font-weight: 600 !important;
            padding: 0.3rem 0.85rem !important;
            border: 1.5px solid {BLUE_MUTED} !important;
            border-radius: 999px !important;
            white-space: nowrap !important;
            color: {BLUE} !important;
            background: {WHITE} !important;
          }}

          .st-key-nav_home button[kind="primary"]:hover,
          .st-key-nav_about button[kind="primary"]:hover,
          .st-key-nav_home button[kind="primary"]:focus,
          .st-key-nav_about button[kind="primary"]:focus,
          .st-key-nav_home button[kind="primary"]:focus-visible,
          .st-key-nav_about button[kind="primary"]:focus-visible,
          .st-key-nav_home button[kind="primary"]:active,
          .st-key-nav_about button[kind="primary"]:active {{
            all: unset !important;
            box-sizing: border-box !important;
            cursor: pointer !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
            font-size: 0.8rem !important;
            font-weight: 600 !important;
            padding: 0.3rem 0.85rem !important;
            border: 1.5px solid {BLUE_MUTED} !important;
            border-radius: 999px !important;
            white-space: nowrap !important;
            color: {BLUE} !important;
            background: {WHITE} !important;
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

          /* Hide Streamlit branding */
          #MainMenu {{ visibility: hidden; }}
          footer {{ visibility: hidden; }}
          header {{ visibility: hidden; }}
          div[data-testid="stStatusWidget"] {{ visibility: hidden; }}
        </style>
        """,
        unsafe_allow_html=True,
    )
