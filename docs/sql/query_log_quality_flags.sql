-- query_log.quality_flags — heuristic flags on the model's explanation (agent/quality.py).
--
-- ORDER MATTERS: run this in the Supabase SQL editor BEFORE deploying the backend that sends
-- the field. Until the column exists Supabase rejects every usage-log row, and on Cloud Run
-- the logger's local fallback file does not survive an instance restart.
--
-- Values: NULL = not checked (no explanation, or the row predates this column);
--         '{}' = checked and clean; otherwise the flags it tripped.


-- ── Migration ───────────────────────────────────────────────────────────────

alter table public.query_log
  add column if not exists quality_flags text[];

comment on column public.query_log.quality_flags is
  'Heuristic flags on the model explanation (backend agent/quality.py). NULL = not checked; {} = clean.';

-- Make the API layer pick up the new column immediately.
notify pgrst, 'reload schema';

-- Verify — expect one row, data_type ARRAY.
select column_name, data_type
from information_schema.columns
where table_schema = 'public' and table_name = 'query_log' and column_name = 'quality_flags';

-- Optional, once the table holds many thousands of rows:
-- create index if not exists query_log_quality_flags_idx on public.query_log using gin (quality_flags);


-- ── Reporting (these assume Supabase's default created_at column) ─────────────
-- Cached no-question answers carry their original flags, so a popular ticker's cache hits
-- are counted again. Fine for trends, slightly over-counts.

-- How often each flag fires, last 7 days.
with checked as (
  select quality_flags from public.query_log
  where quality_flags is not null
    and created_at > now() - interval '7 days'
)
select flag,
       count(*) as runs,
       round(100.0 * count(*) / (select count(*) from checked), 1) as pct_of_checked
from checked, unnest(quality_flags) as flag
group by flag
order by runs desc;

-- Share of explanations that were clean.
select count(*) filter (where cardinality(quality_flags) = 0) as clean,
       count(*) as checked,
       round(100.0 * count(*) filter (where cardinality(quality_flags) = 0)
             / nullif(count(*), 0), 1) as pct_clean
from public.query_log
where quality_flags is not null;

-- Recent runs with a given flag. The explanation text itself is not stored — to read the
-- offending write-ups, capture runs locally with VOLX_SAVE_RUNS and use
-- scripts/quality_report.py --show <flag>.
select created_at, ticker, query, quality_flags
from public.query_log
where quality_flags @> array['consensus_as_cause']
order by created_at desc
limit 20;


-- ── Rollback — revert the backend FIRST, or every insert starts failing ─────────
-- alter table public.query_log drop column if exists quality_flags;
