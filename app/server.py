"""CheckMato M1 backend — FastAPI + SSE.

Fully offline-capable on free tiers; LLM/web are opt-in per request and degrade
without keys. Quotas (§9) are budgets enforced per IP, never paywalls.

  GET  /api/health
  POST /api/check      multipart: {text?, doc?, corpus[]?, names?, web, llm, whitelist}
                       -> SSE stream (parse/corpus/extract/check/web events),
                          terminal `done` event carries {job_id, meta, findings}
  GET  /api/report/{job_id}
  POST /api/decision/{job_id}   JSON {claim_id, decision: keep|fix|dismiss, note?}
                        -> settles a `conflicting` finding; persisted, all
                           exports re-rendered with the decision
"""
import asyncio
import json
import logging
import os
import shutil
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from . import config
from . import quota
from .cli import run

logging.basicConfig(level=os.environ.get("CHECKMATO_LOG", "WARNING").upper(),
                    format="%(levelname)s %(name)s: %(message)s")

ENGINE = "M1 (FastAPI + deterministic engine; SSE progress)"
DATA_DIR = Path(tempfile.gettempdir()) / "checkmato_jobs"
DATA_DIR.mkdir(exist_ok=True)

app = FastAPI(title="CheckMato API", version="0.4")
# Behind Railway/Fly/Render/Vercel the browser calls the API cross-origin, so
# the dev localhost-only allowlist must be replaceable. No cookies/credentials
# are used (public free tool, IP quotas), so a wildcard default is safe; set
# CHECKMATO_CORS_ORIGINS="https://a.vercel.app,https://b.vercel.app" to lock it.
_ORIGINS = [o.strip() for o in
            os.environ.get("CHECKMATO_CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ORIGINS or ["*"],
    allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

CFG = config.load("checkmato.toml")
JOBS = {}
QUOTA = quota.IP
_LOCK = threading.Lock()


def _client_ip(request: Request):
    """Real visitor IP behind a proxy. request.client.host is the load
    balancer's address on every hosted deploy (Railway/Fly/Vercel) — using it
    would collapse all visitors into ONE daily quota bucket."""
    fwd = request.headers.get("x-forwarded-for") or ""
    if fwd:
        return fwd.split(",")[0].strip()
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return request.client.host if request.client else "anon"


@app.get("/api/health")
def health(request: Request):
    ip = _client_ip(request)
    return {"ok": True, "engine": ENGINE, "quota": quota.snapshot(ip, CFG)}


def _quota_check(ip, words):
    return quota.check_ip(ip, words, CFG)


def _word_estimate(text_len, doc_bytes):
    return int((text_len + doc_bytes) / 6)


def _sse(event, data):
    name = f"event: {event}\n" if event else ""
    return f"{name}data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _save_uploads(text, doc, corpus, names):
    """Persist multipart inputs to a job dir. Returns (work, doc_path,
    corpus_dir, names_path) or (None, error, None, None)."""
    job_id = uuid.uuid4().hex[:8]
    work = DATA_DIR / job_id
    work.mkdir(parents=True, exist_ok=True)

    async def _inner():
        doc_bytes = 0
        doc_path = None
        if doc and doc.filename:
            suffix = Path(doc.filename).suffix.lower()
            if suffix not in (".md", ".txt", ".docx"):
                shutil.rmtree(work, ignore_errors=True)
                return "document must be .md / .txt / .docx"
            blob = await doc.read()
            doc_bytes = len(blob)
            (work / f"input{suffix}").write_bytes(blob)
            doc_path = work / f"input{suffix}"
        elif not text.strip():
            shutil.rmtree(work, ignore_errors=True)
            return "no document — paste text or upload a file"
        else:
            doc_path = work / "input.md"
            doc_path.write_text(text, encoding="utf-8")
            doc_bytes = len(text.encode("utf-8"))
        corpus_dir = None
        cs = [c for c in (corpus or []) if c and c.filename]
        if cs:
            corpus_dir = work / "corpus"
            corpus_dir.mkdir()
            for cf in cs:
                (corpus_dir / Path(cf.filename).name).write_bytes(await cf.read())
        names_path = None
        if names and names.filename:
            names_path = work / Path(names.filename).name
            names_path.write_bytes(await names.read())
        return (work, doc_path, doc_bytes, corpus_dir, names_path)

    return _inner()


@app.post("/api/estimate")
async def check_estimate(request: Request, text: str = Form(""),
                         doc: UploadFile | None = File(None),
                         corpus: list[UploadFile] = File(default=[]),
                         names: UploadFile | None = File(None),
                         web: bool = Form(False), llm: bool = Form(False)):
    """Preflight (free, no quota): how big is this document, and how long
    will a FULL-DEPTH check take? Budgets scale with length; the user decides."""
    res = await _save_uploads(text, doc, corpus, names)
    if isinstance(res, str):
        return JSONResponse({"detail": res}, 400)
    work, doc_path, doc_bytes, corpus_dir, names_path = res
    from . import estimate as est
    try:
        stats = est.analyze(str(doc_path),
                            str(corpus_dir) if corpus_dir else None,
                            str(names_path) if names_path else None)
        e = est.estimate(stats, CFG, web=web or llm, llm=llm)
        e["doc"] = stats["doc"]
        e["paras"] = stats["paras"]
        return JSONResponse(e)
    except Exception as x:  # noqa: BLE001
        return JSONResponse({"detail": str(x)}, 500)
    finally:
        shutil.rmtree(work, ignore_errors=True)


@app.post("/api/check")
async def check(request: Request, text: str = Form(""),
                doc: UploadFile | None = File(None),
                corpus: list[UploadFile] = File(default=[]),
                names: UploadFile | None = File(None),
                web: bool = Form(False), llm: bool = Form(False),
                whitelist: str = Form(""), backend: str = Form("auto")):
    backend = backend if backend in ("auto", "brave", "ddgs") else "auto"
    ip = _client_ip(request)
    res = await _save_uploads(text, doc, corpus, names)
    if isinstance(res, str):
        return JSONResponse({"detail": res}, 400)
    work, doc_path, doc_bytes, corpus_dir, names_path = res
    job_id = work.name

    # QUOTA is in WORDS — but docx/pdf files are zips whose BYTES are far more
    # than their words (a 6.6k-word docx ≈ 40k bytes). Count actual words,
    # the same way MS Word does (CJK characters count individually).
    from .extract import read_doc
    from .textproc import count_words
    try:
        words = count_words(read_doc(str(doc_path))["paragraphs"])
    except Exception:
        words = _word_estimate(len(text), doc_bytes)

    with _LOCK:
        ok, why = _quota_check(ip, words)
        if not ok:
            shutil.rmtree(work, ignore_errors=True)
            return JSONResponse({"detail": why, "quota": True}, 429)
        # ONE live run per visitor: a stale browser tab (refresh does NOT stop
        # the server-side job) starting a second run would double-hammer the
        # shared keyless-search IP and the free LLM rate window.
        for jid, j in JOBS.items():
            if j.get("ip") == ip and j.get("status") == "running":
                shutil.rmtree(work, ignore_errors=True)
                return JSONResponse({"detail": "a check is still running for you — "
                                               "use Stop to end it first",
                                      "running_job": jid}, 409)
        JOBS[job_id] = {"status": "running", "ip": ip, "cancel": False,
                        "started": datetime.now().isoformat(), "words": words}

    out = work / "out"
    q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def job():
        quota.charge_ip(ip, words)
        try:
            findings, meta = run(
                str(doc_path), str(corpus_dir) if corpus_dir else None, str(out),
                use_web=web, use_llm=llm, max_search=CFG["max_search"],
                whitelist=[w.strip() for w in whitelist.split(",") if w.strip()],
                names=str(names_path) if names_path else None, cfg=CFG,
                backend=backend,
                progress=lambda ev: loop.call_soon_threadsafe(q.put_nowait, ev),
                cancel=lambda: JOBS.get(job_id, {}).get("cancel"))
            from .report import to_record
            JOBS[job_id].update(status="done", meta=meta,
                                records=[to_record(f) for f in findings])
            loop.call_soon_threadsafe(q.put_nowait,
                                      {"stage": "done", "job_id": job_id})
        except Exception as e:  # noqa: BLE001
            JOBS[job_id].update(status="error", error=str(e))
            loop.call_soon_threadsafe(q.put_nowait,
                                      {"stage": "error", "message": str(e)})

    threading.Thread(target=job, daemon=True).start()

    async def event_gen():
        yield _sse(None, {"stage": "job", "job_id": job_id})
        while True:
            ev = await q.get()
            stage = ev.get("stage")
            if stage == "done":
                jd = JOBS[job_id]
                yield _sse("done", {"job_id": job_id, "meta": jd["meta"],
                                    "findings": jd["records"]})
                return
            if stage == "error":
                yield _sse("error", ev)
                return
            yield _sse(None, ev)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.get("/api/report/{job_id}")
def get_report(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return JSONResponse({"detail": "no such job"}, 404)
    if job["status"] != "done":
        return {"status": job["status"]}
    return {"status": "done", "meta": job["meta"], "findings": job["records"],
            "decisions": job.get("decisions", {})}


DECISIONS = {"keep", "fix", "dismiss"}


@app.get("/api/active")
def active(request: Request):
    """A refreshed tab asks: do I already have a run going? (yes -> resume
    watching it via /api/report, or stop it — refresh must never orphan a
    running check into 'hollow waiting'.)"""
    ip = _client_ip(request)
    for jid, j in JOBS.items():
        if j.get("ip") == ip and j.get("status") == "running":
            return {"job_id": jid}
    return {"job_id": None}


@app.post("/api/cancel/{job_id}")
def cancel_job(job_id: str):
    """Cooperative stop: the engine checks this flag between units of work,
    stops searching, and FINISHES with a partial, honestly-labelled report
    (never a silent kill mid-write)."""
    job = JOBS.get(job_id)
    if not job:
        return JSONResponse({"detail": "no such job"}, 404)
    job["cancel"] = True
    return {"ok": True, "status": job.get("status")}


@app.post("/api/decision/{job_id}")
async def decision(job_id: str, payload: dict):
    """User settles a `conflicting` claim (sources disagreed; the engine never
    picks a side). Persisted to the job dir and re-rendered into every export,
    so the decision survives a server restart and ships with the report."""
    job = JOBS.get(job_id)
    if not job or job.get("status") != "done":
        return JSONResponse({"detail": "no such job"}, 404)
    cid = str(payload.get("claim_id") or "")
    dec = payload.get("decision")
    if dec not in DECISIONS:
        return JSONResponse({"detail": "decision must be keep/fix/dismiss"}, 400)
    rec = next((r for r in job["records"] if r["claim_id"] == cid), None)
    if not rec:
        return JSONResponse({"detail": "unknown claim_id"}, 404)
    note = str(payload.get("note") or "")[:300]
    rec["status"] = f"decided:{dec}"
    rec["user_note"] = note
    job.setdefault("decisions", {})[cid] = {
        "decision": dec, "note": note, "ts": datetime.now().isoformat()}
    out = DATA_DIR / job_id / "out"
    try:
        (out / "decisions.json").write_text(
            json.dumps(job["decisions"], ensure_ascii=False, indent=1),
            encoding="utf-8")
        from .report import rerender_with_decisions
        rerender_with_decisions(str(out), job["meta"], job["records"])
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"detail": f"decision saved but re-render failed: {e}"}, 500)
    return {"ok": True, "record": rec}


EXPORTS = {"md": "report.md", "xlsx": "report.xlsx", "jsonl": "claims.jsonl",
           "annotated_md": "annotated.md", "annotated_docx": "annotated.docx",
           "decisions": "decisions.json"}


@app.get("/api/export/{job_id}/{kind}")
def export(job_id: str, kind: str):
    p = DATA_DIR / job_id / "out" / EXPORTS.get(kind, "")
    if not p.exists():
        return JSONResponse({"detail": "not available for this job"}, 404)
    from fastapi.responses import FileResponse
    media = ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
             if kind.endswith("xlsx") or kind == "annotated_docx"
             else "application/json" if kind in ("jsonl", "decisions")
             else "text/markdown")
    return FileResponse(str(p), media_type=media, filename=p.name)


# Single-process mode: serve the static Next export (web/out) beside the API,
# so `uvicorn app.server:app` alone gives http://localhost:8000 as a full app.
# Mounted LAST so it never shadows the /api routes above.
WEB_OUT = Path(__file__).resolve().parents[1] / "web" / "out"
if WEB_OUT.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=str(WEB_OUT), html=True), name="web")
