"""Options chain data via yfinance — IV skew, put/call ratio, and deeper positioning analysis."""

from __future__ import annotations


def fetch_options_data(ticker: str) -> dict:
    """Fetch options chain metrics: ATM IV, IV rank, skew, put/call ratio."""
    try:
        import yfinance as yf

        yf_ticker = yf.Ticker(ticker.upper())
        expirations = yf_ticker.options
        if not expirations:
            return _empty(ticker)

        # Prefer an expiry inside the 2-4 week investigation horizon; fall back to
        # the nearest one at least 7 days out if nothing falls in that window.
        from datetime import date, timedelta

        today = date.today()
        target_exp = None
        for exp in expirations:
            days_out = (date.fromisoformat(exp) - today).days
            if 14 <= days_out <= 28:
                target_exp = exp
                break
        if not target_exp:
            min_date = today + timedelta(days=7)
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


def _max_pain(calls, puts) -> float | None:
    """Strike that minimizes total option-writer payout at expiry — where price tends to gravitate."""
    call_oi = calls.set_index("strike")["openInterest"].fillna(0)
    put_oi = puts.set_index("strike")["openInterest"].fillna(0)
    strikes = sorted(set(call_oi.index) | set(put_oi.index))
    if not strikes:
        return None

    best_strike, best_pain = None, None
    for s in strikes:
        call_pain = sum(oi * max(0.0, s - k) for k, oi in call_oi.items())
        put_pain = sum(oi * max(0.0, k - s) for k, oi in put_oi.items())
        total = call_pain + put_pain
        if best_pain is None or total < best_pain:
            best_pain, best_strike = total, s
    return float(best_strike) if best_strike is not None else None


