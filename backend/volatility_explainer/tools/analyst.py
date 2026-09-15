"""Wall Street analyst view — consensus, price targets, and recent rating actions.

Three independent yfinance surfaces, fetched in parallel so the tool costs max(), not sum():

- upgrades_downgrades — DATED analyst actions. The reason this tool is worth calling for a
  "why did it move" question at all: a downgrade with a price-target cut three days ago is
  a catalyst, where a static consensus rating never is.
- recommendations — the buy/hold/sell distribution over the last four months, so a rating
  that is quietly deteriorating inside a still-"buy" headline is visible.
- analyst_price_targets — mean, MEDIAN, high, low. The median matters because a single
  outlier target drags the mean; when the two disagree the Street is split.

Every verdict here (upgrade vs downgrade, bullish vs bearish, improving vs deteriorating,
how dispersed the targets are) is computed in code before the model sees it — the model is
never handed two floats and asked to decide which way they lean.

Each surface is wrapped separately: one failing degrades that section alone. Tickers with
no coverage (ETFs, funds) report analyst_coverage "none", which is a real answer, distinct
from "unavailable" when the lookup itself failed.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date

_logger = logging.getLogger(__name__)

# How far back a rating action still counts as "recent" enough to have moved the price,
# and how many to report. Older actions are consensus, not catalyst.
_ACTION_LOOKBACK_DAYS = 30
_MAX_ACTIONS = 5

# Weights for the 1.0 (strong buy) - 5.0 (strong sell) consensus score, matching the scale
# Yahoo's own recommendationMean uses.
_RATING_WEIGHTS = {"strongBuy": 1, "buy": 2, "hold": 3, "sell": 4, "strongSell": 5}

# Score band -> (canonical rating key, plain-English verdict). The verdict is written here
# so the write-up never has to translate a bare number like 2.13 into words itself.
_SCORE_BANDS = [
    (1.5, "strong_buy", "strongly bullish"),
    (2.5, "buy", "leaning bullish"),
    (3.5, "hold", "neutral"),
    (4.5, "sell", "leaning bearish"),
    (float("inf"), "strong_sell", "strongly bearish"),
]

# A consensus score moving by less than this over the window is noise, not a trend.
_TREND_EPSILON = 0.05

_ACTION_LABELS = {
    "up": "upgrade",
    "down": "downgrade",
    "init": "initiated coverage",
    "main": "maintained",
    "reit": "reiterated",
}


def _today() -> date:
    """Indirection so tests can freeze the clock without mocking the date class itself."""
    return date.today()


def _clean(value) -> float | None:
    """yfinance hands back NaN and a literal 0.0 for 'no price target' — both mean absent."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number == 0.0:  # NaN or the 0.0 placeholder
        return None
    return round(number, 2)


def _score(counts: dict) -> float | None:
    """Weighted consensus on Yahoo's 1-5 scale. None when nobody covers the name."""
    total = sum(counts.get(key, 0) for key in _RATING_WEIGHTS)
    if not total:
        return None
    weighted = sum(_RATING_WEIGHTS[key] * counts.get(key, 0) for key in _RATING_WEIGHTS)
    return round(weighted / total, 2)


def _verdict(score: float) -> tuple[str, str]:
    for threshold, rating, phrase in _SCORE_BANDS:
        if score <= threshold:
            return rating, phrase
    return "hold", "neutral"  # unreachable; the last band is unbounded


def _period_counts(recommendations) -> dict[str, dict]:
    """Map period label ('0m', '-1m', ...) to its rating counts. Keyed by the label rather
    than row position — Yahoo has been known to reorder these."""
    if recommendations is None or getattr(recommendations, "empty", True):
        return {}
    if "period" not in getattr(recommendations, "columns", []):
        return {}
    out: dict[str, dict] = {}
    for row in recommendations.to_dict("records"):
        period = row.get("period")
        if period:
            out[str(period)] = {key: int(row.get(key) or 0) for key in _RATING_WEIGHTS}
    return out


