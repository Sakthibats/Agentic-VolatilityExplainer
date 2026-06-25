"""Options chain data via yfinance — IV skew, put/call ratio."""

from __future__ import annotations

def fetch_options_data(ticker: str) -> dict:
    """Fetch options chain metrics: ATM IV, IV rank, skew, put/call ratio."""
    try:
        import yfinance as yf

        yf_ticker = yf.Ticker(ticker.upper())
        expirations = yf_ticker.options
        if not expirations:
            return _empty(ticker)

        # Use the nearest expiry with at least 7 days out
        from datetime import date, timedelta

        today = date.today()
        min_date = today + timedelta(days=7)
        target_exp = None
        for exp in expirations:
            if date.fromisoformat(exp) >= min_date:
                target_exp = exp
                break
        if not target_exp:
            target_exp = expirations[0]

        chain = yf_ticker.option_chain(target_exp)
        calls = chain.calls
        puts = chain.puts

        # Current price for ATM reference
        info = yf_ticker.fast_info
        spot = getattr(info, "last_price", None) or getattr(info, "previous_close", None)
        if spot is None or spot <= 0:
            return _empty(ticker)

        # ATM IV: call and put closest to spot
        calls_sorted = calls.copy()
        calls_sorted["dist"] = (calls_sorted["strike"] - spot).abs()
        puts_sorted = puts.copy()
        puts_sorted["dist"] = (puts_sorted["strike"] - spot).abs()

        atm_call = calls_sorted.nsmallest(1, "dist")
        atm_put = puts_sorted.nsmallest(1, "dist")

        atm_call_iv = float(atm_call["impliedVolatility"].iloc[0]) if len(atm_call) else None
        atm_put_iv = float(atm_put["impliedVolatility"].iloc[0]) if len(atm_put) else None
        atm_iv = round((atm_call_iv or 0 + atm_put_iv or 0) / 2 * 100, 1) if atm_call_iv and atm_put_iv else None

        # IV skew: OTM put IV (strike ~5% below spot) vs OTM call IV (~5% above)
        skew_put_strike = spot * 0.95
        skew_call_strike = spot * 1.05
        puts_skew = puts.copy()
        puts_skew["dist"] = (puts_skew["strike"] - skew_put_strike).abs()
        calls_skew = calls.copy()
        calls_skew["dist"] = (calls_skew["strike"] - skew_call_strike).abs()

        otm_put = puts_skew.nsmallest(1, "dist")
        otm_call = calls_skew.nsmallest(1, "dist")
        otm_put_iv = float(otm_put["impliedVolatility"].iloc[0]) if len(otm_put) else None
        otm_call_iv = float(otm_call["impliedVolatility"].iloc[0]) if len(otm_call) else None

        skew_points = None
        if otm_put_iv is not None and otm_call_iv is not None:
            skew_points = round((otm_put_iv - otm_call_iv) * 100, 1)

        # Put/call ratio by open interest
        total_put_oi = int(puts["openInterest"].fillna(0).sum())
        total_call_oi = int(calls["openInterest"].fillna(0).sum())
        pc_ratio = round(total_put_oi / total_call_oi, 2) if total_call_oi > 0 else None

        # Rough IV rank across all call strikes for this expiry
        all_ivs = calls["impliedVolatility"].dropna().tolist() + puts["impliedVolatility"].dropna().tolist()
        if all_ivs and atm_iv is not None:
            iv_min = min(all_ivs) * 100
            iv_max = max(all_ivs) * 100
            iv_rank = round((atm_iv - iv_min) / (iv_max - iv_min) * 100) if iv_max > iv_min else None
        else:
            iv_rank = None

        days_to_exp = (date.fromisoformat(target_exp) - today).days

        return {
            "ticker": ticker.upper(),
            "expiry": target_exp,
            "days_to_expiry": days_to_exp,
            "atm_iv_pct": atm_iv,
            "iv_rank": iv_rank,
            "skew_points": skew_points,
            "put_call_ratio": pc_ratio,
            "total_put_oi": total_put_oi,
            "total_call_oi": total_call_oi,
        }

    except Exception as exc:
        return {**_empty(ticker), "error": str(exc)}


def _empty(ticker: str) -> dict:
    return {
        "ticker": ticker.upper(),
        "expiry": None,
        "days_to_expiry": None,
        "atm_iv_pct": None,
        "iv_rank": None,
        "skew_points": None,
        "put_call_ratio": None,
        "total_put_oi": None,
        "total_call_oi": None,
    }
