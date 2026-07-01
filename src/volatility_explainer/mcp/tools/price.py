from datetime import date, timedelta

from volatility_explainer.config import get_settings


def fetch_price_data(ticker: str) -> dict:
    """Fetch latest price and recent performance. Massive first, Finnhub second, yfinance fallback."""
    ticker = ticker.upper()

    # # Try Massive (Polygon-compatible) — daily aggs for price, prev close, and realized vol
    # try:
    #     from volatility_explainer.clients.massive import MassiveClient

    #     settings = get_settings()
    #     if settings.massive_api_key.get_secret_value():
    #         client = MassiveClient(settings)
    #         to_date = date.today().isoformat()
    #         from_date = (date.today() - timedelta(days=45)).isoformat()
    #         aggs = client.get_aggs(ticker, from_date=from_date, to_date=to_date)
    #         closes = [float(r["c"]) for r in (aggs.get("results") or []) if "c" in r]

    #         if len(closes) >= 2:
    #             price = closes[-1]
    #             prev_close = closes[-2]
    #             chg_pct = round((price - prev_close) / prev_close * 100, 2)

    #             rv = None
    #             if len(closes) >= 5:
    #                 import numpy as np
    #                 returns = np.diff(closes) / closes[:-1]
    #                 rv = round(float(np.std(returns) * (252 ** 0.5) * 100), 1)

    #             return {
    #                 "ticker": ticker,
    #                 "price": round(price, 2),
    #                 "prev_close": round(prev_close, 2),
    #                 "change_pct": chg_pct,
    #                 "realized_vol_annualized_pct": rv,
    #             }
    # except Exception as exc:
    #     print(f"[price:{ticker}]  massive   FAILED — {exc}")

    # Try Finnhub — quote for price/change, candles for realized vol (candles require paid plan)
    try:
        from volatility_explainer.clients.finnhub import FinnhubClient
        import time as _time

        settings = get_settings()
        if settings.finnhub_api_key.get_secret_value():
            client = FinnhubClient(settings)
            quote = client.get_quote(ticker)
            price = quote.get("c")
            prev_close = quote.get("pc")
            chg_pct = round((price - prev_close) / prev_close * 100, 2) if price and prev_close else None

            rv = None
            try:
                to_ts = int(_time.time())
                from_ts = to_ts - 45 * 86400
                candles = client.get_candles(ticker, resolution="D", from_ts=from_ts, to_ts=to_ts)
                closes = candles.get("c", []) if candles.get("s") == "ok" else []
                if len(closes) >= 5:
                    import numpy as np
                    returns = np.diff(closes) / closes[:-1]
                    rv = round(float(np.std(returns) * (252 ** 0.5) * 100), 1)
            except Exception:
                pass  # candles require paid Finnhub plan; rv stays None

            if price:
                return {
                    "ticker": ticker,
                    "price": round(price, 2),
                    "prev_close": round(prev_close, 2) if prev_close else None,
                    "change_pct": chg_pct,
                    "realized_vol_annualized_pct": rv,
                }
    except Exception as exc:
        print(f"[price:{ticker}]  finnhub   FAILED — {exc}")

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
