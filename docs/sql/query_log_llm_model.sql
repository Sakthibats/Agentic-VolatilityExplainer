-- query_log.llm_provider / llm_model — which model answered each run. Users pick the vendor
-- per run with the query-bar model picker (AnalyzeRequest.provider); each vendor's model is server config.
--
-- ORDER MATTERS: run this in the Supabase SQL editor BEFORE deploying the backend that sends
-- the fields. Until the columns exist Supabase rejects every usage-log row, and on Cloud Run
-- the logger's local fallback file does not survive an instance restart.
--
-- Values: llm_provider 'anthropic' | 'openai'; llm_model e.g. 'gpt-6-luna'.
--         NULL = the row predates these columns.


-- ── Migration ───────────────────────────────────────────────────────────────

alter table public.query_log
  add column if not exists llm_provider text,
  add column if not exists llm_model text;

comment on column public.query_log.llm_provider is
  'LLM vendor that ran the investigation: anthropic | openai. NULL = row predates the column.';
comment on column public.query_log.llm_model is
  'Model ID that ran the investigation, e.g. gpt-6-luna. NULL = row predates the column.';

-- Make the API layer pick up the new columns immediately.
notify pgrst, 'reload schema';

-- Verify — expect two rows, data_type text.
select column_name, data_type
from information_schema.columns
where table_schema = 'public' and table_name = 'query_log'
  and column_name in ('llm_provider', 'llm_model');


-- ── Reporting (assumes Supabase's default created_at column) ─────────────────

-- Runs, completion rate, latency and clean-explanation rate per model, last 7 days.
select llm_provider, llm_model,
       count(*) as runs,
       round(100.0 * count(*) filter (where status = 'complete') / count(*), 1) as pct_complete,
       round(avg(elapsed_ms)) as avg_ms,
       round(100.0 * count(*) filter (where cardinality(quality_flags) = 0)
             / nullif(count(*) filter (where quality_flags is not null), 0), 1) as pct_clean
from public.query_log
where llm_provider is not null
  and created_at > now() - interval '7 days'
group by llm_provider, llm_model
order by runs desc;


-- ── Rollback — revert the backend FIRST, or every insert starts failing ─────────
-- alter table public.query_log drop column if exists llm_provider, drop column if exists llm_model;
