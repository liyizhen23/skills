#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate a trend-focused report from the journals table.

Usage:
  python scripts/run_report.py --days 1 --output report_last_1d.md
  python scripts/run_report.py --days 1 --topics "AI, machine learning" --output report_last_1d.md
  python scripts/run_report.py --days 1 --topics "AI" --llm --output report_last_1d.md

Requirements:
  - psycopg2 installed
  - DB_PASSWORD env var set (supports loading from .env)
  - Optional: openai SDK + OPENAI_API_KEY for OpenAI mode
  - Optional: anthropic SDK + ANTHROPIC_API_KEY for Claude mode
"""

import argparse
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import psycopg2


DB_CONFIG = {
    "host": "aws-0-us-east-1.pooler.supabase.com",
    "port": 5432,
    "database": "postgres",
    "user": "journals_reader.qyyqlnwqwgvzxnccnbgm",
}

DEFAULT_OPENAI_MODEL = "gpt-4.1"
DEFAULT_ANTHROPIC_MODEL = "claude-3-5-sonnet-latest"


def _load_dotenv_if_exists() -> None:
    env_candidates = [Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"]
    env_path = next((p for p in env_candidates if p.exists()), None)
    if not env_path:
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if len(value) >= 2 and ((value[0] == '"' and value[-1] == '"') or (value[0] == "'" and value[-1] == "'")):
            value = value[1:-1]

        # Empty values in .env should not override SDK defaults derived from missing vars.
        if value == "":
            continue

        # Keep externally provided env vars as higher priority.
        if key not in os.environ:
            os.environ[key] = value


def _topic_match(text: str, topic: str) -> bool:
    return topic in text


def _fuzzy_match(text: str, topic: str) -> bool:
    tokens = [t for t in topic.replace("-", " ").split() if t]
    return any(t in text for t in tokens) if tokens else False


def _load_rows(days: int) -> List[Dict]:
    start_time = datetime.now(timezone.utc) - timedelta(days=days)
    password = os.environ.get("DB_PASSWORD", "").strip()
    if not password:
        raise RuntimeError("DB_PASSWORD environment variable is required. You can set it in .env.")

    conn = psycopg2.connect(password=password, **DB_CONFIG)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, journal, title, authors, doi, date, created_at, abstract
        FROM journals
        WHERE created_at >= %s
        ORDER BY created_at DESC
        """,
        (start_time,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    cols = ["id", "journal", "title", "authors", "doi", "date", "created_at", "abstract"]
    norm_rows = []
    for r in rows:
        d = dict(zip(cols, r))
        if d.get("created_at") is not None:
            d["created_at"] = d["created_at"].isoformat()
        norm_rows.append(d)
    return norm_rows


def _filter_rows(rows: List[Dict], topics: List[str]) -> Tuple[List[Dict], bool]:
    if not topics:
        return rows, False
    topics_l = [t.lower() for t in topics if t.strip()]
    matched = []
    for r in rows:
        title = (r.get("title") or "").lower()
        abstract = (r.get("abstract") or "").lower()
        if any(_topic_match(title, t) or _topic_match(abstract, t) for t in topics_l):
            matched.append(r)

    if matched:
        return matched, False

    fuzzy = []
    for r in rows:
        title = (r.get("title") or "").lower()
        abstract = (r.get("abstract") or "").lower()
        if any(_fuzzy_match(title, t) or _fuzzy_match(abstract, t) for t in topics_l):
            fuzzy.append(r)

    if fuzzy:
        return fuzzy, False

    return rows, True


def _representative_items(rows: List[Dict]) -> List[Tuple[str, str]]:
    keywords = [
        "ai",
        "artificial intelligence",
        "machine learning",
        "deep learning",
        "neural",
        "model",
        "optimization",
        "prediction",
        "classification",
    ]
    rep = []
    used = set()
    for kw in keywords:
        for r in rows:
            title = (r.get("title") or "").lower()
            if kw in title and r.get("id") not in used:
                rep.append((r.get("title") or "", r.get("journal") or ""))
                used.add(r.get("id"))
                break
        if len(rep) >= 10:
            break
    if len(rep) < 8:
        for r in rows:
            if r.get("id") in used:
                continue
            rep.append((r.get("title") or "", r.get("journal") or ""))
            used.add(r.get("id"))
            if len(rep) >= 10:
                break
    return rep


def _extract_response_text(response) -> str:
    if hasattr(response, "output_text") and response.output_text:
        return response.output_text
    output = getattr(response, "output", None)
    if not output:
        return str(response)
    texts = []
    for item in output:
        if isinstance(item, dict):
            if item.get("type") == "output_text" and item.get("text"):
                texts.append(item["text"])
            for content in item.get("content", []) or []:
                if content.get("type") == "output_text" and content.get("text"):
                    texts.append(content["text"])
    return "\n".join(texts).strip()


def _openai_generate_text(client, model: str, prompt: str) -> str:
    try:
        response = client.responses.create(
            model=model,
            input=[{"role": "user", "content": prompt}],
        )
        return _extract_response_text(response)
    except Exception as exc:
        # Some OpenAI-compatible gateways do not support /responses.
        if "404" not in str(exc) and "Not Found" not in str(exc):
            raise

    completion = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return (completion.choices[0].message.content or "").strip()


def _chunk_papers(rows: List[Dict], max_chars: int = 12000) -> List[str]:
    chunks = []
    current = []
    cur_len = 0
    for r in rows:
        title = (r.get("title") or "").strip()
        journal = (r.get("journal") or "").strip()
        abstract = (r.get("abstract") or "").strip()
        if len(abstract) > 800:
            abstract = abstract[:800] + "..."
        entry = f"Title: {title}\nJournal: {journal}\nAbstract: {abstract}\n"
        if cur_len + len(entry) > max_chars and current:
            chunks.append("\n".join(current))
            current = [entry]
            cur_len = len(entry)
        else:
            current.append(entry)
            cur_len += len(entry)
    if current:
        chunks.append("\n".join(current))
    return chunks


def _build_chunk_prompt(chunk: str, idx: int, total: int, topics: List[str]) -> str:
    focus = f"重点围绕主题：{', '.join(topics)}。" if topics else "请从整体上归纳共同关注点与研究趋势。"
    return (
        "你是科研综述分析助手。基于以下论文标题与摘要，提炼该批文献的共同关注点与研究趋势。\n"
        "要求：\n"
        "- 输出 3-6 条要点，使用无序列表（每条以“- ”开头）\n"
        "- 不要逐篇摘要，不要罗列标题\n"
        "- 不要原文引用摘要内容，必须改写\n"
        "- 避免固定模板句式，表达自然且具体\n"
        "- 语气为AI分析报告，突出趋势、方法路线、关注对象变化\n"
        f"- {focus}\n\n"
        f"【批次 {idx}/{total}】\n"
        f"{chunk}"
    )


def _build_merge_prompt(chunk_summaries: List[str]) -> str:
    return (
        "你是科研综述分析助手。以下是多个批次的趋势要点，"
        "请综合去重并输出最终的 3-6 条共同关注点与研究趋势，中文输出。\n"
        "要求：\n"
        "- 使用无序列表（每条以“- ”开头）\n"
        "- 不要复述批次编号\n"
        "- 不要原文引用摘要内容\n"
        "- 避免固定模板句式\n\n"
        + "\n\n".join(chunk_summaries)
    )


def _extract_anthropic_text(message) -> str:
    parts = []
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", "") == "text":
            text = getattr(block, "text", "")
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def _theme_summary_openai(rows: List[Dict], topics: List[str], model: str) -> List[str]:
    try:
        from openai import OpenAI
    except Exception as exc:
        raise RuntimeError("Missing openai SDK. Install with `pip install openai`.") from exc

    api_key = (
        os.environ.get("OPENAI_API_KEY", "").strip()
        or os.environ.get("LLM_API_KEY", "").strip()
        or os.environ.get("CLAUDE_API_KEY", "").strip()
        or os.environ.get("ANTHROPIC_API_KEY", "").strip()
    )
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY (or LLM_API_KEY / CLAUDE_API_KEY) is required for OpenAI mode. You can set it in .env."
        )

    base_url = (
        os.environ.get("OPENAI_BASE_URL", "").strip()
        or os.environ.get("LLM_BASE_URL", "").strip()
        or os.environ.get("ANTHROPIC_BASE_URL", "").strip()
    )
    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = OpenAI(**client_kwargs)
    chunks = _chunk_papers(rows)

    chunk_summaries = []
    for idx, chunk in enumerate(chunks, start=1):
        prompt = _build_chunk_prompt(chunk, idx, len(chunks), topics)
        text = _openai_generate_text(client, model, prompt)
        chunk_summaries.append(text.strip())

    if len(chunk_summaries) == 1:
        return [line for line in chunk_summaries[0].splitlines() if line.strip()]

    merge_prompt = _build_merge_prompt(chunk_summaries)
    text = _openai_generate_text(client, model, merge_prompt)
    return [line for line in text.splitlines() if line.strip()]