def _consensus(recommendations) -> dict | None:
    """Current consensus plus which way it has drifted over the available months."""
    periods = _period_counts(recommendations)
    current = periods.get("0m")
    score = _score(current) if current else None
    if score is None:
        return None

    rating, phrase = _verdict(score)
    analysts = sum(current.get(key, 0) for key in _RATING_WEIGHTS)
    consensus = {
        "rating": rating,
        "score": score,
        "verdict": phrase,
        "analysts": analysts,
        "counts": current,
    }

    # Compare against the oldest month we actually have, so the trend still works when
    # Yahoo returns fewer than four periods.
    older = [(int(p.rstrip("m")), c) for p, c in periods.items() if p.startswith("-")]
    if not older:
        return consensus
    months_back, oldest = min(older, key=lambda pair: pair[0])
    old_score = _score(oldest)
    if old_score is None:
        return consensus

    span = abs(months_back)
    delta = round(score - old_score, 2)
    bearish_now = current.get("sell", 0) + current.get("strongSell", 0)
    bearish_then = oldest.get("sell", 0) + oldest.get("strongSell", 0)

    if delta > _TREND_EPSILON:
        # A HIGHER score is worse on Yahoo's scale (5 = strong sell).
        trend = "deteriorating"
        detail = (
            f"consensus softened over {span} months (score {old_score} to {score}; "
            f"bearish ratings {bearish_then} to {bearish_now})"
        )
    elif delta < -_TREND_EPSILON:
        trend = "improving"
        detail = (
            f"consensus firmed up over {span} months (score {old_score} to {score}; "
            f"bearish ratings {bearish_then} to {bearish_now})"
        )
    else:
        trend = "stable"
        detail = f"consensus essentially unchanged over {span} months (score {old_score} to {score})"

    consensus["trend"] = trend
    consensus["trend_detail"] = detail
    return consensus


def _price_target(targets: dict) -> dict | None:
    """Targets plus the two things the raw payload does not say out loud: how far apart the
    Street is, and the upside measured against the outlier-resistant median."""
    if not targets:
        return None
    mean = _clean(targets.get("mean"))
    median = _clean(targets.get("median"))
    high = _clean(targets.get("high"))
    low = _clean(targets.get("low"))
    current = _clean(targets.get("current"))
    if mean is None and median is None:
        return None

    out = {
        "mean": mean,
        "median": median,
        "high": high,
        "low": low,
        "current_price": current,
    }
    if high is not None and low is not None and mean:
        # How wide the range of opinion is, as a share of the mean target. A big number
        # means the Street genuinely disagrees, which is itself the finding.
        out["dispersion_pct"] = round((high - low) / mean * 100, 1)
    if current:
        if mean is not None:
            out["upside_vs_mean_pct"] = round((mean - current) / current * 100, 1)
        if median is not None:
            out["upside_vs_median_pct"] = round((median - current) / current * 100, 1)
    return out


def apply_reference_price(result: dict, price: float | None) -> dict:
    """Re-anchor the upside percentages to an externally supplied current price.

    The orchestrator calls this with get_price_data's price so a single run never quotes
    two different prices for the same stock — yfinance's `current` and Finnhub's quote can
    diverge intraday, and the write-up quotes the latter.

    It is applied to CACHE HITS as well as fresh fetches, which is the point: analyst data
    is cached for 12 hours but price for 15 minutes, so an upside baked in at fetch time
    goes stale long before the entry expires. Returns the result untouched when there is no
    price or nothing to re-anchor.
    """
    price = _clean(price)
    target = result.get("price_target")
    if not price or not target:
        return result

    target["current_price"] = price
    for key, field in (("mean", "upside_vs_mean_pct"), ("median", "upside_vs_median_pct")):
        value = target.get(key)
        if value is None:
            target.pop(field, None)
        else:
            target[field] = round((value - price) / price * 100, 1)
    return result


def _describe_action(ticker: str, entry: dict) -> str:
    firm = entry["firm"]
    label = entry["action"]
    from_grade, to_grade = entry.get("from_grade"), entry.get("to_grade")
    pt_from, pt_to = entry.get("price_target_from"), entry.get("price_target_to")

    if label in {"upgrade", "downgrade"} and from_grade and to_grade:
        sentence = f"{firm} {label}d {ticker} from {from_grade} to {to_grade}"
    elif label == "initiated coverage" and to_grade:
        sentence = f"{firm} initiated coverage of {ticker} at {to_grade}"
    elif to_grade:
        sentence = f"{firm} {label} its {to_grade} rating on {ticker}"
    else:
        sentence = f"{firm} {label} its rating on {ticker}"

    if pt_to is not None and pt_from is not None and pt_to != pt_from:
        direction = "raised" if pt_to > pt_from else "cut"
        sentence += f" and {direction} its price target from ${pt_from} to ${pt_to}"
    elif pt_to is not None:
        sentence += f" with a ${pt_to} price target"
    return sentence