def fetch_options_positioning(ticker: str) -> dict:
    """General options-positioning check for the 2-4 week horizon.

    Answers a simple question: how is the market pricing the next few weeks for
    this stock, and what does that hint about what's next? Returns max pain,
    call/put open-interest walls (support/resistance), IV term structure across
    the horizon, unusual volume vs. open interest (fresh bets vs. stale OI), and
    a net directional lean from OTM call vs. OTM put open interest.
    """
    ticker = ticker.upper()
    try:
        import yfinance as yf
        from datetime import date

        yf_ticker = yf.Ticker(ticker)
        expirations = yf_ticker.options
        if not expirations:
            return {"ticker": ticker, "error": "No options data available."}

        today = date.today()

        # 2-4 week horizon (12-30 days gives a little slack around weekly/monthly
        # expiry cadences); cap to 3 expiries to keep yfinance calls bounded.
        horizon = [exp for exp in expirations if 12 <= (date.fromisoformat(exp) - today).days <= 30]
        if not horizon:
            horizon = sorted(
                expirations,
                key=lambda e: abs((date.fromisoformat(e) - today).days - 21),
            )[:1]
        horizon = horizon[:3]

        info = yf_ticker.fast_info
        spot = getattr(info, "last_price", None) or getattr(info, "previous_close", None)
        if not spot:
            return {"ticker": ticker, "error": "No spot price available."}
        spot = float(spot)

        term_structure: list[dict] = []
        nearest = None  # (expiry, days_to_expiry, calls_df, puts_df)

        for exp in horizon:
            try:
                chain = yf_ticker.option_chain(exp)
            except Exception:
                continue
            calls, puts = chain.calls, chain.puts
            days_out = (date.fromisoformat(exp) - today).days

            calls_d = calls.copy()
            calls_d["dist"] = (calls_d["strike"] - spot).abs()
            puts_d = puts.copy()
            puts_d["dist"] = (puts_d["strike"] - spot).abs()
            atm_call = calls_d.nsmallest(1, "dist")["impliedVolatility"]
            atm_put = puts_d.nsmallest(1, "dist")["impliedVolatility"]
            atm_iv = (
                round((float(atm_call.iloc[0]) + float(atm_put.iloc[0])) / 2 * 100, 1)
                if len(atm_call) and len(atm_put)
                else None
            )
            term_structure.append({"expiry": exp, "days_to_expiry": days_out, "atm_iv_pct": atm_iv})

            if nearest is None or days_out < nearest[1]:
                nearest = (exp, days_out, calls, puts)

        if nearest is None:
            return {"ticker": ticker, "error": "No option chains available in the 2-4 week horizon."}

        exp, days_out, calls, puts = nearest

        max_pain_strike = _max_pain(calls, puts)

        call_oi = calls[["strike", "openInterest"]].dropna().sort_values("openInterest", ascending=False)
        put_oi = puts[["strike", "openInterest"]].dropna().sort_values("openInterest", ascending=False)
        resistance_walls = [
            {"strike": float(r.strike), "open_interest": int(r.openInterest)} for r in call_oi.head(3).itertuples()
        ]
        support_walls = [
            {"strike": float(r.strike), "open_interest": int(r.openInterest)} for r in put_oi.head(3).itertuples()
        ]

        # Unusual activity: volume well above existing open interest signals fresh
        # positioning being put on today, not stale resting interest.
        unusual: list[dict] = []
        for side, df in (("call", calls), ("put", puts)):
            d = df.copy()
            d["volume"] = d["volume"].fillna(0)
            d["openInterest"] = d["openInterest"].fillna(0)
            d = d[d["volume"] > 100]
            if d.empty:
                continue
            d["vol_oi_ratio"] = d["volume"] / d["openInterest"].replace(0, 1)
            for r in d.nlargest(3, "vol_oi_ratio").itertuples():
                is_otm = (side == "call" and r.strike > spot) or (side == "put" and r.strike < spot)
                unusual.append({
                    "side": side,
                    "strike": float(r.strike),
                    "volume": int(r.volume),
                    "open_interest": int(r.openInterest),
                    "vol_oi_ratio": round(float(r.vol_oi_ratio), 1),
                    "moneyness": "OTM" if is_otm else "ITM",
                })
        unusual.sort(key=lambda x: x["vol_oi_ratio"], reverse=True)
        unusual = unusual[:5]

        # Net directional lean: OTM call OI (bullish bets) vs. OTM put OI (bearish
        # bets / hedges) for the nearest expiry in the horizon.
        otm_call_oi = int(calls[calls["strike"] > spot]["openInterest"].fillna(0).sum())
        otm_put_oi = int(puts[puts["strike"] < spot]["openInterest"].fillna(0).sum())
        total_otm = otm_call_oi + otm_put_oi
        lean_score = round((otm_call_oi - otm_put_oi) / total_otm, 2) if total_otm > 0 else None
        if lean_score is None:
            lean_label = "Unclear — insufficient OI"
        elif lean_score > 0.15:
            lean_label = "Bullish lean"
        elif lean_score < -0.15:
            lean_label = "Bearish lean"
        else:
            lean_label = "Balanced / hedged"

        iv_points = [t["atm_iv_pct"] for t in term_structure if t["atm_iv_pct"] is not None]
        if len(iv_points) >= 2:
            slope = iv_points[-1] - iv_points[0]
            if slope > 2:
                term_trend = "Rising — market pricing in a later catalyst within the horizon"
            elif slope < -2:
                term_trend = "Falling — near-term risk dominates, expected to cool"
            else:
                term_trend = "Flat across the horizon"
        else:
            term_trend = "Insufficient data"

        return {
            "ticker": ticker,
            "spot": round(spot, 2),
            "horizon_days": "12-30",
            "primary_expiry": exp,
            "primary_days_to_expiry": days_out,
            "max_pain_strike": max_pain_strike,
            "resistance_walls": resistance_walls,
            "support_walls": support_walls,
            "term_structure": term_structure,
            "term_structure_trend": term_trend,
            "unusual_activity": unusual,
            "otm_call_oi": otm_call_oi,
            "otm_put_oi": otm_put_oi,
            "positioning_lean_score": lean_score,
            "positioning_lean": lean_label,
        }
    except Exception as exc:
        return {"ticker": ticker, "error": str(exc)}


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
