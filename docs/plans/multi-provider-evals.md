# Plan: one agent loop, two vendors, one eval

Branch `multi-provider-evals`. Not merged to `main` until it has been reviewed: backend changes on
`main` deploy to Cloud Run.

**Goal.** The same agent loop runs on Claude or OpenAI, chosen by configuration, and an eval
replays recorded market data (`evals/fixtures/`) through each model and scores the answers.

**Decisions.**
- Models compared: `claude-haiku-5-5`, `gpt-6-luna`, and `claude-haiku-4-5-20251001` (the
  production baseline).
- Production stays on Anthropic + Haiku 4.5. The provider is a setting, not a runtime fallback.
- A thin in-house adapter per vendor, not LiteLLM or LangChain: the loop relies on streaming a
  partial tool call and on explicit cache breakpoints, which generic layers flatten.
- SDKs: keep `anthropic` as installed; add `openai~=3.46`.
- Eval spend cap: $5 in total, enforced by the runner. A 5-case pilot measures cost first.
- No `OPENAI_API_KEY` in GitHub: the OpenAI live test skips without a key.

## Phase 1: provider seam (no behaviour change)

- `backend/volatility_explainer/llm/`: `base.py` (neutral types + `LLMProvider`), 
  `anthropic_provider.py` (today's code, moved), `pricing.py` (`cost_usd`), `__init__.py`
  (`get_provider`).
- `agent/orchestrator.py` calls the provider; usage gains `provider` and `cost_usd`.
- `agent/tool_schemas.py` loses the Anthropic-only keys; the adapter adds them back.
- `query/parsing.py` resolves tickers through `provider.complete()`.
- `config.py`: `llm_provider`, `llm_model`, `openai_api_key`; `ANTHROPIC_MODEL` keeps working.

Done when: the existing suite passes with only the fake client's patch target changed.

## Phase 2: OpenAI adapter

- `llm/openai_provider.py` on the Responses API: function tools, `tool_choice="required"`,
  `function_call` / `function_call_output` items, streamed arguments, reasoning items carried
  between turns, usage including reasoning tokens.
- Tests with a scripted fake OpenAI stream; the loop's behaviour tests run on both fakes; a live
  test per vendor that skips without a key.

Done when: one real investigation completes on GPT-6 Luna.

## Phase 3: eval runner and automatic scorers

- `evals/cases.py` (stratified cases from fixtures), `evals/replay.py` (fixtures served through
  the real loop, caches off, network forbidden), `evals/run.py` (models, repeats, concurrency,
  resume, spend cap), `evals/scorers.py`, `evals/report.py` → `evals/results/REPORT.md`.
- Scorers: completion, schema validity, numbers vs. tool data, internal agreement, quality
  flags, tool choice, cost, latency, run-to-run stability.

Done when: a full comparison table exists.

## Phase 5 (README level)

README "Model evaluation" section (table, method, caveats), AGENTS.md decision and repo map,
env docs. Phase 4 (labelled catalyst recall, cross-vendor judge, calibration) is listed as next
steps only.

## If time runs short, cut in this order

Stability (1 repeat) → number matching → fewer cases (20) → live test. The seam, the OpenAI
adapter, completion/cost/quality scores and the README table must ship.
