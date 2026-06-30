from volatility_explainer.config import get_settings


def fetch_price_data(ticker: str) -> dict:
    """Fetch latest price and recent performance. Alpaca first, yfinance fallback."""
    ticker = ticker.upper()

    # Try Alpaca — normalize the raw trade + bars into the same shape the
    # yfinance fallback produces below, since callers (and the LLM) depend on
    # change_pct / realized_vol_annualized_pct being present.
    try:
        from volatility_explainer.clients.alpaca import AlpacaClient
        settings = get_settings()
        if settings.alpaca_api_key.get_secret_value():
            client = AlpacaClient(settings)
            trade = client.get_latest_trade(ticker)
            price = trade.get("trade", {}).get("p")

            from datetime import date, timedelta
            start = (date.today() - timedelta(days=35)).isoformat()
            bars_raw = client.get_bars(ticker, timeframe="1Day", start=start, limit=30)
            closes = [float(b["c"]) for b in bars_raw.get("bars", []) if "c" in b]

            if price and closes:
                prev = closes[-2] if len(closes) >= 2 else closes[-1]
                chg_pct = round((price - prev) / prev * 100, 2) if prev else None

                rv = None
                if len(closes) >= 5:
                    import numpy as np
                    returns = np.diff(closes) / closes[:-1]
                    rv = round(float(np.std(returns) * (252 ** 0.5) * 100), 1)

                return {
                    "ticker": ticker,
                    "price": round(price, 2),
                    "prev_close": round(prev, 2) if prev else None,
                    "change_pct": chg_pct,
                    "realized_vol_annualized_pct": rv,
                }
    except Exception as exc:
        print(f"[price:{ticker}]  alpaca    FAILED — {exc}")

    # Fallback: yfinance
    try:
        import yfinance as yf

        t = yf.Ticker(ticker)
        info = t.fast_info
        hist = t.history(period="1mo")

        price = getattr(info, "last_price", None)
        prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else None
        chg_pct = round((price - prev) / prev * 100, 2) if price and prev else None

        rv = None
        if len(hist) >= 5:
            import numpy as np
            returns = hist["Close"].pct_change().dropna()
            rv = round(float(returns.std() * (252 ** 0.5) * 100), 1)

        return {
            "ticker": ticker,
            "price": round(price, 2) if price else None,
            "prev_close": round(prev, 2) if prev else None,
            "change_pct": chg_pct,
            "realized_vol_annualized_pct": rv,
        }
    except Exception as exc:
        print(f"[price:{ticker}]  yfinance  FAILED — {exc}")
        return {"ticker": ticker, "error": str(exc)}
