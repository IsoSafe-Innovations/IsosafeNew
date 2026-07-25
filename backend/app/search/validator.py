"""SELECT-only SQL validator. Every generated statement passes through here
before execution, every time. Rejects semicolons, comments, stacked queries,
and any mutating or DDL keyword.
"""
import re

# Keywords that must never appear anywhere in the statement (word-boundary match)
FORBIDDEN_KEYWORDS = {
    "insert", "update", "delete", "drop", "alter", "create", "truncate",
    "grant", "revoke", "copy", "call", "do", "execute", "prepare",
    "vacuum", "analyze", "reindex", "cluster", "listen", "notify",
    "lock", "comment", "security", "set", "reset", "show", "merge",
    "refresh", "discard", "declare", "fetch", "move", "checkpoint",
    "load", "import", "pg_read_file", "pg_write_file", "pg_sleep",
    "dblink", "lo_import", "lo_export",
}

ALLOWED_TABLES = {
    "cameras", "detections", "incidents", "analytics_hourly", "analytics_daily",
}


class SQLValidationError(ValueError):
    pass


def validate_select_only(sql: str) -> str:
    """Returns the cleaned SQL or raises SQLValidationError."""
    if not sql or not sql.strip():
        raise SQLValidationError("Empty SQL")
    cleaned = sql.strip()

    # No comments of any kind
    if "--" in cleaned or "/*" in cleaned or "*/" in cleaned or "#" in cleaned:
        raise SQLValidationError("Comments are not allowed")

    # No semicolons anywhere (blocks stacked queries; a single trailing one is also rejected
    # so the model learns to omit it)
    if ";" in cleaned:
        raise SQLValidationError("Semicolons are not allowed")

    # Must start with SELECT or WITH (CTE)
    first_word = re.match(r"^\s*(\w+)", cleaned)
    if not first_word or first_word.group(1).lower() not in ("select", "with"):
        raise SQLValidationError("Only SELECT statements are allowed")

    # If it starts with WITH, ensure the body is a SELECT (no data-modifying CTEs)
    lowered = cleaned.lower()

    # Word-boundary scan for forbidden keywords
    for kw in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}\b", lowered):
            raise SQLValidationError(f"Forbidden keyword: {kw.upper()}")

    # Block access to system catalogs and non-allowlisted schemas
    if re.search(r"\bpg_", lowered) or "information_schema" in lowered:
        raise SQLValidationError("System catalog access is not allowed")

    # CTE names defined in this statement are legal FROM targets
    cte_names = set(re.findall(r"(?:\bwith\s+|,\s*)([a-z_][a-z0-9_]*)\s+as\s*\(", lowered))

    # Ensure referenced tables are in the allowlist
    tables = re.findall(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_.]*)", lowered)
    for table in tables:
        base = table.split(".")[-1]
        if base not in ALLOWED_TABLES and base not in cte_names:
            raise SQLValidationError(f"Table not allowed: {table}")

    return cleaned
