---
name: journal-db-summary-report
description: Generate a weekly trend-focused report from the Supabase Postgres journals table using DAYS/TOPIC filtering. Use when the user wants a weekly digest that summarizes shared themes and trends across recent papers (not per-paper summaries).
---

# Journal Db Summary Report

## Overview

Generate a weekly trend report from recent records in the `journals` table, optionally filtered by a topic keyword. Output a structured digest with counts and a synthesis of common themes and trends across all papers (no per-paper summaries).

## Inputs

- `DAYS`: Integer, default `7`. Query articles uploaded in the last N days.
- `TOPIC`: String, default empty. Empty means no topic filtering.

## Workflow

1. Load `references/journal_db_report.md` for the canonical prompt, schema, SQL, and report template.
2. Obtain the database password securely (environment variable or user input). Never print or log it.
3. Query recent rows by `createdtime >= now_utc - DAYS` (time filtering must use `createdtime`).
4. If `TOPIC` is non-empty, filter by keyword matching in `title` and `abstract`; if no hits, broaden to fuzzy matching; if still none, state that and return all results.
5. Synthesize common themes, methods, and trends across all matched rows. Do not write per-paper summaries.
6. Format the weekly report in the same language as the user, following the required structure.

## Output Rules

- Do not output any database password or raw `abstract` content verbatim.
- If no rows are found, notify the user and suggest increasing `DAYS`.
- If the article count exceeds 30, keep the overview longer and more structured (e.g., grouped trends by subfield).
- Keep summaries in the user's language (Chinese vs English).
- Ensure report files are written as UTF-8 to avoid `?` garbling on Windows.

## Resources

- `references/journal_db_report.md`: Detailed prompt, DB schema, SQL, filtering logic, and report format.
