"""M1 backend contract test: health, SSE, §7 payload, corpus path, quota 429."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["CHECKMATO_QUOTA_PATH"] = str(ROOT / "tests" / "_quota_test.json")
from fastapi.testclient import TestClient  # noqa: E402
from app.server import CFG, QUOTA, _client_ip, app  # noqa: E402

CFG["enforce_ip_quota"] = True    # exercise the hosted guest budget explicitly;
                                  # the dev toml ships enforce_ip_quota = false
CFG["quota_ip_per_day"] = 1        # test the PRODUCTION guest budget, not dev toml
CFG["max_words"] = 10_000
CFG["max_words_per_day"] = 60_000

DOC_PATH = ROOT / "tests" / "case_ai_draft.md"
DOC = DOC_PATH.read_text(encoding="utf-8")
CORPUS_DIR = ROOT / "tests" / "corpus"


def parse_sse(body):
    events, done_payload = [], None
    for block in body.split("\n\n"):
        ev = data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                ev = line[7:]
            if line.startswith("data: "):
                data = json.loads(line[6:])
        if data is None:
            continue
        events.append((ev, data))
        if ev == "done":
            done_payload = data
    return events, done_payload


def run_check(client, with_corpus=False):
    if with_corpus:
        data = {"web": "false", "llm": "false"}
        files = [("doc", (DOC_PATH.name, DOC.encode(), "text/markdown"))]
        for p in sorted(CORPUS_DIR.iterdir()):
            if p.is_file():
                mime = "application/pdf" if p.suffix == ".pdf" else "text/markdown"
                files.append(("corpus", (p.name, p.read_bytes(), mime)))
    else:
        data = {"text": DOC, "web": "false", "llm": "false"}
        files = None
    with client.stream("POST", "/api/check", data=data, files=files) as r:
        assert r.status_code == 200, r.status_code
        body = "".join(r.iter_text())
    events, done = parse_sse(body)
    assert done, "no done event"
    rep = client.get(f"/api/report/{done['job_id']}").json()
    return events, rep


def main():
    QUOTA.clear()
    Path(os.environ["CHECKMATO_QUOTA_PATH"]).unlink(missing_ok=True)

    class Req:
        def __init__(self, headers, host="10.0.0.1"):
            self.headers = headers
            self.client = type("C", (), {"host": host})()

    assert _client_ip(Req({"fly-client-ip": "203.0.113.9",
                           "x-forwarded-for": "6.6.6.6"})) == "203.0.113.9"
    assert _client_ip(Req({"x-forwarded-for": "198.51.100.7, 10.0.0.1"})) \
        == "198.51.100.7"
    print("  client IP: provider header wins over spoofable XFF")

    client = TestClient(app)
    h = client.get("/api/health").json()
    assert h["ok"] and h["quota"]["runs_per_day"] >= 1
    assert "runs_left" in h["quota"] and "brave_left" in h["quota"]
    print("  health: OK")

    # 1) paste-text, no corpus: conservative — no BYOS verdicts may appear
    events, rep = run_check(client, with_corpus=False)
    stages = [d.get("stage") for _, d in events]
    assert "parse" in stages and "extract" in stages and "check" in stages
    recs = rep["findings"]
    paras = rep["meta"]["paragraphs"]
    anchored = [x for x in recs if x["source_span"]]
    assert len(anchored) > 15, f"few anchors: {len(anchored)}"
    for x in anchored:
        p = paras[x["source_span"]["para"]]
        s, e = x["source_span"]["start"], x["source_span"]["end"]
        assert p[s:e] == x["quote"], f"anchor drift {x['claim_id']}"
    v = {x["verdict"] for x in recs}
    assert {"needs_fix", "structure", "unverified"} <= v, v
    assert "contradicted" not in v and "supported" not in v, \
        "BYOS verdicts without a corpus = engine lying"
    print(f"  no-corpus run: OK ({len(events)} events, {len(recs)} records, "
          f"spans verified, conservative)")

    # 2) quota: second guest run the same day is honestly refused
    bad = client.post("/api/check", data={"text": "again"})
    assert bad.status_code == 429 and "quota" in bad.json()["detail"].lower()
    print("  guest quota: 429 with budget message")
    QUOTA.clear()

    # 3) with corpus (multipart incl. a PDF): BYOS verdicts must appear
    _, rep2 = run_check(client, with_corpus=True)
    v2 = {x["verdict"] for x in rep2["findings"]}
    assert {"contradicted", "supported"} <= v2, v2
    assert rep2["meta"]["byos_sources"] > 0, rep2["meta"]
    assert str(rep2["meta"]["mode"]).startswith("sources"), rep2["meta"]["mode"]
    founded = next(x for x in rep2["findings"] if x["quote"] == "2008")
    assert founded["verdict"] == "contradicted" and founded["evidence"]
    assert any(".pdf" in e["ref"] for x in rep2["findings"]
               for e in x["evidence"]), "PDF corpus evidence not used"
    print(f"  corpus run: OK ({len(rep2['findings'])} records — contradicted/"
          f"supported present, PDF page evidence attached)")

    QUOTA.clear()
    bad2 = client.post("/api/check", data={"text": "   "})
    assert bad2.status_code == 400
    print("  empty input: 400")
    try:
        Path(os.environ["CHECKMATO_QUOTA_PATH"]).unlink(missing_ok=True)
    except Exception:
        pass
    print("WEBAPP: PASS")


if __name__ == "__main__":
    main()
