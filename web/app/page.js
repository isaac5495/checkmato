"use client";
import { useEffect, useRef, useState } from "react";

const VERDICTS = {
  contradicted: { label: "Contradicted", color: "#c0392b", bg: "#ffe3e3" },
  internal_conflict: { label: "Internal conflict", color: "#c2185b", bg: "#ffe0ef" },
  misattributed: { label: "Misattributed quote", color: "#b3541e", bg: "#ffedd6" },
  conflicting: { label: "Sources disagree", color: "#b45309", bg: "#ffe8cc" },
  paraphrase_flag: { label: "Possible embellishment", color: "#8a6d00", bg: "#fff3c4" },
  needs_fix: { label: "Needs fix", color: "#8a6d00", bg: "#fff3c4" },
  structure: { label: "Structure defect", color: "#5b6770", bg: "#e7ecef" },
  supported: { label: "Supported", color: "#1e7d43", bg: "#dcf2e4" },
  unverified: { label: "Unverified", color: "#5b6770", bg: "#eef1f3" },
  narrative: { label: "Narrative (nothing to check)", color: "#2f6cb0", bg: "#e1eefb" },
  deferred_web: { label: "Deferred (web budget)", color: "#33628f", bg: "#e2eefb" },
};

const STAGE_LABEL = {
  estimate: "Preflight estimate",
  parse: "Parsing document",
  corpus: "Indexing BYOS sources",
  extract: "Extracting claims",
  thinking: "AI reading the document",
  triage: "Sorting facts from commentary",
  triage_done: "Facts vs commentary sorted",
  check: "Checking claim",
  context: "Inferring subject",
  planning: "Planning web searches",
  readsrc: "Reading sources for claim clusters",
  readsrc_q: "Cluster search",
  readsrc_pages: "Reading pages in full",
  web: "Free web search",
  webpass_done: "Keyword web pass done",
  deepweb: "Sentence-level web check",
  heartbeat: "Deep checks in progress",
  deepdone: "Sentence-level check done",
  reuse: "Cross-proof from fetched evidence",
  pooljudge: "LLM re-judge vs fetched evidence",
  pooljudge_done: "Cross-proof done",
  reporting: "Writing report + annotated copy",
};

/* NEXT_PUBLIC_API_URL = the deployed backend (set in Vercel env at build
   time); same-origin when FastAPI serves web/out; dev on :3000 hits :8000 */
const API = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/$/, "") ||
  (typeof window !== "undefined" && window.location.port === "3000"
    ? "http://127.0.0.1:8000" : "");

function fmtVal(v) {
  if (typeof v !== "number") return v;
  return Math.abs(v) >= 1000 ? v.toLocaleString("en-US") : v;
}

/* wrap one paragraph's text in spans; records carry source_span {para,start,end} */
function renderParagraph(i, text, recs, active, selectedId, onPick) {
  const mine = recs
    .filter((r) => r.source_span && r.source_span.para === i && r.verdict)
    .sort((a, b) => a.source_span.start - b.source_span.start);
  const parts = [];
  let pos = 0;
  mine.forEach((r) => {
    const { start, end } = r.source_span;
    if (start < pos || end > text.length || text.slice(start, end) !== r.quote) return;
    if (start > pos) parts.push(text.slice(pos, start));
    const v = r.verdict;
    const dim = active && !active.has(v);
    parts.push(
      <mark
        key={r.claim_id}
        className={dim ? "hl dim" : "hl"}
        style={dim ? null : { background: VERDICTS[v]?.bg, boxShadow: `inset 0 -2px 0 ${VERDICTS[v]?.color}` }}
        title={r.notes || ""}
        onClick={() => onPick(r.claim_id)}
        data-sel={selectedId === r.claim_id ? "1" : undefined}
      >
        {text.slice(start, end)}
      </mark>
    );
    pos = end;
  });
  if (pos < text.length) parts.push(text.slice(pos));
  return <p key={i}>{parts}</p>;
}

