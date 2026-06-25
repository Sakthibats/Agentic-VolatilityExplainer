from volatility_explainer.config import get_settings

VIX_SERIES_ID = "VIXCLS"


def fetch_macro() -> dict:
    """Fetch macro indicators. FRED first, yfinance VIX fallback."""
    # Try FRED
    try:
        from volatility_explainer.clients.fred import FredClient
        settings = get_settings()
        if settings.fred_api_key.get_secret_value():
            vix = FredClient(settings).get_series_observations(VIX_SERIES_ID, limit=5)
            return {"vix": vix, "series_id": VIX_SERIES_ID, "source": "fred"}
    except Exception:
        pass

    # Fallback: yfinance VIX
    try:
        import yfinance as yf

        vix_hist = yf.Ticker("^VIX").history(period="5d")
        vix_current = round(float(vix_hist["Close"].iloc[-1]), 2) if not vix_hist.empty else None
        vix_prev = round(float(vix_hist["Close"].iloc[-2]), 2) if len(vix_hist) >= 2 else None
        vix_chg = round(vix_current - vix_prev, 2) if vix_current and vix_prev else None

        sp500_hist = yf.Ticker("^GSPC").history(period="5d")
        sp500_chg = None
        if len(sp500_hist) >= 2:
            sp500_chg = round(
                (float(sp500_hist["Close"].iloc[-1]) - float(sp500_hist["Close"].iloc[-2]))
                / float(sp500_hist["Close"].iloc[-2]) * 100, 2
            )

        return {
            "vix_current": vix_current,
            "vix_prev_close": vix_prev,
            "vix_change": vix_chg,
            "sp500_change_pct": sp500_chg,
            "source": "yfinance",
        }
    except Exception as exc:
        return {"error": str(exc)}