def _theme_summary_anthropic(rows: List[Dict], topics: List[str], model: str) -> List[str]:
    try:
        from anthropic import Anthropic
    except Exception as exc:
        raise RuntimeError("Missing anthropic SDK. Install with `pip install anthropic`.") from exc

    api_key = (
        os.environ.get("ANTHROPIC_API_KEY", "").strip()
        or os.environ.get("CLAUDE_API_KEY", "").strip()
        or os.environ.get("LLM_API_KEY", "").strip()
        or os.environ.get("OPENAI_API_KEY", "").strip()
    )
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY (or CLAUDE_API_KEY / LLM_API_KEY) is required for Claude mode. You can set it in .env."
        )

    base_url = (
        os.environ.get("ANTHROPIC_BASE_URL", "").strip()
        or os.environ.get("LLM_BASE_URL", "").strip()
    )
    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = Anthropic(**client_kwargs)
    chunks = _chunk_papers(rows)

    chunk_summaries = []
    for idx, chunk in enumerate(chunks, start=1):
        prompt = _build_chunk_prompt(chunk, idx, len(chunks), topics)
        response = client.messages.create(
            model=model,
            max_tokens=1200,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )
        text = _extract_anthropic_text(response)
        chunk_summaries.append(text.strip())

    if len(chunk_summaries) == 1:
        return [line for line in chunk_summaries[0].splitlines() if line.strip()]

    merge_prompt = _build_merge_prompt(chunk_summaries)
    response = client.messages.create(
        model=model,
        max_tokens=1200,
        temperature=0.2,
        messages=[{"role": "user", "content": merge_prompt}],
    )
    text = _extract_anthropic_text(response)
    return [line for line in text.splitlines() if line.strip()]


