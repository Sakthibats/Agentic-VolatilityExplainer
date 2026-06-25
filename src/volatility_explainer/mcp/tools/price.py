from volatility_explainer.config import get_settings


def fetch_price_data(ticker: str) -> dict:
    """Fetch latest price and recent performance. Alpaca first, yfinance fallback."""
    # Try Alpaca
    try:
        from volatility_explainer.clients.alpaca import AlpacaClient
        settings = get_settings()
        if settings.alpaca_api_key.get_secret_value():
            return AlpacaClient(settings).get_latest_trade(ticker)
    except Exception:
        pass

    # Fallback: yfinance
    try:
        import yfinance as yf

        t = yf.Ticker(ticker.upper())
        info = t.fast_info
        hist = t.history(period="10d")

        price = getattr(info, "last_price", None)
        prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else None
        chg_pct = round((price - prev) / prev * 100, 2) if price and prev else None

        # Simple realized vol: std of daily returns over last 20 days * sqrt(252)
        hist20 = t.history(period="1mo")
        rv = None
        if len(hist20) >= 5:
            import numpy as np
            returns = hist20["Close"].pct_change().dropna()
            rv = round(float(returns.std() * (252 ** 0.5) * 100), 1)

        return {
            "ticker": ticker.upper(),
            "price": round(price, 2) if price else None,
            "prev_close": round(prev, 2) if prev else None,
            "change_pct": chg_pct,
            "realized_vol_annualized_pct": rv,
            "source": "yfinance",
        }
    except Exception as exc:
        return {"ticker": ticker.upper(), "error": str(exc)}
