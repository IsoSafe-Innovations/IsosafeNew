"""Natural-language search: operator query + schema DDL -> Claude -> validated
SELECT -> execution with a 5s statement timeout and 100-row cap.

Only the query text leaves the network. No video, frames, or rows are sent.
"""
import json
import logging

from app.config import get_settings
from app.db.engine import get_asyncpg_pool
from app.search.validator import SQLValidationError, validate_select_only

log = logging.getLogger(__name__)

ROW_CAP = 100
STATEMENT_TIMEOUT_MS = 5000

SCHEMA_DDL = """
cameras(id TEXT, name TEXT, type TEXT, vertical_profile TEXT, enabled BOOLEAN, created_at TIMESTAMPTZ)
detections(id BIGINT, camera_id TEXT, ts TIMESTAMPTZ, object_type TEXT, confidence REAL,
           track_id INT, bbox REAL[], zone_ids TEXT[], plate_text TEXT, plate_confidence REAL)
  -- object_type in: person, car, motorcycle, bus, truck, backpack, suitcase
incidents(id BIGINT, camera_id TEXT, ts TIMESTAMPTZ, incident_type TEXT,
          severity TEXT, description TEXT, status TEXT, assigned_to TEXT,
          resolved_at TIMESTAMPTZ, resolution_notes TEXT)
  -- severity in: info, warning, critical; status in: open, investigating, resolved, closed
analytics_hourly(camera_id TEXT, bucket TIMESTAMPTZ, footfall INT, vehicles JSONB,
                 avg_queue REAL, max_queue INT, avg_occupancy REAL, incident_count INT)
analytics_daily(camera_id TEXT, day DATE, footfall INT, vehicles JSONB, avg_queue REAL,
                max_queue INT, avg_occupancy REAL, incident_count INT, peak_hour INT)
"""

SYSTEM_PROMPT = f"""You translate natural-language questions about a CCTV video \
intelligence system into a single PostgreSQL SELECT statement.

Schema:
{SCHEMA_DDL}

Rules:
- Respond with ONLY a JSON object: {{"sql": "...", "explanation": "..."}}
- The SQL must be a single SELECT (CTEs with WITH are fine). Never any other statement type.
- No semicolons. No comments. No system catalogs.
- Always include a LIMIT of {ROW_CAP} or less.
- Timestamps are UTC (timestamptz). Use now() and intervals for relative times.
- The explanation is one plain-English sentence describing what the query returns."""


class SearchUnavailable(Exception):
    pass


async def generate_sql(question: str) -> dict:
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise SearchUnavailable("ANTHROPIC_API_KEY not configured")

    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": question}],
    )
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    # tolerate fenced output
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text)
        return {"sql": data["sql"], "explanation": data.get("explanation", "")}
    except (json.JSONDecodeError, KeyError) as e:
        raise SQLValidationError("Model did not return valid JSON") from e


async def execute_search(question: str) -> dict:
    generated = await generate_sql(question)
    sql = validate_select_only(generated["sql"])

    pool = await get_asyncpg_pool()
    async with pool.acquire() as conn:
        # read-only transaction + statement timeout as defense in depth
        async with conn.transaction(readonly=True):
            await conn.execute(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")
            rows = await conn.fetch(sql)

    rows = rows[:ROW_CAP]
    columns = list(rows[0].keys()) if rows else []
    return {
        "sql": sql,
        "explanation": generated["explanation"],
        "columns": columns,
        "rows": [[_jsonable(v) for v in row.values()] for row in rows],
        "row_count": len(rows),
    }


def _jsonable(value):
    import datetime as dt
    import decimal
    import uuid

    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value
