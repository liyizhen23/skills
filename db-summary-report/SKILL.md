---
name: db-summary-report
description: Generate a trend-focused report from the Supabase Postgres journals table using DAYS/TOPIC filtering. Use when the user wants a digest that summarizes shared themes and trends across recent papers (not per-paper summaries).
---

# Db Summary Report

## Overview

Generate a trend report from recent records in the `journals` table, optionally filtered by a topic keyword. Output a structured digest with counts and a synthesis of common themes and trends across all papers (no per-paper summaries).

## Inputs

- `DAYS`: Integer, default `7`. Query articles uploaded in the last N days.
- `TOPIC`: String, default empty. Empty means no topic filtering.

## Workflow

1. Load `references/journal_db_report.md` for the canonical prompt, schema, SQL, and report template.
2. Obtain the database password securely from environment variables or local `.env` file. Never print or log it.
3. Query recent rows by `created_at >= now_utc - DAYS` (time filtering must use `created_at`).
4. If `TOPIC` is non-empty, filter by keyword matching in `title` and `abstract`; if no hits, broaden to fuzzy matching; if still none, state that and return all results.
5. Synthesize common themes, methods, and trends across all matched rows. Do not write per-paper summaries.
6. Format the weekly report in the same language as the user, following the required structure.

## Script

Use `scripts/run_report.py` to generate a report deterministically.

Prepare env file in skill root (`db-summary-report/.env`):

```dotenv
DB_PASSWORD=<PASSWORD>
OPENAI_API_KEY=<OPENAI_API_KEY>
ANTHROPIC_API_KEY=<ANTHROPIC_API_KEY>
CLAUDE_API_KEY=<CLAUDE_API_KEY>
LLM_API_KEY=<LLM_API_KEY>
LLM_PROVIDER=openai
LLM_BASE_URL=
LLM_MODEL=
OPENAI_MODEL=gpt-4.1
OPENAI_BASE_URL=
ANTHROPIC_MODEL=claude-3-5-sonnet-latest
ANTHROPIC_BASE_URL=
```

Example:

```powershell
cd db-summary-report
python scripts/run_report.py --days 1 --topics "AI, machine learning" --output report_last_1d.md
python scripts/run_report.py --days 1 --output report_last_1d.md
python scripts/run_report.py --days 1 --topics "AI" --llm --output report_last_1d.md
python scripts/run_report.py --provider anthropic --days 1 --topics "AI" --output report_last_1d.md
python scripts/run_report.py --provider openai --model claude-3-5-sonnet --days 1 --topics "AI" --output report_last_1d.md
```

LLM mode requires:

- OpenAI mode: `OPENAI_API_KEY` + `openai` SDK
- Claude mode: `ANTHROPIC_API_KEY` + `anthropic` SDK
- For OpenAI-compatible gateways, set `OPENAI_BASE_URL` (or `LLM_BASE_URL`) and provider `openai`.

## Output Rules

- Do not output any database password or raw `abstract` content verbatim.
- If no rows are found, notify the user and suggest increasing `DAYS`.
- If the article count exceeds 30, keep the overview longer and more structured (for example, grouped trends by subfields).
- Keep summaries in the user's language (Chinese vs English).
- Ensure report files are written as UTF-8 to avoid `?` garbling on Windows.

## Resources

- `references/journal_db_report.md`: Detailed prompt, DB schema, SQL, filtering logic, and report format.