export default function Home() {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState([]);
  const [report, setReport] = useState(null);
  const [err, setErr] = useState("");
  const [selected, setSelected] = useState(null);
  const [active, setActive] = useState(null); // Set of verdicts filter, null = all
  const fileRef = useRef(null);
  // Two distinct jobs, and the difference is who supplies the evidence:
  //   search -> the tool looks the claims up itself (web on)
  //   byos   -> the tool may ONLY use the sources the user uploaded (web off)
  // `web` is DERIVED from the mode instead of being hardcoded on. Leaving it
  // constant meant a BYOS run still went to the open web, which quietly
  // answers claims the user's own documents were supposed to be the sole
  // authority on -- the opposite of what uploading sources is for.
  const [mode, setMode] = useState("search");
  const web = mode === "search";
  const llm = true; // free tier, no user choice
  const [whitelist, setWhitelist] = useState("");
  const [engine, setEngine] = useState("deepseek"); // deepseek | brave
  const [backend, setBackend] = useState("unknown"); // ok | down
  const [quota, setQuota] = useState(null);
  const [files, setFiles] = useState([]); // {file, role: 'doc'|'source'|'alias'}
  const sourceCount = files.filter((f) => f.role === "source").length;
  const [decBusy, setDecBusy] = useState(false);
  const [lastEv, setLastEv] = useState(0);  // ts of last SSE event (liveness timer)
  const [now, setNow] = useState(0);
  const [jobId, setJobId] = useState(null); // live job (for Stop)
  const [stopping, setStopping] = useState(false);

  useEffect(() => {
    if (!busy) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [busy]);

  useEffect(() => {
    /* RESUME: a refresh drops the SSE stream but NOT the server-side run.
       If a check of mine is still going, re-attach: poll its report until
       done. (Without this, a refreshed tab could neither see nor stop the
       run — the 'hollow waiting' trap.) */
    let stop = false;
    const attach = async () => {
      try {
        const a = await (await fetch(`${API}/api/active`)).json();
        if (!a.job_id || stop) return;
        setJobId(a.job_id);
        setBusy(true);
        setLog((L) => [...L, { stage: "context", item: "re-attached to the check already running" }]);
        const tick = async () => {
          if (stop) return;
          setLastEv(Date.now());
          try {
            const rep = await (await fetch(`${API}/api/report/${a.job_id}`)).json();
            if (rep.status === "done") {
              setReport({ ...rep, job_id: a.job_id });
              setBusy(false);
              setJobId(null);
              return;
            }
          } catch { /* server mid-restart; keep polling */ }
          setTimeout(tick, 3000);
        };
        tick();
      } catch { /* backend offline; health banner already says so */ }
    };
    attach();
    return () => { stop = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    let stop = false;
    const ping = async () => {
      try {
        const r = await fetch(`${API}/api/health`);
        if (stop) return;
        if (!r.ok) { setBackend("down"); return; }
        const j = await r.json();
        setBackend("ok");
        if (j.quota) {
          setQuota(j.quota);
          if ((j.quota.brave_left || 0) <= 0) setEngine((e) => (e === "brave" ? "deepseek" : e));
        }
      } catch {
        if (!stop) setBackend("down");
      }
    };
    ping();
    const t = setInterval(ping, 5000);
    return () => { stop = true; clearInterval(t); };
  }, []);

  useEffect(() => {
    /* the whole page is a drop target: without this, dropping a file outside
       the dashed box makes the browser NAVIGATE to it (looks like "no slot") */
    const prevent = (e) => e.preventDefault();
    const onDrop = (e) => {
      e.preventDefault();
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length)
        addFiles(e.dataTransfer.files);
    };
    window.addEventListener("dragover", prevent);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragover", prevent);
      window.removeEventListener("drop", onDrop);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const counts = {};
  (report?.findings || []).forEach((r) => {
    if (r.verdict) counts[r.verdict] = (counts[r.verdict] || 0) + 1;
  });

  function addFiles(list) {
    const picked = [...list];
    setFiles((prev) => {
      const next = [...prev];
      for (const f of picked) {
        const ext = f.name.split(".").pop().toLowerCase();
        const isDocType = ["md", "txt", "docx"].includes(ext);
        const role = (!isDocType && ext === "csv" && !next.some((p) => p.role === "alias"))
          ? "alias"
          : isDocType && !next.some((p) => p.role === "doc") ? "doc" : "source";
        next.push({ file: f, role });
      }
      return next;
    });
  }

  function buildFd() {
    const fd = new FormData();
    const docFile = files.find((f) => f.role === "doc");
    if (text.trim() && !docFile) fd.append("text", text);
    if (docFile) fd.append("doc", docFile.file);
    files.filter((f) => f.role === "source").forEach((f) => fd.append("corpus", f.file));
    const aliasFile = files.find((f) => f.role === "alias");
    if (aliasFile) fd.append("names", aliasFile.file);
    fd.append("web", web ? "true" : "false");
    fd.append("llm", llm ? "true" : "false");
    fd.append("backend", engine);  // which search engine this run may use
    return fd;
  }

  function fmtDur(s) {
    return s >= 60 ? `${Math.floor(s / 60)}m ${(s % 60).toString().padStart(2, "0")}s` : `${s}s`;
  }

  async function check() {
    setBusy(true); setErr(""); setReport(null); setLog([]); setSelected(null);
    setActive(null);  // a leftover verdict filter from the last run dims the new report
    setJobId(null); setStopping(false);
    setLastEv(Date.now()); setNow(Date.now());
    const fd = buildFd();
    fd.append("whitelist", whitelist);
    // PREFLIGHT: ask the engine how long a FULL-DEPTH check takes, then let
    // the user decide before committing. Budgets scale with length — a long
    // document is slower, never skipped or shallow.
    if (web || llm) {
      try {
        const r = await fetch(`${API}/api/estimate`, {
          method: "POST",
          body: (() => { const f = buildFd(); return f; })(),
        });
        if (r.ok) {
          const e = await r.json();
          setLog((L) => [...L, { stage: "estimate", words: e.words, claims: e.need_web,
            lo: e.seconds_lo, hi: e.seconds_hi, typ: e.seconds_typ, cov: e.coverage_pct,
            plan: e.plan }]);
          const pl = e.plan || {};
          if (!window.confirm(
            `Job plan for ${e.words?.toLocaleString?.() ?? e.words} words ` +
            `(${e.need_web} claims need live checks):\n\n` +
            (web
              ? `  • ~${pl.searches} web searches (budget: up to 5-6/claim, spent only while a claim is unsettled)\n` +
                `  • ${pl.deep_checks} sentence-level deep checks — every claim\n` +
                `  • ${pl.pages} full-page deep-reads\n`
              : `  • NO web lookups — verdicts rest only on your ${sourceCount} uploaded source file${sourceCount === 1 ? "" : "s"}\n` +
                `  • ${pl.deep_checks} sentence-level source checks — every claim\n`) +
            `  • ${pl.llm_calls} LLM judgment calls\n\n` +
            `Estimated time: ~${fmtDur(pl.sec_typ ?? e.seconds_typ)} ` +
            `(usually ${fmtDur(e.seconds_lo)}–${fmtDur(e.seconds_hi)})\n` +
            `Full-depth coverage: ${e.coverage_pct}%` +
            (e.recommend ? `\n\nNote: ${e.recommend}` : "") +
            `\n\nStart?`)) {
            setBusy(false);
            return;
          }
        }
      } catch { /* preflight is optional; proceed to check anyway */ }
    }
    try {
      const res = await fetch(`${API}/api/check`, { method: "POST", body: fd });
      if (res.status === 409) {
        const j = await res.json().catch(() => ({}));
        if (j.running_job) setJobId(j.running_job);
        setErr(j.detail || "A check is already running for you.");
        setBusy(false);
        return;
      }
      if (res.status === 429) {
        const j = await res.json();
        setErr(`Quota: ${j.detail}`);
        setBusy(false);
        return;
      }
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.detail || `HTTP ${res.status}`);
      }
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const events = buf.split("\n\n");
        buf = events.pop();
        for (const raw of events) {
          const isDone = raw.startsWith("event: done");
          const line = raw.split("\n").find((l) => l.startsWith("data:"));
          if (!line) continue;
          const data = JSON.parse(line.slice(5));
          if (data.stage === "job") setJobId(data.job_id);
          if (isDone) {
            setReport(data);
          } else {
            setLastEv(Date.now());
            setLog((L) => [...L.slice(-1999), data]);
          }
        }
      }
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    if (!jobId || stopping) return;
    setStopping(true);
    try {
      await fetch(`${API}/api/cancel/${jobId}`, { method: "POST" });
    } catch { /* engine keeps running; retry */ }
    if (!busy) {
      /* stopped from the 409 path: stay attached so the partial report
         still lands here instead of vanishing server-side */
      const tick = async () => {
        try {
          const rep = await (await fetch(`${API}/api/report/${jobId}`)).json();
          if (rep.status === "done") {
            setReport({ ...rep, job_id: jobId });
            setJobId(null);
            setStopping(false);
            return;
          }
        } catch { /* keep polling */ }
        setTimeout(tick, 2000);
      };
      tick();
    } else {
      setStopping(false);
    }
  }

  const sel = report?.findings.find((r) => r.claim_id === selected);

  async function decide(decision) {
    if (!sel || decBusy) return;
    setDecBusy(true);
    setErr("");
    try {
      const r = await fetch(`${API}/api/decision/${report.job_id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ claim_id: sel.claim_id, decision }),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
      setReport((rep) => ({
        ...rep,
        findings: rep.findings.map((f) => (f.claim_id === sel.claim_id ? j.record : f)),
      }));
    } catch (e) {
      setErr(`Decision not saved: ${String(e.message || e)}`);
    } finally {
      setDecBusy(false);
    }
  }

  return (
    <main>
      <header>
        <div className="brand">
          Check<b>Mato</b>
          <span className="tag">free · open · evidence-first</span>
        </div>
        <div className="sub">
          Fact-check AI-written documents — every claim, line-precise evidence, nothing invented.
        </div>
        {quota && (
          <div className="sub" style={{ fontSize: 12 }}>
            {quota.enforced === false
              ? "no daily run limit on this instance (local / desktop build)"
              : `${quota.runs_left} run${quota.runs_left === 1 ? "" : "s"} left today`}
            {quota.brave_left > 0
              ? ` · Brave ${quota.brave_left}/${quota.brave_cap} this month`
              : " · Brave spent this month — DeepSeek Search"}
          </div>
        )}
      </header>

      {backend === "down" && (
        <div className="banner">
          <b>Backend offline.</b> The website is running, but the engine is not. Open a terminal in
          <code> CheckMato </code> and run
          <code> .venv\Scripts\python.exe -m uvicorn app.server:app --port 8000 </code>
          — or use <code>start.bat</code> to bring both up. This page retries every 5s.
        </div>
      )}

      <section className="card input">
        <div className="row" style={{ marginBottom: 10 }}>
          <span style={{ fontSize: 12, color: "#5b6770" }}>Mode</span>{" "}
          <div style={{ display: "inline-flex", gap: 4 }}>
            {[
              ["search", "Search the web", "The tool looks each claim up itself"],
              ["byos", "Check my own sources", "Only the files you upload are used"],
            ].map(([val, label, tip]) => (
              <button
                key={val}
                onClick={() => setMode(val)}
                disabled={busy}
                title={tip}
                style={{
                  fontSize: 12,
                  padding: "4px 10px",
                  cursor: busy ? "default" : "pointer",
                  borderRadius: 6,
                  border: `1px solid ${mode === val ? "#2c6f5e" : "#d7dee3"}`,
                  background: mode === val ? "#e6f2ec" : "#fff",
                  color: mode === val ? "#1f5346" : "#5b6770",
                  fontWeight: mode === val ? 600 : 400,
                }}
              >
                {label}
              </button>
            ))}
          </div>
          <span className="spacer" />
          <span style={{ fontSize: 12, color: "#7b8794" }}>
            {web ? "live lookups enabled" : "no internet lookups — offline against your files"}
          </span>
        </div>
        {mode === "byos" && (
          <div className="banner" style={{ marginBottom: 10 }}>
            <b>Bring your own sources.</b> Every verdict will rest only on the files you
            upload below &mdash; nothing is fetched from the web. Upload the text to check,
            then add the source documents (.md/.txt/.pdf/.docx/.csv) it should be judged
            against. Claims your sources do not cover stay <code>unverified</code>;
            they are never filled in from the open internet.
            {sourceCount === 0 && (
              <div style={{ marginTop: 6, fontWeight: 600 }}>
                No source files yet &mdash; without them there is nothing to check against,
                so every claim will come back unverified.
              </div>
            )}
          </div>
        )}
        <textarea
          placeholder={web
            ? "Paste your AI-drafted article / case study here… (or upload .docx/.md/.txt)"
            : "Paste the text to fact-check here… (then upload your source documents below)"}
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={7}
          disabled={busy}
        />
        <div className="dropzone"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => { e.preventDefault(); addFiles(e.dataTransfer.files); }}
          onClick={() => fileRef.current?.click()}>
          <input ref={fileRef} type="file" hidden multiple
            accept=".md,.txt,.docx,.pdf,.csv"
            onChange={(e) => addFiles(e.target.files)} />
            {files.length === 0 ? "Drop files or click: the document to check (.md/.txt/.docx), your source books/reports (.pdf too), an optional aliases .csv — roles auto-detected, adjust below" : "click to add more files"}
        </div>
        {files.length > 0 && (
          <div className="filelist">
            {files.map((f, i) => (
              <span key={i} className="fpill">
                {f.file.name}
                <select value={f.role} onChange={(e) => setFiles((prev) =>
                  prev.map((p, j) => (j === i ? { ...p, role: e.target.value } : p)))}>
                  <option value="doc">document</option>
                  <option value="source">source</option>
                  <option value="alias">aliases</option>
                </select>
                <button className="x" onClick={() =>
                  setFiles((prev) => prev.filter((_, j) => j !== i))}>×</button>
              </span>
            ))}
          </div>
        )}
        <div className="row">
          {web ? (
            <>
              <span style={{ fontSize: 12, color: "#5b6770" }}>Search</span>{" "}
              <select
                style={{ fontSize: 12, padding: "2px 6px", border: "1px solid #d7dee3", borderRadius: 6 }}
                value={engine}
                onChange={(e) => setEngine(e.target.value)}
                title="DeepSeek Search (in-house index, DEEPSEEK_API_KEY) or Brave (monthly free credit)"
              >
                <option value="deepseek">DeepSeek Search</option>
                <option value="brave" disabled={quota && quota.brave_left <= 0}>
                  {quota && quota.brave_left <= 0 ? "Brave only (spent this month)" : "Brave only"}
                </option>
              </select>
            </>
          ) : (
            <span style={{ fontSize: 12, color: "#5b6770" }}>
              Sources: <b>{sourceCount}</b> file{sourceCount === 1 ? "" : "s"}
            </span>
          )}
          <span className="spacer" />
          <input
            className="wl"
            placeholder="site whitelist, e.g. reuters.com,gov.cn"
            value={whitelist}
            onChange={(e) => setWhitelist(e.target.value)}
            disabled={!web}
            title={web ? "Only accept evidence from these domains" : "Web lookups are off in this mode"}
          />
          <button className="go" onClick={check} disabled={busy || (!text.trim() && !files.some((f) => f.role === "doc"))}>
            {busy ? "Checking…" : "Check document"}
          </button>
        </div>
        {err && <div className="err">{err}</div>}
        {jobId && !report && (
          <div className="row">
            <span style={{ fontSize: 12, color: "#7b8794" }}>
              A check is running server-side — its report will appear here when done.
            </span>
            <span className="spacer" />
            <button className="stopbtn" onClick={stop} disabled={stopping}>
              {stopping ? "stopping…" : "■ stop it"}
            </button>
          </div>
        )}
      </section>

      {log.length > 0 && (() => {
        const total = log.find((e) => e.stage === "extract")?.claims || 0;
        const est = log.find((e) => e.stage === "estimate");
        const need = est?.claims || total;
        const checks = log.filter((e) => e.stage === "check").length;
        const webIds = new Set(log.filter((e) => e.stage === "web" && e.id).map((e) => e.id));
        const webpassDone = log.some((e) => e.stage === "webpass_done");
        const lastDeep = [...log].reverse().find((e) => e.stage === "deepdone");
        const deepTotal = lastDeep?.total ?? est?.plan?.deep_checks ?? 0;
        const deepStarted = new Set(log.filter((e) => e.stage === "deepweb" && e.id).map((e) => e.id)).size;
        const deepFrac = deepTotal ? Math.min(1, Math.max(lastDeep?.done || 0, deepStarted) / deepTotal) : 0;
        // (deepFrac kept for older runs' replay; new runs drive readFrac below)
        const thinking = [...log].reverse().find((e) => e.stage === "thinking" && e.batches);
        const thinkFrac = thinking ? Math.min(1, (thinking.done || 0) / (thinking.batches || 1)) : 0;
        const planning = [...log].reverse().find((e) => e.stage === "planning");
        const planFrac = planning ? Math.min(1, (planning.done || 0) / (planning.batches || 1)) : 0;
        const readsrc = [...log].reverse().find((e) => e.stage === "readsrc");
        const readFrac = readsrc ? Math.min(1, (readsrc.done || 0) / (readsrc.batches || 1)) : 0;
        const crossDone = log.some((e) => e.stage === "pooljudge_done");
        const crossOn = crossDone || log.some((e) => ["pooljudge", "reuse"].includes(e.stage));
        const triDone = log.some((e) => e.stage === "triage_done");
        const triOn = triDone || log.some((e) => e.stage === "triage");
        const reporting = log.some((e) => e.stage === "reporting");
        let p;
        if (!total) p = 0;
        else if (!est && !webpassDone && !deepTotal && !planning) {
          /* offline run: the deterministic check sweep IS the work */
          p = Math.min(1, checks / total) * 0.9 + (reporting ? 0.09 : 0);
        } else {
          /* weighted by WHERE TIME ACTUALLY GOES: the keyword pass is fast
             (many claims reserved for the deep pass), the sentence-level deep
             checks are the long pole (~2/3 of a real run), not 6% */
          p = Math.min(1, checks / total) * 0.18
            + (llm ? thinkFrac * 0.07 : 0)
            + (triDone ? 0.03 : triOn ? 0.015 : 0)
            + planFrac * 0.05
            + (webpassDone || webIds.size >= need ? 0.08
               : (need ? webIds.size / need : 0) * 0.08)
            + readFrac * 0.39
            + (crossDone ? 0.08 : crossOn ? 0.04 : 0)
            + (reporting ? 0.02 : 0);
        }
        const pct = report ? 100 : Math.min(99, Math.round(p * 100));
        const cur = [...log].reverse().find((e) =>
          ["thinking", "triage", "triage_done", "planning", "check", "web",
            "webpass_done", "readsrc", "readsrc_q", "readsrc_pages",
            "heartbeat", "reuse", "pooljudge", "pooljudge_done",
            "context", "corpus", "parse", "reporting"].includes(e.stage));
        const msg = cur ? (STAGE_LABEL[cur.stage] || cur.stage) : "Working";
        const detail = cur ? (cur.item || cur.claims || "") : "";
        const idleS = busy && lastEv ? Math.max(0, Math.round((now - lastEv) / 1000)) : 0;
        return (
          <section className="card nowline">
            <div className="nowstatus">
              <span className="pulse" />
              <span key={log.length} className="fading" style={{ whiteSpace: "normal" }}>
                {msg}{detail ? `: ${String(detail).slice(0, 200)}` : ""}
              </span>
              {idleS >= 3 && <span className="elapsed">still working · {idleS}s on this step</span>}
              {total ? <b className="pctnum">{pct}%</b> : null}
              {busy && jobId ? (
                <button className="stopbtn" onClick={stop} disabled={stopping}>
                  {stopping ? "stopping…" : "■ stop"}
                </button>
              ) : null}
            </div>
            {total ? (
              <div className="bar"><i style={{ width: `${pct}%` }} /></div>
            ) : null}
            <details className="chaingen">
              <summary>details ({log.length} steps)</summary>
              <ul className="chainlist">
                {log.slice(-40).map((e, i) => (
                  <li key={i}>
                    <span className="stage">{STAGE_LABEL[e.stage] || e.stage}</span>{" "}
                    {e.stage === "estimate" ? (
                      <em>{e.words?.toLocaleString?.()} words · {e.claims} claims · plan: {e.plan?.searches} searches, {e.plan?.deep_checks} deep checks · ~{fmtDur(e.typ)}</em>
                    ) : (
                      <>{e.id ? <code>{e.id}</code> : null} {e.item ? <em>{String(e.item).slice(0, 140)}</em> : null}
                      {e.used != null ? <span className="budget"> [{e.budget ? `${e.used}/${e.budget}` : e.used}]</span> : null}</>
                    )}
                  </li>
                ))}
              </ul>
            </details>
          </section>
        );
      })()}

      {report && (
        <>
          {report.meta?.cancelled && (
            <div className="banner"><b>Cancelled — partial results.</b> Everything
              already checked is shown; unchecked items say so. You can re-run anytime.</div>
          )}
          {report.meta?.free_tier && (
            <div className="banner"><b>Free tier:</b> web search is capped at{" "}
              {report.meta.free_tier_search_cap || 40} requests per document.
              Claims reached after the cap are marked <b>Not checked</b>, not
              &quot;checked, not found&quot;.</div>
          )}
          {report.meta?.coverage && (
            <section className="coverage" aria-label="Run coverage">
              {[
                ["supported", "Supported", "ok"],
                ["checked_not_found", "Checked, not found", "info"],
                ["not_checked", "Not checked", "warn"],
                ["no_source", "No source", "warn"],
                ["not_checkable", "Not checkable", ""],
                ["needs_attention", "Needs attention", "warn"],
                ["conflicting", "Conflicting", "warn"],
                ["structure", "Structure", ""],
              ].filter(([k]) => report.meta.coverage[k] != null).map(([k, label, tone]) => (
                <div key={k} className={`cov ${tone}`}>
                  <b>{report.meta.coverage[k] ?? 0}</b>
                  <span>{label}</span>
                </div>
              ))}
            </section>
          )}
          <section className="chips">
            {Object.entries(VERDICTS).filter(([v]) => counts[v]).map(([v, meta]) => (
              <button
                key={v}
                className={"chip" + (active && !active.has(v) ? " off" : active ? " on" : "")}
                style={{ borderColor: meta.color, color: meta.color,
                         background: active && active.has(v) ? meta.color : undefined }}
                onClick={() =>
                  setActive((a) => (!a || !a.has(v) || a.size > 1 ? new Set([v]) : null))
                }
              >
                {meta.label} <b>{counts[v]}</b>
              </button>
            ))}
            <button className="chip" onClick={() => setActive(null)}>all</button>
            <span className="spacer" />
            {["md", "xlsx", "jsonl"].map((k) => (
              <a key={k} className="dl" href={`${API}/api/export/${report.job_id}/${k}`}>
                download {k}
              </a>
            ))}
          </section>

          <section className="split">
            <article className="card doc">
              {report.meta?.paragraphs?.map((para, i) =>
                renderParagraph(i, para, report.findings, active, selected, setSelected)
              )}
            </article>
            <aside className="card detail">
              {!sel && <p className="hint">Click a highlighted span to see its evidence, source and suggested fix.</p>}
              {sel && (
                <div>
                  <div className="badge" style={{ background: VERDICTS[sel.verdict]?.bg, color: VERDICTS[sel.verdict]?.color }}>
                    {VERDICTS[sel.verdict]?.label} · {sel.confidence}
                  </div>
                  <blockquote>{sel.quote}</blockquote>
                  {sel.notes && <p className="notes">{sel.notes}</p>}
                  {sel.search_suggestions?.length > 0 && (
                    <div className="suggests">
                      <p className="hint">Search this yourself:</p>
                      {sel.search_suggestions.map((q, i) => (
                        <a key={i} className="sug" target="_blank" rel="noreferrer"
                           title="Open this query in a search engine"
                           href={"https://www.google.com/search?q=" + encodeURIComponent(q)}>
                          {q}
                        </a>
                      ))}
                    </div>
                  )}
                  <ul className="ev">
                    {sel.evidence.map((e, i) => (
                      <li key={i}>
                        <span className={"kind " + e.kind}>[{e.kind.toUpperCase()}]</span>{" "}
                        {e.side && <span className={"side " + e.side}>{e.side === "support" ? "SUPPORTS" : "AGAINST"}</span>}{" "}
                        {e.kind === "web" || e.kind === "fx" ? (
                          <a href={e.ref} target="_blank" rel="noreferrer">{e.ref}</a>
                        ) : (
                          <code>{e.ref}</code>
                        )}
                        <div className="evq">“{e.quote}”</div>
                      </li>
                    ))}
                  </ul>
                  <p className="status">status: {sel.status}</p>
                  {sel.verdict === "conflicting" && (
                    <div className="decide">
                      <p><b>Sources disagree</b> — the engine will not pick a side.
                        Open the evidence and decide:</p>
                      <div className="drow">
                        <button className="dkeep" onClick={() => decide("keep")} disabled={decBusy}>
                          ✓ claim stands
                        </button>
                        <button className="dfix" onClick={() => decide("fix")} disabled={decBusy}>
                          ✎ fix the document
                        </button>
                        <button className="ddismiss" onClick={() => decide("dismiss")} disabled={decBusy}>
                          ✕ dismiss flag
                        </button>
                      </div>
                      <p className="dnote">saved with the job and written into every export</p>
                    </div>
                  )}
                </div>
              )}
              {Object.values(report.meta?.timelines || {}).some((t) => Object.keys(t).length) > 0 && (
                <details className="tl">
                  <summary>Timelines</summary>
                  {Object.entries(report.meta.timelines).filter(([, t]) => Object.keys(t).length).map(([ent, t]) => (
                    <div key={ent}><b>{ent}</b>: {Object.entries(t).map(([ev, yrs]) => `${ev} ${Math.min(...Object.keys(yrs))}${new Set(Object.keys(yrs)).size > 1 ? "–" + Math.max(...Object.keys(yrs)) : ""}`).join(" · ")}</div>
                  ))}
                </details>
              )}
            </aside>
          </section>
        </>
      )}

      <footer>
        verdicts reflect the evidence shown — “unverified” means not found in provided
        sources, not false · all functions free; limits are budgets, never paywalls
      </footer>
    </main>
  );
}
