"""End-to-end API smoke test against a running server.

Usage: python -m scripts.smoke_api http://localhost:8010
"""
import os
import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8010"
ADMIN = {
    "email": os.environ.get("SMOKE_ADMIN_EMAIL", "admin@isosafe.local"),
    "password": os.environ.get("SMOKE_ADMIN_PASSWORD", "smoke-test-pass1"),
}

passed = failed = skipped = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS {name}")
    else:
        failed += 1
        print(f"  FAIL {name} {detail}")


def skip(name: str, reason: str) -> None:
    global skipped
    skipped += 1
    print(f"  SKIP {name} ({reason})")


def main() -> None:
    c = httpx.Client(base_url=BASE, timeout=30)

    # health
    r = c.get("/api/health")
    body = r.json()
    check("health 200", r.status_code == 200)
    check("health db ok", body["database"]["ok"], str(body))
    check("health redis ok", body["redis"]["ok"], str(body))

    # metrics
    r = c.get("/api/metrics")
    check("prometheus metrics", r.status_code == 200 and b"isosafe" in r.content)

    # openapi
    r = c.get("/openapi.json")
    check("openapi renders", r.status_code == 200 and len(r.json()["paths"]) > 15)

    # auth
    r = c.post("/api/auth/login", json=ADMIN)
    check("admin login", r.status_code == 200, r.text)
    tokens = r.json()
    admin_h = {"Authorization": f"Bearer {tokens['access_token']}"}

    r = c.post("/api/auth/login", json={"email": ADMIN["email"], "password": "wrong"})
    check("bad password rejected", r.status_code == 401)

    r = c.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    check("refresh flow", r.status_code == 200)

    r = c.get("/api/cameras")
    check("unauthenticated 401", r.status_code == 401)

    # create viewer user
    r = c.post("/api/users", headers=admin_h,
               json={"email": "viewer@test.local", "password": "viewerpass123", "role": "viewer"})
    check("create viewer", r.status_code in (201, 409), r.text)
    r = c.post("/api/auth/login", json={"email": "viewer@test.local", "password": "viewerpass123"})
    viewer_h = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # viewer read access ok
    r = c.get("/api/cameras", headers=viewer_h)
    check("viewer can list cameras", r.status_code == 200)

    # viewer 403 on every mutation
    mutations = [
        ("POST", "/api/cameras", {"name": "x", "source": "file.mp4", "type": "file"}),
        ("PATCH", "/api/cameras/cam-x", {"name": "y"}),
        ("DELETE", "/api/cameras/cam-x", None),
        ("PATCH", "/api/incidents/1", {"status": "closed"}),
        ("POST", "/api/users", {"email": "e@x.com", "password": "longenough1", "role": "viewer"}),
        ("PATCH", "/api/users/00000000-0000-0000-0000-000000000000", {"role": "admin"}),
        ("DELETE", "/api/users/00000000-0000-0000-0000-000000000000", None),
    ]
    for method, path, body in mutations:
        r = c.request(method, path, headers=viewer_h, json=body)
        check(f"viewer 403 on {method} {path}", r.status_code == 403, f"got {r.status_code}")

    # camera CRUD as admin
    r = c.post("/api/cameras", headers=admin_h, json={
        "name": "Demo Cam", "source": "rtsp://user:secret@10.0.0.9/s1", "type": "rtsp",
        "vertical_profile": "estate",
    })
    check("admin creates camera", r.status_code == 201, r.text)
    cam = r.json()
    check("profile pre-populated rules", len(cam["rules"]) >= 4, str(len(cam.get("rules", []))))
    check("source credentials redacted", "secret" not in cam["source"], cam["source"])

    r = c.patch(f"/api/cameras/{cam['id']}", headers=admin_h,
                json={"zones": [{"id": "gate", "name": "Gate",
                                 "polygon": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]}]})
    check("admin edits zones", r.status_code == 200, r.text)

    # detections with cursor pagination. Staging/demo DBs may not have the
    # cam-05 bench data seeded, so an empty result is a skip, not a failure.
    r = c.get("/api/detections?camera=cam-05&limit=50", headers=viewer_h)
    items1 = r.json().get("items", []) if r.status_code == 200 else []
    if not items1:
        check("detections endpoint", r.status_code == 200, r.text[:200])
        skip("detections pagination", "cam-05 bench data not seeded")
    else:
        check("detections page 1", r.status_code == 200, r.text[:200])
        cursor = r.json().get("next_cursor")
        if cursor is None:
            check("detections single page", len(items1) <= 50)
        else:
            r2 = c.get(f"/api/detections?camera=cam-05&limit=50&cursor={cursor}", headers=viewer_h)
            items2 = r2.json().get("items", []) if r2.status_code == 200 else []
            ids1 = {i["id"] for i in items1}
            ids2 = {i["id"] for i in items2}
            check("cursor pages disjoint", r2.status_code == 200 and not (ids1 & ids2))

    # incidents + stats + counts
    r = c.get("/api/incidents?limit=10", headers=viewer_h)
    check("incidents list", r.status_code == 200)
    r = c.get("/api/stats/all?hours=24", headers=viewer_h)
    check("stats endpoint", r.status_code == 200)
    r = c.get("/api/overview", headers=viewer_h)
    check("overview KPIs", r.status_code == 200 and "today" in r.json())
    r = c.get("/api/counts", headers=viewer_h)
    check("live counts", r.status_code == 200)

    # search without API key -> 503 graceful degradation
    r = c.post("/api/search", headers=viewer_h, json={"query": "how many people today"})
    check("search degrades without key", r.status_code == 503, f"got {r.status_code}")
    r = c.get("/api/insights", headers=viewer_h)
    check("insights degrade without key",
          r.status_code == 200 and r.json()["available"] is False)

    # reports
    r = c.get("/api/reports/daily_summary?format=pdf", headers=viewer_h)
    check("PDF report", r.status_code == 200 and r.content[:4] == b"%PDF")
    r = c.get("/api/reports/camera_health?format=xlsx", headers=viewer_h)
    check("XLSX report", r.status_code == 200 and r.content[:2] == b"PK")

    # profiles list
    r = c.get("/api/cameras/profiles", headers=viewer_h)
    check("profiles list", r.status_code == 200 and len(r.json()) >= 14)

    # cleanup demo camera
    c.request("DELETE", f"/api/cameras/{cam['id']}", headers=admin_h)

    print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