def _resolve_model(provider: str, cli_model: str) -> str:
    if cli_model:
        return cli_model
    if provider == "anthropic":
        return os.environ.get("ANTHROPIC_MODEL", "").strip() or os.environ.get("LLM_MODEL", "").strip() or DEFAULT_ANTHROPIC_MODEL
    return os.environ.get("OPENAI_MODEL", "").strip() or os.environ.get("LLM_MODEL", "").strip() or DEFAULT_OPENAI_MODEL


def _theme_summary_llm(rows: List[Dict], topics: List[str], provider: str, model: str) -> List[str]:
    if provider == "anthropic":
        return _theme_summary_anthropic(rows, topics, model)
    return _theme_summary_openai(rows, topics, model)


def _format_report(
    rows: List[Dict],
    start_time: datetime,
    end_time: datetime,
    topics: List[str],
    fallback_all: bool,
    theme_lines: List[str],
    days: int,
) -> str:
    journal_count = len(set([r.get("journal") for r in rows if r.get("journal")]))
    rep_items = _representative_items(rows)
    rep_list = "\n".join(
        [f"- {title}（{journal}）" for title, journal in rep_items]
    ) if rep_items else "- 本期未提取代表性条目"

    header = [
        "# 期刊数据库摘要报告",
        f"**统计时间段**：{start_time.strftime('%Y-%m-%d %H:%M UTC')} 至 {end_time.strftime('%Y-%m-%d %H:%M UTC')}（最近 {days} 天）",
        f"**主题过滤**：{', '.join(topics) if topics else '未设置（全部文章）'}",
        f"**本期文章总数**：{len(rows)} 篇 | 涉及期刊：{journal_count} 种",
    ]
    if fallback_all:
        header.append("**提示**：未匹配到主题关键词，已返回全部结果。")

    body = [
        "---",
        "",
        "## 本期共性与趋势",
        *(theme_lines if theme_lines else ["- 未能生成趋势总结。"]),
        "",
        "## 代表性条目（可选）",
        rep_list,
    ]
    return "\n".join(header + body)


def main() -> int:
    _load_dotenv_if_exists()

    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument(
        "--topics",
        type=str,
        default="",
        help='Comma-separated list of topics, e.g. "AI, machine learning"',
    )
    parser.add_argument(
        "--provider",
        type=str,
        choices=["openai", "anthropic"],
        default=os.environ.get("LLM_PROVIDER", "openai"),
        help="LLM backend provider (default: LLM_PROVIDER or openai).",
    )
    llm_group = parser.add_mutually_exclusive_group()
    llm_group.add_argument(
        "--llm",
        action="store_true",
        help="Explicitly enable LLM-based trend analysis (default: enabled).",
    )
    llm_group.add_argument(
        "--no-llm",
        action="store_true",
        help="Disable LLM-based trend analysis.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="",
        help="Model name for selected provider. Uses provider defaults when omitted.",
    )
    parser.add_argument("--output", type=str, default="report_last_1d.md")
    args = parser.parse_args()

    rows = _load_rows(args.days)
    if not rows:
        report = "\n".join(
            [
                "# 期刊数据库摘要报告",
                f"**统计时间段**：最近 {args.days} 天",
                f"**主题过滤**：{args.topics if args.topics else '未设置（全部文章）'}",
                "",
                "未检索到任何文章，请尝试增大 DAYS。",
            ]
        )
        with open(args.output, "w", encoding="utf-8-sig") as f:
            f.write(report)
        return 0

    created_dt = [
        datetime.fromisoformat(r["created_at"]) for r in rows if r.get("created_at")
    ]
    start_time = min(created_dt) if created_dt else datetime.now(timezone.utc)
    end_time = max(created_dt) if created_dt else datetime.now(timezone.utc)

    topics = [t.strip() for t in args.topics.split(",") if t.strip()]
    filtered_rows, fallback_all = _filter_rows(rows, topics)

    use_llm = not args.no_llm
    if use_llm:
        model = _resolve_model(args.provider, args.model)
        theme_lines = _theme_summary_llm(filtered_rows, topics, args.provider, model)
    else:
        theme_lines = ["- 已禁用 AI 分析，无法生成趋势要点。"]

    report = _format_report(
        filtered_rows,
        start_time,
        end_time,
        topics,
        fallback_all,
        theme_lines,
        args.days,
    )

    with open(args.output, "w", encoding="utf-8-sig") as f:
        f.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
