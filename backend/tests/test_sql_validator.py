"""Phase 10 acceptance: injection attempts (DROP, UPDATE, stacked queries) are
rejected before execution; legitimate SELECTs pass."""
import pytest

from app.search.validator import SQLValidationError, validate_select_only

VALID = [
    "SELECT * FROM incidents WHERE severity = 'critical' LIMIT 100",
    "SELECT camera_id, COUNT(*) FROM detections GROUP BY camera_id LIMIT 50",
    "WITH recent AS (SELECT * FROM detections WHERE ts > now() - interval '1 hour') "
    "SELECT object_type, COUNT(*) FROM recent GROUP BY object_type LIMIT 10",
    "select plate_text from detections where plate_text is not null limit 20",
    "SELECT * FROM analytics_hourly WHERE bucket > now() - interval '7 days' LIMIT 100",
    "SELECT i.camera_id, c.name FROM incidents i JOIN cameras c ON c.id = i.camera_id LIMIT 5",
]

INVALID = [
    "DROP TABLE detections",
    "UPDATE incidents SET status = 'closed'",
    "DELETE FROM detections",
    "INSERT INTO users (email) VALUES ('x')",
    "SELECT * FROM incidents; DROP TABLE incidents",
    "SELECT * FROM incidents -- sneaky comment",
    "SELECT * FROM incidents /* block comment */",
    "SELECT * FROM users LIMIT 10",  # users table not allowlisted
    "SELECT * FROM pg_catalog.pg_tables",
    "SELECT pg_sleep(60)",
    "SELECT * FROM information_schema.tables",
    "TRUNCATE detections",
    "CREATE TABLE evil (id INT)",
    "ALTER TABLE incidents ADD COLUMN x INT",
    "GRANT ALL ON detections TO public",
    "SELECT * FROM detections; SELECT * FROM incidents",
    "",
    "   ",
    "EXPLAIN SELECT * FROM incidents",
    "COPY detections TO '/tmp/x'",
    "WITH x AS (DELETE FROM incidents RETURNING *) SELECT * FROM x",
]


@pytest.mark.parametrize("sql", VALID)
def test_valid_selects_pass(sql):
    assert validate_select_only(sql) == sql.strip()


@pytest.mark.parametrize("sql", INVALID)
def test_injection_rejected(sql):
    with pytest.raises(SQLValidationError):
        validate_select_only(sql)
