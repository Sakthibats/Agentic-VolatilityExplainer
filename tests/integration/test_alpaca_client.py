import httpx
import respx

from volatility_explainer.clients.alpaca import ALPACA_DATA_URL, AlpacaClient
from volatility_explainer.config import Settings


@respx.mock
def test_get_latest_trade() -> None:
    route = respx.get(f"{ALPACA_DATA_URL}/v2/stocks/AAPL/trades/latest").mock(
        return_value=httpx.Response(200, json={"symbol": "AAPL", "trade": {"p": 190.5}})
    )

    settings = Settings(
        alpaca_api_key="test-key",
        alpaca_api_secret="test-secret",
    )
    client = AlpacaClient(settings)

    result = client.get_latest_trade("AAPL")

    assert route.called
    assert result["symbol"] == "AAPL"
