"""Eval cases: a recorded fixture plus the question a user asks about it.

Sampled across the capture buckets so every model sees the same mix of real catalysts
(`move`, `top_mover`) and calm days where the right answer is "nothing unusual" (`control`).
Deterministic for a given seed, so two runs compare like with like.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

from volatility_explainer.tools.price import _horizon_levels

from evals.capture import FIXTURE_DIR
from evals.replay import normalize_price

# Share of cases per bucket. Controls are fewer per day in the fixtures, and a third of the
# set is enough to measure whether a model invents causes for a quiet stock.
_MIX = {"move": 0.4, "top_mover": 0.35, "control": 0.25}


@dataclass(frozen=True)
class Case:
    id: str              # "<day>/<TICKER>"
    day: str
    ticker: str
    bucket: str          # move | top_mover | control
    query: str
    change_pct: float | None
    path: str

    def fixture(self) -> dict:
        return json.loads(Path(self.path).read_text(encoding="utf-8"))


def _query(ticker: str, bucket: str, change_pct: float | None, i: int) -> str:
    """Alternate the two ways people ask: naming only the stock, or asking about the move.

    Naming only the stock reaches the loop as an empty question (api/service.py passes
    `decision.question`, which is "" for "TSLA" or "why did tesla move"), so it is "" here too.
    """
    if i % 2 == 0:
        return ""
    if bucket == "control" or change_pct is None:
        return f"why did {ticker} move today?"
    return f"why is {ticker} {'down' if change_pct < 0 else 'up'} today?"


def today_level(fixture: dict) -> str | None:
    """The 1-day significance level after replay's correction ("typical" | "elevated" |
    "unusual"), or None when the price data can't support a verdict."""
    price = normalize_price(fixture["tools"]["get_price_data"])
    one_day = _horizon_levels(price.get("changes_pct") or {},
                              price.get("realized_vol_annualized_pct")).get("1d")
    return one_day[0] if one_day else None


def bucket_holds(fixture: dict) -> bool:
    """Does the capture bucket still describe the day once "today" is corrected?

    Capture picks `move` and `control` from yfinance's daily history, which lags the close by
    a day (evals/README.md), so some `move` fixtures are calm on the day they're replayed for
    and some controls actually moved. Those are left out rather than relabelled: a stale move
    is neither a catalyst case nor a clean control. `top_mover` comes from the live screener,
    so it is never stale; nor is a hand-picked `manual` capture. A fixture with no verdict is
    kept. On the first 3 weeks of fixtures this drops 35 of 76 moves and 8 of 30 controls.
    """
    bucket = fixture["selected_as"]
    if bucket not in ("move", "control"):
        return True
    level = today_level(fixture)
    if level is None:
        return True
    return level != "typical" if bucket == "move" else level == "typical"


def load_fixtures(root: Path = FIXTURE_DIR) -> list[dict]:
    fixtures = []
    for path in sorted(root.glob("*/*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if "error" in (data.get("tools", {}).get("get_price_data") or {"error": "missing"}):
            continue  # no price, no investigation worth scoring
        if not bucket_holds(data):
            continue
        data["_path"] = str(path)
        fixtures.append(data)
    return fixtures


def build_cases(n: int, seed: int = 7, root: Path = FIXTURE_DIR) -> list[Case]:
    rng = random.Random(seed)
    by_bucket: dict[str, list[dict]] = {}
    for fixture in load_fixtures(root):
        by_bucket.setdefault(fixture["selected_as"], []).append(fixture)

    chosen: list[dict] = []
    for bucket, share in _MIX.items():
        pool = by_bucket.get(bucket, [])
        chosen += rng.sample(pool, min(len(pool), round(n * share)))
    chosen.sort(key=lambda f: (f["trading_day"], f["ticker"]))

    return [
        Case(
            id=f"{f['trading_day']}/{f['ticker']}",
            day=f["trading_day"],
            ticker=f["ticker"],
            bucket=f["selected_as"],
            query=_query(f["ticker"], f["selected_as"], f.get("change_pct"), i),
            change_pct=f.get("change_pct"),
            path=f["_path"],
        )
        for i, f in enumerate(chosen)
    ]
