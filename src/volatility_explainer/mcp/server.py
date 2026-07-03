"""MCP server entry point — registers and exposes all tools."""

from mcp.server.fastmcp import FastMCP

from volatility_explainer.mcp.tools import analyst, events, macro, news, options, price, sector

mcp = FastMCP("volatility-explainer")


@mcp.tool()
def get_price_data(ticker: str) -> dict:
    """Fetch price and volatility data for a ticker."""
    return price.fetch_price_data(ticker)


@mcp.tool()
def get_events(ticker: str) -> dict:
    """Fetch upcoming and recent market events (earnings, FOMC, etc.)."""
    return events.fetch_events(ticker)


@mcp.tool()
def get_news(ticker: str) -> dict:
    """Fetch recent news headlines and sentiment for a ticker."""
    return news.fetch_news(ticker)


@mcp.tool()
def get_macro() -> dict:
    """Fetch macro indicators (rates, CPI, VIX, etc.)."""
    return macro.fetch_macro()


@mcp.tool()
def get_options_data(ticker: str) -> dict:
    """Fetch options chain data (IV, skew, put/call ratio)."""
    return options.fetch_options_data(ticker)


@mcp.tool()
def get_options_positioning(ticker: str) -> dict:
    """Deeper options positioning: max pain, OI walls, IV term structure, unusual activity."""
    return options.fetch_options_positioning(ticker)


@mcp.tool()
def get_analyst_sentiment(ticker: str) -> dict:
    """Fetch Wall Street analyst consensus rating and price targets for a ticker."""
    return analyst.fetch_analyst_sentiment(ticker)


@mcp.tool()
def get_sector_comparison(ticker: str) -> dict:
    """Compare a stock's move against its sector ETF's move over the same horizons."""
    return sector.fetch_sector_comparison(ticker)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