def _recent_actions(ticker: str, upgrades, today: date) -> list[dict]:
    """Dated rating actions inside the lookback window, most recent first."""
    if upgrades is None or getattr(upgrades, "empty", True):
        return []
    if "Firm" not in getattr(upgrades, "columns", []):
        return []

    actions: list[dict] = []
    for timestamp, row in upgrades.iterrows():
        try:
            when = timestamp.date()
        except AttributeError:
            continue
        days_ago = (today - when).days
        if days_ago < 0 or days_ago > _ACTION_LOOKBACK_DAYS:
            continue

        raw_action = str(row.get("Action") or "").lower()
        entry = {
            "date": when.isoformat(),
            "days_ago": days_ago,
            "firm": str(row.get("Firm") or "").strip() or "An analyst",
            "action": _ACTION_LABELS.get(raw_action, "updated"),
            "from_grade": str(row.get("FromGrade") or "").strip() or None,
            "to_grade": str(row.get("ToGrade") or "").strip() or None,
            "price_target_from": _clean(row.get("priorPriceTarget")),
            "price_target_to": _clean(row.get("currentPriceTarget")),
        }
        entry["is_rating_change"] = entry["action"] in {"upgrade", "downgrade"}
        entry["description"] = _describe_action(ticker, entry)
        actions.append(entry)

    actions.sort(key=lambda a: a["days_ago"])
    return actions[:_MAX_ACTIONS]


def _fetch_price_targets(yf_ticker) -> dict:
    return yf_ticker.analyst_price_targets


def _fetch_recommendations(yf_ticker):
    return yf_ticker.recommendations


def _fetch_upgrades(yf_ticker):
    return yf_ticker.upgrades_downgrades


def fetch_analyst_sentiment(ticker: str) -> dict:
    """Fetch Wall Street consensus, price targets, and recent rating actions.

    Three parallel yfinance calls instead of the single Ticker.info snapshot this used to
    make: same wall time (Yahoo's per-request latency dominates and the fetches overlap),
    a fraction of the payload, and it adds the time dimension — what analysts did recently,
    not just where they stand today.
    """
    ticker = ticker.upper()
    today = _today()

    try:
        import yfinance as yf

        yf_ticker = yf.Ticker(ticker)
    except Exception as exc:
        _logger.warning("[analyst:%s] yfinance unavailable", ticker, exc_info=True)
        return {"ticker": ticker, "analyst_coverage": "unavailable", "error": str(exc)}

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            "targets": pool.submit(_fetch_price_targets, yf_ticker),
            "recommendations": pool.submit(_fetch_recommendations, yf_ticker),
            "upgrades": pool.submit(_fetch_upgrades, yf_ticker),
        }
        raw: dict = {}
        failures = 0
        for name, future in futures.items():
            try:
                raw[name] = future.result()
            except Exception:
                _logger.warning("[analyst:%s] %s lookup failed", ticker, name, exc_info=True)
                raw[name] = None
                failures += 1

    consensus = _consensus(raw.get("recommendations"))
    price_target = _price_target(raw.get("targets") or {})
    recent_actions = _recent_actions(ticker, raw.get("upgrades"), today)

    if consensus is None and price_target is None and not recent_actions:
        # Nothing came back at all. Recent actions count as coverage on their own: a firm
        # downgrading the stock last week is evidence even if the consensus and target
        # lookups came back empty.
        # Distinguish "this ticker has no analysts" (every call succeeded and returned
        # empty — normal for an ETF) from "we could not find out".
        coverage = "unavailable" if failures == len(futures) else "none"
        result = {"ticker": ticker, "as_of": today.isoformat(), "analyst_coverage": coverage}
        result["notes"] = [
            f"Analyst data could not be retrieved for {ticker}."
            if coverage == "unavailable"
            else f"No analyst coverage for {ticker} — expected for an ETF or fund, not a data failure."
        ]
        return result

    result: dict = {
        "ticker": ticker,
        "as_of": today.isoformat(),
        "analyst_coverage": "covered",
        "recent_actions": recent_actions,
    }
    if consensus is not None:
        result["consensus"] = consensus
    if price_target is not None:
        result["price_target"] = price_target
    if not recent_actions:
        result["notes"] = [
            f"No analyst rating changes in the last {_ACTION_LOOKBACK_DAYS} days — "
            "the consensus below is standing opinion, not a recent catalyst."
        ]
    return result
