"""Read-only checks against the public HTTPS front door, not the internal API."""
import argparse
import json
from urllib.parse import urlparse

import httpx


def check(base):
    checks = {}
    with httpx.Client(base_url=base, timeout=15, follow_redirects=False) as client:
        page = client.get("/")
        checks["dashboard"] = page.status_code == 200
        checks["hsts"] = "max-age=" in page.headers.get("strict-transport-security", "")
        checks["no_sniff"] = page.headers.get("x-content-type-options") == "nosniff"
        checks["frame_protection"] = page.headers.get("x-frame-options", "").upper() == "DENY"
        for path in ("/api/cameras", "/api/incidents", "/api/users"):
            checks["unauthenticated " + path] = client.get(path).status_code == 401
            checks["forged_token " + path] = client.get(path, headers={"Authorization": "Bearer invalid.invalid.invalid"}).status_code == 401
        checks["metrics_private"] = client.get("/api/metrics").status_code == 404
        checks["legacy_media_private"] = client.get("/media/private.jpg").status_code == 404
        health = client.get("/api/health")
        checks["healthy"] = health.status_code == 200 and health.json().get("status") == "ok"
        redirect = client.get(base.replace("https://", "http://", 1) + "/")
        checks["https_redirect"] = redirect.status_code in (301, 308) and redirect.headers.get("location", "").startswith(base)
    return {"passed": all(checks.values()), "checks": checks}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    args = parser.parse_args()
    if urlparse(args.base).scheme != "https":
        parser.error("Use the public HTTPS URL; certificate validation is required")
    report = check(args.base.rstrip("/"))
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] else 1)
