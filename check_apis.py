"""Quick diagnostic — run from the project root to test all API keys."""

import sys
from pathlib import Path

# Make src/ importable
sys.path.insert(0, str(Path(__file__).parent / "src"))

from volatility_explainer.config import get_settings

settings = get_settings()

TICKER = "AAPL"
OK = "  ✓"
FAIL = "  ✗"
SKIP = "  -"


def check(label: str, fn) -> bool:
    try:
        result = fn()
        print(f"{OK}  {label}: {result}")
        return True
    except Exception as exc:
        print(f"{FAIL}  {label}: {exc}")
        return False


print("\n── API Key Diagnostics ──────────────────────────────")

# ── 1. Config / .env loading ──────────────────────────────────────────────────
print("\n[1] Config (.env loading)")
keys = {
    "ANTHROPIC_API_KEY": settings.anthropic_api_key.get_secret_value(),
    "ALPACA_API_KEY":    settings.alpaca_api_key.get_secret_value(),
    "ALPACA_API_SECRET": settings.alpaca_api_secret.get_secret_value(),
    "FINNHUB_API_KEY":   settings.finnhub_api_key.get_secret_value(),
    "FRED_API_KEY":      settings.fred_api_key.get_secret_value(),
}
all_present = True
for name, val in keys.items():
    if val:
        masked = val[:6] + "..." + val[-3:] if len(val) > 10 else "***"
        print(f"{OK}  {name} loaded ({masked})")
    else:
        print(f"{FAIL}  {name} missing or empty")
        all_present = False

if not all_present:
    print("\n  → Check your .env file at the project root.")
    print("    Keys present in .env? Run:  grep -v '^#' .env | grep '='")

# ── 2. Anthropic ──────────────────────────────────────────────────────────────
print("\n[2] Anthropic (Claude)")
def test_anthropic():
    import anthropic
    api_key = settings.anthropic_api_key.get_secret_value() or None
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=10,
        messages=[{"role": "user", "content": "Say OK"}],
    )
    return msg.content[0].text.strip()
check("Claude API", test_anthropic)

# ── 3. Alpaca ─────────────────────────────────────────────────────────────────
print("\n[3] Alpaca (price data)")
def test_alpaca_trade():
    from volatility_explainer.clients.alpaca import AlpacaClient
    data = AlpacaClient(settings).get_latest_trade(TICKER)
    trade = data.get("trade", {})
    return f"last trade price = {trade.get('p', '?')}"
def test_alpaca_bars():
    from volatility_explainer.clients.alpaca import AlpacaClient
    data = AlpacaClient(settings).get_bars(TICKER, limit=2)
    bars = data.get("bars", [])
    return f"{len(bars)} bar(s) returned"
check("Latest trade", test_alpaca_trade)
check("Price bars",   test_alpaca_bars)

# ── 4. Finnhub ────────────────────────────────────────────────────────────────
print("\n[4] Finnhub (news)")
def test_finnhub():
    from datetime import date, timedelta
    from volatility_explainer.clients.finnhub import FinnhubClient
    today = date.today().isoformat()
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    news = FinnhubClient(settings).get_company_news(TICKER, from_date=week_ago, to_date=today)
    return f"{len(news)} headline(s) in last 7 days"
check("Company news", test_finnhub)

# ── 5. FRED ───────────────────────────────────────────────────────────────────
print("\n[5] FRED (macro / VIX)")
def test_fred():
    from volatility_explainer.clients.fred import FredClient
    data = FredClient(settings).get_series_observations("VIXCLS", limit=1)
    obs = data.get("observations", [{}])
    return f"VIX latest = {obs[0].get('value', '?')} on {obs[0].get('date', '?')}"
check("VIX series", test_fred)

# ── 6. yfinance (no key needed) ───────────────────────────────────────────────
print("\n[6] yfinance (options / events / quick stats — no key needed)")
def test_yf_info():
    import yfinance as yf
    info = yf.Ticker(TICKER).fast_info
    return f"last price = {info.last_price:.2f}"
def test_yf_options():
    import yfinance as yf
    exps = yf.Ticker(TICKER).options
    return f"{len(exps)} expiration date(s) available"
def test_yf_history():
    import yfinance as yf
    hist = yf.Ticker(TICKER).history(period="5d")
    return f"{len(hist)} trading day(s) returned"
check("Quote / fast_info",  test_yf_info)
check("Options chain",      test_yf_options)
check("Price history",      test_yf_history)

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n─────────────────────────────────────────────────────")
print("Done. Fix any ✗ rows above before running the app.\n")
