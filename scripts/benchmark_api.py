"""Benchmark /v1/analyze: sequential latency + concurrent wall time.

Usage: python scripts/benchmark_api.py http://localhost:8098
Uses distinct tickers per run so in-process/Redis caches don't flatter the numbers.
"""

from __future__ import annotations

import asyncio
import sys
import time

import httpx

SEQUENTIAL_TICKERS = ["AAPL", "MSFT", "NVDA"]
CONCURRENT_TICKERS = ["TSLA", "AMZN", "GOOG", "META"]


async def one_run(client: httpx.AsyncClient, base: str, ticker: str) -> float:
    t0 = time.perf_counter()
    r = await client.post(
        f"{base}/v1/analyze?stream=false",
        json={"query": f"why did {ticker} move today"},
        timeout=180.0,
    )
    r.raise_for_status()
    status = r.json()["status"]
    elapsed = time.perf_counter() - t0
    print(f"  {ticker:<6} {elapsed:6.1f}s  ({status})")
    return elapsed


async def main(base: str) -> None:
    async with httpx.AsyncClient() as client:
        print(f"[sequential] {len(SEQUENTIAL_TICKERS)} runs, one at a time")
        seq_times = [await one_run(client, base, t) for t in SEQUENTIAL_TICKERS]

        print(f"[concurrent] {len(CONCURRENT_TICKERS)} runs, all at once")
        t0 = time.perf_counter()
        conc_times = await asyncio.gather(
            *(one_run(client, base, t) for t in CONCURRENT_TICKERS)
        )
        conc_wall = time.perf_counter() - t0

        print("\n== summary ==")
        print(f"sequential mean per-run : {sum(seq_times) / len(seq_times):6.1f}s")
        print(f"concurrent mean per-run : {sum(conc_times) / len(conc_times):6.1f}s")
        print(f"concurrent wall (n={len(CONCURRENT_TICKERS)})   : {conc_wall:6.1f}s")
        print(f"concurrency speedup     : {sum(conc_times) / conc_wall:6.2f}x vs serial execution")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1].rstrip("/")))
