"""Record raw tool outputs as eval fixtures. Makes no LLM calls, so a capture costs nothing.

Run each weekday after the US close (.github/workflows/eval-capture.yml). It price-checks a
fixed universe and keeps:
  move       universe names whose move the code rates elevated or unusual (catalyst candidates)
  control    a few calm universe names (no-catalyst controls, for abstention)
  top_mover  the day's largest large-cap gainers and losers from the Yahoo screener
For every kept ticker it fetches EVERY data tool, not just the ones today's model would pick,
so a replay under a different prompt or model never runs into missing data.

    python -m evals.capture                      # today's selection
    python -m evals.capture --dry-run            # print the selection, write nothing
    python -m evals.capture --tickers NVDA,MU    # specific tickers, skip selection

Writes evals/fixtures/<trading day>/<TICKER>.json; an existing file is left alone.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf
from volatility_explainer.agent.orchestrator import _TOOL_DISPATCH
from volatility_explainer.config import get_settings
from volatility_explainer.tools.price import _horizon_levels

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SCHEMA_VERSION = 1

# Liquid, widely covered names: their catalysts are easy to verify when labelling.
UNIVERSE: tuple[str, ...] = (
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "NFLX",
    "JPM", "BAC", "GS", "XOM", "CVX", "UNH", "LLY", "JNJ", "PFE", "WMT",
    "COST", "HD", "NKE", "DIS", "BA", "INTC", "MU", "ORCL", "CRM", "PLTR",
)
# Per-bucket caps, so a wild day can't crowd out the other buckets or bloat the repo.
CONTROLS_PER_DAY = 2
MOVES_PER_DAY = 6
MOVERS_PER_SIDE = 3
MOVER_MIN_MARKET_CAP = 10e9  # smaller names rarely have a catalyst you can verify

# Finnhub's free tier allows ~60 calls a minute and a ticker's tools make ~5 of them; past
# that, tools quietly fall back to yfinance and the fixture no longer matches production.
COOLDOWN_AFTER_SELECTION_S = 60  # the universe price check spends ~30 calls
PAUSE_BETWEEN_TICKERS_S = 6

_SEVERITY = {"unusual": 2, "elevated": 1}


def last_trading_day() -> date:
    """Date of SPY's latest daily bar: today on a trading day, earlier on a holiday."""
    return yf.Ticker("SPY").history(period="5d").index[-1].date()


def select(
    prices: dict[str, dict], gainers: list[dict], losers: list[dict], day: date
) -> dict[str, str]:
    """Pick today's tickers as {ticker: reason}. Pure, so it is tested directly.

    A move is judged on TODAY's change only: move_assessment's "overall" is the worst
    horizon, so a quiet day after a big month would pass as a catalyst candidate. A
    control must be calm on every horizon, or a recent shock could leak into it.
    """
    usable = [t for t in prices if not prices[t].get("error")]
    today = {t: _today_level(prices[t]) for t in usable}
    moves = sorted((t for t in usable if today[t] in _SEVERITY),
                   key=lambda t: (-_SEVERITY[today[t]], t))[:MOVES_PER_DAY]
    calm = sorted(t for t in usable
                  if (prices[t].get("move_assessment") or {}).get("overall") == "typical")
    controls = random.Random(day.isoformat()).sample(calm, min(CONTROLS_PER_DAY, len(calm)))

    picked: dict[str, str] = dict.fromkeys(controls, "control")
    picked.update(dict.fromkeys(moves, "move"))
    for side in (gainers, losers):
        big = [q for q in side if (q.get("marketCap") or 0) >= MOVER_MIN_MARKET_CAP]
        big.sort(key=lambda q: -abs(q.get("regularMarketChangePercent") or 0))
        fresh = [q["symbol"] for q in big if q.get("symbol") and q["symbol"] not in picked]
        picked.update(dict.fromkeys(fresh[:MOVERS_PER_SIDE], "top_mover"))
    return picked


