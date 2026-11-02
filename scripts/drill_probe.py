"""Probe the recovered application over certificate-validated HTTPS from a peer container."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
import ssl
import sys
import threading
import time
import httpx

receipt = json.load(sys.stdin)
origin = "https://recovered-web:8443"
tls = ssl.create_default_context(cafile="/drill-ca.pem")
barrier = threading.Barrier(15, timeout=30)


def client():
    return httpx.Client(base_url=origin, verify=tls, trust_env=False, timeout=30, headers={"Origin":origin})


def analyst(i):
    session = client()
    barrier.wait()
    start = time.monotonic()
    login = session.post("/api/v1/auth/login", json={"login":f"drill{i}", "password":os.environ["GS_QA_PASSWORD"]})
    login.raise_for_status()
    cookie = login.headers["set-cookie"].lower()
    assert all(flag in cookie for flag in ("secure","httponly","samesite=strict"))
    session.headers["x-csrf-token"] = login.json()["csrf"]
    assert session.get("/api/v1/auth/me").json()["login"] == f"drill{i}"
    session.get("/api/v1/companies").raise_for_status()
    return session, (time.monotonic() - start) * 1000


with client() as anonymous:
    for attempt in range(40):
        try:
            if anonymous.get("/health/ready").status_code == 200:
                break
        except httpx.TransportError:
            pass
        time.sleep(1)
    else:
        raise RuntimeError("Recovered app did not become ready")
    assert anonymous.get("/api/v1/companies").status_code == 401
    anonymous.cookies.set("gs_session", receipt["old_session"])
    assert anonymous.get("/api/v1/auth/me").status_code == 401

with ThreadPoolExecutor(max_workers=15) as pool:
    sessions = list(pool.map(analyst, range(15)))
try:
    admin = sessions[0][0]
    original = receipt["document"]
    path = f'/api/v1/documents/{original["document_id"]}/versions/{original["version_id"]}/download'
    assert hashlib.sha256(admin.get(path).content).hexdigest() == original["sha256"]
    assert sessions[1][0].get(path).status_code == 404
    template = receipt["template"]
    path = f'/api/v1/templates/{template["template_id"]}/versions/{template["id"]}/original'
    assert hashlib.sha256(admin.get(path).content).hexdigest() == receipt["template_sha"]
    knowledge = admin.get("/api/v1/knowledge/jpm/export").json()
    assert len(knowledge["facts"]) == 1 and knowledge["state_hash"] == receipt["knowledge_hash"]
    assert admin.put("/api/v1/favorites/jpm", headers={"Origin":"https://untrusted.invalid"}).status_code == 403
    employee = sessions[-1][0].get("/api/v1/auth/me").json()["id"]
    admin.patch("/api/v1/users/"+employee, json={"active":False}).raise_for_status()
    assert sessions[-1][0].get("/api/v1/companies").status_code == 401
    run = admin.post("/api/v1/ai/proposals", json={"job_id": original["job_id"]})
    run.raise_for_status()
    for attempt in range(35):
        result = admin.get("/api/v1/ai/runs/"+run.json()["id"]).json()
        if result["state"] == "failed":
            break
        time.sleep(1)
    else:
        raise RuntimeError("Disconnected provider did not fail its queued task")
    admin.get("/api/v1/companies").raise_for_status()
    admin.get("/health/ready").raise_for_status()
    timings = sorted(item[1] for item in sessions)
    print(json.dumps(dict(concurrent_accounts=len(sessions), scenario="HTTPS login, session and catalog",
                          p50_ms=round(timings[7]), p95_ms=round(timings[math.ceil(.95*15)-1]),
                          original=True, template=True, reviewed_knowledge=True, revoked_session_denied=True,
                          old_session_denied=True, inference_outage_isolated=True)))
finally:
    for session, _ in sessions:
        session.close()
