from fastapi import FastAPI

from volatility_explainer.agent.orchestrator import run_explainer

app = FastAPI(title="Volatility Explainer API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/explain/{ticker}")
def explain(ticker: str) -> dict:
    return run_explainer(ticker)