def _today_level(price: dict) -> str:
    """The 1-day verdict from the same code that writes move_assessment."""
    levels = _horizon_levels(price.get("changes_pct") or {}, price.get("realized_vol_annualized_pct"))
    return levels["1d"][0] if "1d" in levels else ""


def _call(name: str, ticker: str) -> dict:
    try:
        return _TOOL_DISPATCH[name]({"ticker": ticker})
    except Exception as exc:  # recorded as-is: a replay should see the same failure
        return {"error": str(exc)}


def fetch_all_tools(ticker: str) -> dict[str, dict]:
    """Every data tool for one ticker, fetched in parallel, raw (no run context applied)."""
    with ThreadPoolExecutor(max_workers=len(_TOOL_DISPATCH)) as pool:
        futures = {name: pool.submit(_call, name, ticker) for name in _TOOL_DISPATCH}
    return {name: f.result() for name, f in futures.items()}


def build_fixture(ticker: str, day: date, reason: str, tools: dict[str, dict]) -> dict:
    settings = get_settings()
    price = tools.get("get_price_data") or {}
    return {
        "schema": SCHEMA_VERSION,
        "ticker": ticker,
        "trading_day": day.isoformat(),
        "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "selected_as": reason,
        "change_pct": price.get("change_pct"),
        "move_assessment": price.get("move_assessment"),
        # Without a key that tool falls back to yfinance. Where a tool reports the source
        # it actually used (e.g. get_macro's "source"), that is in its own output.
        "keys_configured": {
            "finnhub": bool(settings.finnhub_api_key.get_secret_value()),
            "fred": bool(settings.fred_api_key.get_secret_value()),
        },
        "tools": tools,
    }


def fixture_path(ticker: str, day: date, root: Path = FIXTURE_DIR) -> Path:
    return root / day.isoformat() / f"{ticker}.json"


def write_fixture(fixture: dict, root: Path = FIXTURE_DIR) -> Path:
    path = fixture_path(fixture["ticker"], date.fromisoformat(fixture["trading_day"]), root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fixture, indent=1, default=str) + "\n", encoding="utf-8")
    return path


def _screen(name: str) -> list[dict]:
    try:
        return yf.screen(name, count=25).get("quotes", [])
    except Exception as exc:
        print(f"[capture] screener {name} failed: {exc}")
        return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tickers", help="comma-separated tickers; skips selection")
    parser.add_argument("--dry-run", action="store_true", help="print the selection only")
    args = parser.parse_args()

    day = last_trading_day()
    today = datetime.now(ZoneInfo("America/New_York")).date()
    if day != today and not args.tickers:
        print(f"[capture] market closed today ({today}); last session was {day}. Nothing to do.")
        return 0

    if args.tickers:
        selection = {t.strip().upper(): "manual" for t in args.tickers.split(",") if t.strip()}
    else:
        with ThreadPoolExecutor(max_workers=4) as pool:
            prices = dict(zip(UNIVERSE, pool.map(lambda t: _call("get_price_data", t), UNIVERSE),
                              strict=True))
        selection = select(prices, _screen("day_gainers"), _screen("day_losers"), day)

    print(f"[capture] {day}: {len(selection)} tickers")
    for ticker, reason in selection.items():
        print(f"  {ticker:<6} {reason}")
    if args.dry_run:
        return 0

    todo = {t: r for t, r in selection.items() if not fixture_path(t, day).exists()}
    if todo and not args.tickers:
        time.sleep(COOLDOWN_AFTER_SELECTION_S)
    for i, (ticker, reason) in enumerate(todo.items()):
        if i:
            time.sleep(PAUSE_BETWEEN_TICKERS_S)
        path = write_fixture(build_fixture(ticker, day, reason, fetch_all_tools(ticker)))
        print(f"[capture] wrote {path.relative_to(FIXTURE_DIR.parent)}")
    print(f"[capture] {len(todo)} new, {len(selection) - len(todo)} already recorded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
