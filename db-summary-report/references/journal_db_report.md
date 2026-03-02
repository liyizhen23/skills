# Journal DB Summary Report Reference

Use this reference as the canonical prompt and specification for the workflow.

## Variables

| Variable | Type | Default | Meaning |
| --- | --- | --- | --- |
| `DAYS` | Integer | `7` | Query articles uploaded in the last N days |
| `TOPIC` | String | `""` | Topic filter. Empty means no filtering |

## Database Connection

- Host: `aws-0-us-east-1.pooler.supabase.com`
- Port: `5432`
- Database: `postgres`
- Username: `journals_reader.qyyqlnwqwgvzxnccnbgm`
- Password: read from user input or secure environment variable. Never print it.

## Table Schema: `journals`

- `id`: UUID
- `journal`: Journal name
- `title`: Paper title
- `authors`: JSON array, e.g. `["张三", "李四"]`
- `doi`: DOI identifier
- `date`: Publication year-month (e.g. `"2023-08"`)
- `created_at`: timestamptz (used for time filtering; always use this field)
- `abstract`: Original abstract text (nullable)

## Query (Python + psycopg2)

```python
from datetime import datetime, timedelta, timezone
import psycopg2

days = int("{{DAYS}}") if "{{DAYS}}" else 7
start_time = datetime.now(timezone.utc) - timedelta(days=days)

conn = psycopg2.connect(
    host="aws-0-us-east-1.pooler.supabase.com",
    port=5432,
    database="postgres",
    user="journals_reader.qyyqlnwqwgvzxnccnbgm",
    password="<PASSWORD_FROM_ENV>"
)
cursor = conn.cursor()
cursor.execute("""
    SELECT id, journal, title, authors, doi, date, created_at, abstract
    FROM journals
    WHERE created_at >= %s
    ORDER BY created_at DESC
""", (start_time,))
rows = cursor.fetchall()
```

## Topic Filtering

- If `TOPIC` is empty: skip filtering and keep all rows.
- If `TOPIC` is non-empty:
  - Perform keyword matching over `title` and `abstract`.
  - If zero matches, broaden to fuzzy matching.
  - If still zero, notify the user and return all rows.

## Weekly Trend Summary Rules

- Summarize shared themes, methods, and trends across all papers.
- Focus on 3-6 major themes, highlighting shifts, emerging methods, or common problem settings.
- Do not produce per-paper summaries.
- Use `title`, `journal`, and `abstract` (if present) as evidence; paraphrase only.
- Language: same as the user.

## Output Report Format (Weekly)

```
# 📚 期刊数据库摘要报告
**统计时间段**：[start_date] 至 [end_date]（最近 {{DAYS}} 天）
**主题过滤**：{{TOPIC}}（若为空则显示"全部文章，不限主题"）
**本期文章总数**：X 篇 | 涉及期刊：X 种
---

## 📊 本期共性与趋势

[按主题分组的趋势总结：每组 2-4 句，覆盖研究对象、方法/技术路线、主要发现或应用场景]

## 🧾 代表性条目（可选）

[仅列出 5-10 篇代表性论文的标题与期刊，用于说明趋势来源；不写逐篇摘要]
```

## Supplementary Rules

1. Do not return raw `abstract` content.
2. If zero rows in the time range, tell the user and suggest increasing `DAYS`.
3. If article count > 30, expand and structure the trend summary (grouped by subfields).
4. Never output database passwords in any form.
5. Keep report language aligned with the user.
6. Always write report files with UTF-8 encoding on Windows.

## Encoding Guidance (Windows)

If you write a report to a file, force UTF-8:

```python
with open(output_path, "w", encoding="utf-8", newline="\n") as f:
    f.write(report_text)
```

If you print to console and redirect to a file, set the console code page:

```powershell
chcp 65001
python scripts/run_report.py > report.md
```

Note: If the report already contains `?`, the characters are lost; regenerate after fixing encoding.
