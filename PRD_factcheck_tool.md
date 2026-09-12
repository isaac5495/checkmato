# PRD — CheckMato: AI Hallucination & Fact-Check Tool for Documents

- Version: 0.7 (M1.6–M1.8 2026-09-06: user rulings on `conflicting`, `narrative` eligibility,
  source-cluster deep reads, official free-tier search lanes, run safety rails; deployment pending)
- Date: 2026-09-06
- Owner: you
- Positioning: **public, all-functions-free web tool** — limits are quotas, never paywalls
- Living "what is true now" doc: `HANDOFF.md` (ops + invariants); this PRD is the spec.

---

## 1. Problem

Documents increasingly start as AI drafts. AI text has "deceptive coherence": it reads well but
invents precise details — wrong years, wrong FX-converted figures, paraphrases dressed as verbatim
quotes, quotes attributed to the wrong person, footnotes attached to the wrong claim. General AI
chat tools either refuse to verify ("I can't browse…") or fabricate verification. Existing products
(Manus, Originality.ai, Facticity) are either expensive agents with opaque credit burn,
AI-detection-first with fact-check as a bolt-on, or tied to crypto/Web3 features. None of them
check **document-internal integrity** (footnote anchoring, timeline consistency, EN/ZH version
drift) and none show **line-precise evidence**.

## 2. Why we can win (unfair advantages from the KS project)

1. **Labeled eval set**: 89 verified sentences (`pipeline/footnotes_suggested.md`) + 76-footnote
   verdict table (`FOOTNOTE_VERIFICATION.md`) + 54 confirmed AI-hallucination fixes
   (`v9_corrections_plan.md`). ~130 input→ground-truth pairs, human-verified, in exactly the
   target genre (business case studies, EN/ZH).
2. **Hallucination taxonomy** proven in practice: number/FX errors, wrong names, fake verbatim
   quotes, misattributed quotes, mis-anchored footnotes, unsupported quotes with no source,
   timeline contradictions, book-only facts presented as public.
3. **Evidence schema already battle-tested**: claim quote + verdict + `[WEB]`(URL) / `[LOCAL]`
   (file:line) provenance + citation-precision rule (line ≥ chapter ≥ page) + "Open items"
   honest-unknown bucket + dual output (short verdict sheet + detailed md).
4. **Structural checkers** no competitor has: footnote anchor integrity, reference counting,
   cross-language (EN/ZH) same-anchor verification — deterministic, zero LLM cost.

## 3. Goals / Non-goals

### Goals (v1 public product)
- G1: User uploads a document (or pastes text, or gives a URL) → gets a claim-by-claim verification
  report with clickable evidence, in under ~5 min for a 20-page doc.
- G2: Report distinguishes the full verdict set (as-built): `supported` / `contradicted` /
  `unverified` / `internal_conflict`, plus `paraphrase_flag`, `misattributed` (real quote,
  wrong speaker), `needs_fix` (placeholders, dead links), `structure` (footnote/timeline
  defects) and `deferred_web` (budget-exhausted items) — never asserts truth beyond the
  evidence it shows.
- G3: "Bring your own sources" (BYOS): user supplies source files (PDF/MD/TXT books, reports);
  tool indexes them and prefers local line-precise evidence over web guesses. (This is the KS
  workflow generalized. As-built: corpus ingests .md/.txt/.csv (line precision; UTF-8 first,
  then charset-normalizer sniffing for GBK/Big5/latin-1, lossy fallback), .pdf via
  PyMuPDF (page precision, `book.pdf p.N:line`), .docx via python-docx (paragraph precision);
  PDF text layers only — OCR is out of scope. Scale guards: inverted token index (search is
  O(matching lines), not O(corpus)), 40 MB/file and 200k-line/file caps, evidence quotes
  clipped at ~280 chars with an explicit `…[line clipped]` marker, xlsx cells hard-capped.)
- G4: **$0-to-operate by design** ("free at our max effort"): free-tier LLMs (Gemini Flash / Groq),
  keyless search (ddgs / self-hosted SearXNG), free self-hosting (Oracle Cloud Always Free);
  hard per-run budgets + daily quotas so traffic spikes can never create a bill.
- G5: EN + ZH documents; report language follows document language.

### Non-goals (v1)
- N1: Image/video verification (TinEye/InVID territory).
- N2: Political claim rating / "Truth-O-Meter" style public ratings — we verify documents, we don't
  publish verdicts on people.
- N3: AI-generated-text detection (avoids Originality's false-positive battlefield entirely).
- N4: Browser extension, mobile app, public API.
- N5: Real-time collaborative editing.

## 4. Users & personas

| Persona | Job | KS-project analog |
|---|---|---|
| P1 Case writer / editor (academic publishing) | fact-check case studies, footnotes, quotes | you, right now |
| P2 Student with AI-drafted long paper | catch hallucinations before submission | dogfood tier |
| P3 Content team / newsletter editor | pre-publication scan of URLs/pastes | free-acquisition tier |
| P4 Translator / bilingual publisher | verify EN↔ZH versions carry same facts, same quotes | v8 EN/ZH cross-check workflow |

P1/P4 are the paid core. P2/P3 are the funnel.

## 5. Core loop (user story)

1. User drops `kingsoft_case.docx`, optionally adds 3 source books as PDFs (BYOS).
2. Tool parses → extracts claims → user sees claim count + estimated time/credits → confirms.
3. Agent works with live progress (SSE): "Checking: 腾讯 became largest shareholder at 15.68%…
   found HKEX announcement 2011-07-06 → matched".
4. Report: document view with inline highlights (contradicted = red, unverified = amber,
   supported = green) + right panel: evidence, source links/line refs, suggested fix.
5. User accepts/dismisses each item; exports report as MD / XLSX / annotated DOCX; re-runs after fixes.

## 6. Functional requirements

### MVP (M1–M2 below)
- F1 Inputs: `.docx` / `.md` / `.txt` upload (≤ 30k words) and pasted text. **DOCX is walked in
  document order and flattened**: table rows become `cell | cell` lines, text boxes and
  footnote/endnote text are collected too — a python-docx `.paragraphs` read silently misses
  ~30% of a real case study (and Word counts it all: `textproc.count_words` matches MS-Word's
  rule, CJK char = 1 word). **Live-URL import is deferred to M2** — scraping fragility (paywalls,
  JS pages) is the worst support cost for a $0 volunteer-staffed product. (This is about accepting
  a URL as *input to check*; the report always shows evidence URLs.)
- F2 Claim extraction (as-built two layers + sentence floor): a **deterministic regex floor**
  always runs (years, amounts incl. EN/ZH units 亿/万/billion…, percents, counts incl. spelled
  ages "was only twenty-four" and identifiers "room 501", quoted speech, placeholders, URLs,
  footnote markers); **every sentence containing no extractable figure becomes one narrative
  claim** (`origin:"sentence"`, type `event`) so statements like "WPS was a word processor" are
  checked like everything else — no sentence escapes silently; an **optional LLM layer** proposes
  extra digit-free semantic claims (`type: year|quote|amount|pct|count|placeholder|url|name|event|citation|timeline|fx`,
  anchor `{para, span}`) with an anti-hallucination guard: an LLM-proposed claim is
  dropped unless its text is found verbatim in the document. Recall on seeded
  hallucinations ≥ 80% (measured on golden set; current: 100% on the 14-case synthetic set).
- F3 Structural checks (deterministic, always run, no LLM):
  - footnote reference ↔ definition pairing, count, orphan/mis-anchored candidates;
    footnote URLs also get liveness probes (the only footnote content that is checked);
  - timeline builder (as-built): per-entity milestone table via event anchors
    (founding/IPO/launch/funding/acquisition/shutdown); same entity + same event with
    different years → `internal_conflict`; full timelines printed in the report;
  - internal number conflicts — deliberately conservative after false-positive audits on a
    real case study (an old union-find chain turned a revenue table into 95 fake conflicts):
    **no transitive chaining** (every member must share ≥2 non-stopword, non-name,
    non-unit words directly with the anchor claim); amounts conflict only **within the
    same currency**; years conflict only for the **same milestone event**; identifier
    figures (room/suite/floor/version) never participate; **a time series is not a
    contradiction** ("revenue in 2011: X" vs "in 2012: Y" — disjoint year contexts never link);
    modifier-aware ("over 90%" vs 95% is agreement, not conflict);
  - URL liveness + title match for existing citations.
- F4 Evidence search (as-built priority BYOS grep > web > LLM-over-snippets), per claim:
  (a) BYOS corpus exact/fuzzy grep first (`file:line` evidence);
  (b) free keyless web: **two backends in order** — ddgs (DuckDuckGo) then optional
  self-hosted **SearXNG** (Google/Bing/DDG aggregate, localhost-only container, JSON API)
  which also covers empty-lapses; query ladder ≤3 variants in **reading order**
  (`rare_phrase`, never sorted token-bags); **early-stop rule**: a variant is tried ONLY
  when the previous query returned zero results — results that don't match are information
  (more queries per claim measurably produced false conflicts); narrative/sentence claims
  get topic-phrase probes only, **prose is never quoted verbatim into a search**; only real
  quoted text is searched as `""`;
  **Entity-anchoring rule:** a web snippet may only confirm/contradict a number claim if it
  names one of the document's entities; quotes at ≥90% windowed similarity.
  **Contradiction has a higher bar than support:** same event OR ≥3 shared non-name,
  non-unit-noise words; a currency-less figure never overturns a revenue claim; modifier
  aware ("over/approx" phrasings).
  **Snippet reuse:** every snippet fetched this run is pooled; a second pass re-matches
  the pool against still-unverified claims (one source proves many claims — same strict
  guards, zero extra budget);
  (c) full-page **deep-read**: promising-but-inconclusive pages are fetched (bounded,
  cached, wall-clock-safe), entity/value sentence-windows are re-assessed with the same
  guards → evidence precision `passage`;
  (d) FX/number verification: adjacent conversion pairs ("HK$189M (about US$24.3M)") are
  tagged BEFORE web runs — the restated figure is exempted from standalone web judging
  (today's rate ≠ 1990's rate manufactured fake conflicts) — and settled arithmetically
  against frankfurter.app/ECB (≥1999) or a curated PBoC/IMF official annual-average table
  (1978–1998, provenance shown); when no rate exists the pair is explained, never web-contradicted.
- F4b LLM evidence layer (optional, degrades silently): batched **planned natural-language
  queries** (≤24 claims/call, incl. translation into the subject's origin language —
  Chinese sources proving English claims), per-claim judge over fetched snippets (must cite),
  and a **pool re-judge**: every still-unverified claim re-checked against the whole snippet
  pool of the run in batches of 22 — a claim is only settled if the "proof" appears
  **verbatim inside the cited snippet** (outside-knowledge guard).
- F5 Verdict engine: no evidence → `unverified`; evidence conflicts → `contradicted`
  (must show both); quote similarity via **windowed** match against the best corpus/snippet
  line (so attribution prefixes don't dilute it): ≥98% verbatim → `supported`,
  62–98% → `paraphrase_flag` ("possible paraphrase/fabrication"); an LLM may upgrade
  a verdict only by citing a raw evidence snippet it was shown. Two additional rules
  (as-built): **misattribution** — a quote that matches a source verbatim but whose
  speaker (`X said` / `X说：「…」`, EN or ZH) differs from the source's speaker →
  `misattributed`; **currency mismatch** — the identical figure stated in a different
  currency than the source (e.g. doc `1.89亿元` vs source `1.89亿港元`) → `contradicted`.
  Evidence carries a **credibility tier** (`published` / `open-community`); when a web
  `supported` rests only on Wikipedia/百度百科-class sources the note explicitly says
  *corroborate with primary/scholarly sources for academic use* (up to 3 independent
  sources are attached per verdict when found).
- F5b No-silent-unverified rule: every claim that ends unverified states WHY (searched
  without match / not searched: cap, budget, citation, LLM-off) **and** gives 1–2
  ready-to-paste hand-search queries (planned queries if they exist, else entity +
  reading-order phrases) — in `suggestion` text and as `search_suggestions` in §7.
- F6 Report UI: **preflight plan** — `POST /api/estimate` (free, no quota) returns this
  document's plan (searches / deep checks / page reads / LLM calls / time range /
  coverage %) and the run starts only after the user confirms; web+LLM toggles default ON.
  Live progress is **one line** (pulsing dot, fading current activity, % bar) — the full
  event chain sits behind a collapsed "details" — with heartbeat events during LLM phases
  so it never looks frozen. Highlighted document view (spans = claims; narrative claims
  color whole sentences), verdict filter chips, click → evidence cards (tier, precision
  snippet/passage/line, up to 3 sources), accept/dismiss per item. **Data contract already
  met by the engine (foundation work):** every claim carries exact, validated character
  anchors (`source_span` slices its paragraph verbatim; `anchored:true` on 100% of
  deterministic claims in both suites) so the frontend only wraps spans in `<mark>` —
  no re-searching.
- F7 Exports: detailed `report.md` + summary `report.xlsx` (the exact two-format convention of this
  project) + annotated `.docx` (tracked-change-style suggestions, never silent edits).
- F8 Quotas (everything free, as loose as the $0 budget allows): no sign-up to try — guest runs
  1 doc/day (IP-based); free email account = 10 docs/day + saved history + BYOS libraries.
  **Per-run budgets are a PLAN, not a fixed cap**: the preflight sizes searches/pages/deep
  checks/LLM calls to the document's claim count (≈5.6 searches per claim available, early-stop
  means typical consumption is ~half), cfg values act as floors, wall-clock ceilings are derived
  from the plan as runaway guards — never deadlines that cut depth. A doc whose full plan won't
  fit is reported with coverage % and a split recommendation, honestly, before starting.
  No feature is ever paywalled; if money is ever needed it buys *more
  quota*, not access (§9).
- F9 Bilingual: ZH docs use ZH search sources (gov.cn, 官方公告, 財新 etc. whitelist) + s2t/t2s
  normalization for quote matching (OpenCC, already in stack).

- F10 Name layer (as-built, optional `--names` alias file: CSV `en,zh,note` or
  `A = B` lines): (a) cross-script BYOS — an EN claim finds ZH evidence via alias
  token expansion (E17: "Lingxi engine 2015" ← `灵犀引擎于2015年发布`); (b) name-drift
  detection inside one doc (`X said / Y said` near-identical statements, X,Y not
  aliases → `needs_fix`, the 老王→小王 class); (c) dual-version compare CLI
  (`checkmato diff a.md b.md --names g.csv`) using language-neutral fact sets
  (values + alias-canonical names + URLs): same-kind near-miss values → drift pair,
  one-sided facts → drift, with raw entities deliberately excluded cross-script
  (avoids Hangzhou≠杭州 false drift). Quote wording is never diffed across languages.
- F11 Config (`checkmato.toml`, see `.example`): budgets, FX tolerance, quote cuts,
  LLM caps, default whitelist — no redeploy to tune; CLI flags override.

### v2
- BYOS vector fallback when grep misses; paragraph-aligned (vs today's fact-set) dual-version
  diff; browser extension; API; team workspaces; public citation DB integrations
  (Wikiquote, HKEX, SEC EDGAR).

## 7. Data & evidence schema (contract for dev + report + eval)

```json
{
  "claim_id": "c037",
  "source_span": {"para": 95, "start": 212, "end": 298},
  "quote": "Tencent became Kingsoft's largest shareholder at 15.68%",
  "context": "…the full sentence containing the claim…",
  "type": "amount",
  "verdict": "supported",
  "confidence": "high",
  "evidence": [
    {"kind": "web", "ref": "https://static.www.tencent.com/...pdf",
     "quote": "求伯君与张旋龙转让共计15.68%股权予腾讯", "precision": "primary_source"},
    {"kind": "local", "ref": "生生不息.md:882", "quote": "...", "precision": "line"},
    {"kind": "fx", "ref": "frankfurter.app 2011-12-28 USD->HKD",
     "quote": "HK$189M = US$24.3M implies 7.78; official 7.76 (dev 0.2%)",
     "precision": "primary_source"}
  ],
  "notes": "22.89% is voting-rights, not direct holding — wording nuance flagged",
  "search_suggestions": ["Qiu Bojun WPS 1989 release baike", "求伯君 WPS 1989 发布"],
  "status": "pending_user_review"
}
```

Precision ladder enforced: `primary_source > line > chapter > page > passage > snippet > bare citation`.
Evidence items may carry `tier: "published" | "open-community"` (Wikipedia/百度百科-class)
and `side: "support" | "contradict"` (present on both camps of a `conflicting` verdict).
**Verdict enum:** `supported · contradicted · conflicting · internal_conflict · paraphrase_flag ·
misattributed · needs_fix · structure · deferred_web · unverified · narrative · supported_pending_context` —
`conflicting` = sources disagree; engine shows both camps, user rules (keep/fix/dismiss via
`POST /api/decision/{job}`, persisted + re-rendered into all exports); `narrative` =
heading/question/commentary — visible with reason, never searched, never counted pending.
`status` becomes `decided:keep|fix|dismiss` (+ optional `user_note`) once the user rules.

## 8. Architecture (as-built; single-process local deploy works end-to-end)

```
Next.js static export (web/out) — served by the same process, no separate node server
   │ SSE: estimate → live progress line → done(records)   [built, incl. plan-confirm dialog]
FastAPI (app/server.py): /api/health /estimate /check(SSE) /report /export — IP quotas
   │ job dirs under %TEMP%/checkmato_jobs (transient; persistent store = deployment item)
Check pipeline (plain Python, zero paid services):
   read_doc (docx flattened: body order + tables + text boxes + notes)
   → extract (regex floor + sentence claims) → [optional LLM semantic claims, verbatim-guarded]
   → structural_checks → citation/FX-pair tagging
   → PLAN (app/estimate.py: per-doc budgets + time quote; approve-before-run)
    → BYOS corpus grep → token web ladder (numbers judged deterministically here, incl.
      compact entity·figure rungs) → SOURCE-LED DEEP PASS: cluster the rest by shared
      entities/vocab → 1–3 human-shaped queries per cluster (native script + exact
      figures) → deep-read ≤3 pages once → figures judged vs full-page passages, prose
      in ONE batched judge call/cluster (verbatim-quote guard)
    (search chain: Google CSE [closed to new signup] → Brave key → ddgs [region-pinned]
      → local SearXNG [pinned engines] → Wikipedia API; subject-anchor gate rejects
      geo-poisoned result sets; 429 backoff; transient+persistent circuit breakers)
    → snippet-pool reuse → LLM pool re-judge (backstop) → FX recompute
    → judge (conservative verdicts; modifiers, tiers; LLM "contradicted" always
      demoted to `conflicting` — only deterministic guards may contradict)
    → report nodes
    → exports: report.md, report.xlsx, claims.jsonl (the §7 contract), annotated.{docx,md},
      decisions.json
LLM: optional provider abstraction over free tiers (Gemini/Groq/OpenAI-compatible/Agnes),
keys via .env only (never chat/prompt), plan-scaled call/token/time budgets (ALL budgets
derive from the document; a static token ceiling once starved deep passes silently);
every call hard-capped 90 s wall-clock incl. retries; semantic scan chunked per 10 ¶;
prose triage → `narrative` eligibility. Degrade honest.
Search: keyless ddgs + optional SearXNG (deploy/searxng docker-compose, localhost-bound,
JSON via mounted settings.yml, engines pinned "bing,mojeek" — captcha'd engines crash
the combined response) + Wikipedia search API; official free-tier API keys (Brave live;
Google CSE wired but unobtainable for new projects) auto-take first place when present.
Safety rails: one live run per visitor IP (409), refresh re-attaches (`/api/active`),
cooperative Stop (`/api/cancel/{job}` → partial report labelled "cancelled").
```

All components have existing analogs in `pipeline/` (docx dumpers, footnote counters, openpyxl
writer, pandoc build, verify loops) — migration, not invention.

## 9. Free-first model (no paywalls)

**Every function is free at launch.** Limitations exist only because the $0 infra has finite
free-tier ceilings — they are *quotas*, not *plans*.

| | Guest (no account) | Free account |
|---|---|---|
| Runs | 1 doc / day | 10 docs / day |
| Word cap | 10k | 30k |
| Inputs | paste text | + file upload, BYOS libraries |
| Footnote/structural checks | ✓ | ✓ |
| Exports | report.md | + xlsx, annotated docx, archive |

Mechanics:
- Daily **global** budget across all users (e.g., 500 LLM jobs, 5k searches); when exhausted, new
  runs queue to the next day with honest messaging — degradation, never surprise cost.
- Per-run budget = **the document's approved plan** (see F8): sized by claim count, early-stop
  keeps actual use ~half of the quote; wall-clock ceilings are runaway guards only. Partial
  report still labeled "incomplete — resume".
- Structural-only "degraded mode" (deterministic checks + BYOS grep, no web) keeps the tool useful
  even when every external free tier is tapped out.
- Later, if traffic justifies paid keys, monetization stays quota-based (more runs/faster = Pro or
  sponsorship/donation); core verification + evidence view remain free. Decision deferred until
  real usage data — do not build billing now.

## 10. Privacy & legal

- Uploads are processed then auto-deleted (default 30 days; free tier 7). Never trained on.
- BYOS files are user-provided sources — stored only in user workspace, deletable per file.
- Verdict wording = "evidence found / not found / conflicts", not defamation ("lie", "fake").
  Legal review before launch (verdicts about living people's quotes).
- KS project data (books, interviews, transcripts) stays local and is **not** part of the product
  corpus — the eval harness runs offline on the owner's machine; no public KS-case marketing.

## 11. Success metrics

**Eval — two tiers (as-built):**
- **Tier A (ships in repo, offline, deterministic):** golden sets, one per language —
  EN: `tests/case_ai_draft.md` + `tests/corpus/` (md + PDF source) + 16 seeded findings
  (wrong years, wrong amounts, fake/embellished/misattributed quotes, verbatim quotes
  EN+ZH-across-script, count conflict, currency mismatch, placeholder, orphan footnote,
  FX-correct, FX-wrong, timeline collision, PDF-page evidence).
  ZH: `tests/case_zh.md` + `tests/corpus_zh/` + 7 seeded findings (same taxonomy,
  full-simplified pipeline incl. `。`-splitting, CJK counters 名/人/位, `「」` quotes).
  `tests/run_eval.py` gates every change: **current 100% recall / 100% precision on both
  suites**. No network in this tier (FX rates injected). Plus **foundation gates**:
  §7 contract on every record; 100% exact anchors (UI-highlight contract);
  `tests/test_units.py` (≈59 assertions locking amount parsing, year-exact vs
  amount-tolerant equality, quote-protected sentence spans, entity detection, FX
  adjacency, encoding sniffing, inverted-index == brute-force); and
  `tests/test_robustness.py`: determinism (identical reruns), 9 adversarial/edge inputs
  (empty, unbalanced markdown, huge numbers, emoji, CJK punctuation, NULs), performance
  (~16k-word doc checked in ~13 s; G1 budget 20 pages < 5 min).
  **Determinism holds offline; web verdicts are not run-stable by nature** (keyless
  search results vary) — never promise identical web verdicts across runs.
- **Tier B (private, owner's machine only, never shipped/marketed):** the KS records —
  89 verified sentences + 76 footnote verdicts + 54 corrections — as an out-of-domain
  check that Tier-A-measured behavior holds on a real 20-page case (§10 privacy honored).
- Gates (both tiers): recall of seeded hallucinations ≥ 80%; false-alarm precision ≥ 80%
  (target 90%); "unverified" used instead of guessing ≥ 95% of no-evidence cases;
  a web-regression guard test (`tests/test_web_guard.py`) must pass (unanchored snippets
  cannot flip verdicts).

**Product:**
- Time-to-first-verdict < 30s; 20-page doc report < 5 min
- Activation: ≥ 40% of users who run a doc return to edit verdicts
- Operating cost $0/mo for first 6 months; ≥ 85% of runs complete within budget (no queue rage)
- D7 return ≥ 20% (free product lives or dies on retention, not conversion)

## 12. Milestones

- **M0 — DONE (as M0+M0.5+foundation, 2026-09-03, local, no UI):** CLI engine (`python -m app.cli <doc>
  --corpus <dir> --web --llm --whitelist …`): extract → BYOS grep (md/txt/PDF/DOCX) →
  structural/timeline/attribution → optional keyless web + FX recompute → judge → exports
  (report.md [EN or ZH by doc language] / report.xlsx / claims.jsonl per §7 / annotated.docx|md).
  Dual golden sets (16 EN + 7 ZH seeds) + web-guard + robustness tests in `tests/`;
  gate: 100% recall / 100% precision offline, 100% exact anchors, 16k words in ~13 s.
- **M1 — BUILT LOCALLY (2026-09-03):** FastAPI backend (`app/server.py`: SSE thought
  chain, multipart paste/upload/corpus/names, §9 IP quotas enforced with honest 429s,
  export endpoints) + Next.js 15 frontend (`web/`: hero highlight view — click a span
  → evidence card with [LOCAL]/[WEB]/[FX] sources; verdict filter chips; live thought
  chain; download md/xlsx/jsonl). `/api` rewrite avoids CORS/env config. Contract test
  `tests/test_webapp.py` (SSE events, span-exactness against returned paragraphs,
  conservative-without-corpus, quota 429). `tests/run_all.py` = the 7-suite gate;
  `tests/test_blind_lego.py` (network, anti-overfitting) runs separately. REMAINing: email
  accounts, persistent job store, Oracle deployment, private beta.
- **M1.5 — BUILT LOCALLY (2026-09-05/06, quality-hardening pass):** found and fixed via the
  real Kingsoft 9k-word case study. Shipped: docx flattening (tables/text boxes/notes;
  Word-compatible word counts), every-sentence claim floor, preflight job planner +
  plan-confirm UX (`/api/estimate`, CLI `--estimate`, default-on web+LLM), one-line live
  progress with % + LLM-phase heartbeats, SearXNG second backend (localhost docker),
  query ladder with early-stop + reading-order phrases + modifier matching, contradiction
  bar raised (unit-noise, event, currency guards; time-series ≠ conflict; identifiers
  exempt), snippet-pool reuse + LLM pool re-judge with verbatim-quote guard, page
  deep-reads (passage precision), FX pairs pre-tagged + arithmetic verdicts incl. curated
  1978-98 PBoC/IMF table, source credibility tiers, footnote citations exempt from
  searching, 429 backoff + persistent/cold circuit breakers, `HANDOFF.md`. Gates: 100/100
  offline, 59 unit assertions, estimate calibrated ~±40% on real runs.
- **M1.6–M1.8 — BUILT LOCALLY (2026-09-06, the "too many unverified" campaign):** a
  long field-debugging session against the real Kingsoft case text. M1.6 speed/visibility:
  hard 90 s deadline per LLM call (a trickling provider froze a run 2 h), chunked
  semantic scan, honest progress phases + idle counter. M1.7 quality: `conflicting`
  verdict with BOTH evidence camps + user ruling (keep/fix/dismiss persisted to every
  export), `narrative` eligibility triage (heading/question/commentary never pending),
  official native-spelling feed to the planner (free LLMs invent wrong Chinese names),
  entity-first CJK queries to Wikipedia, rare-token Ctrl+F windows (merged, not
  skipped), scaled llm_max_tokens, dated-claim/undated-figure contradiction ban,
  ddgs breaker, SearXNG engine pinning (captcha'd engines crash combined responses),
  ddgs region pinning (cn-zh/wt-wt), subject-anchor gate vs geo-poisoned SERPs.
  M1.8 architecture swap: per-claim planned-query judging → **source-led clusters**
  (human workflow: find a few articles, read each once, check many claims) —
  ~90→6 LLM calls and 2–15 min → ~60–140 s per 250-word section; every LLM
  "contradicted" demoted to `conflicting` by rule; Brave Search key onboarded
  (Google CSE closed new signup; keys stay wired); refresh re-attach, one-run-
  per-IP, cooperative cancel. Gates: still 100/100 offline + blind-lego;
  unit assertions 59→~70. **Known ceiling accepted:** internal case facts are not
  on the public web — the BYOS acceptance run (user's source materials attached)
  is the designated next validation.
- **M1-deploy (next):** email accounts + persistent job store (sqlite), Docker Compose +
  Caddy on an **Oracle Cloud Always Free ARM VM** (genuinely $0, 4-core/24 GB tier);
  fallback Hetzner VM (~€4/mo) if denied. Private beta (10–20 case-writing users).
- **M2 (weeks 4–6):** BYOS libraries deepening + vector fallback, bilingual search
  whitelists, live-URL import. (Highlight viewer + accept/dismiss workflow shipped
  early via M1.7 user rulings; xlsx/docx exports already built.)
- **M3:** launch — no billing at all: Product Hunt / r/editoristics / HuggingFace, "free forever"
  as the differentiator vs Manus/Originality's credit burn.

## 13. Risks

| Risk | Mitigation |
|---|---|
| Free-tier API cuts / caps | multi-provider LLM abstraction; search providers pluggable behind one interface; structural-check-only "degraded mode" |
| Traffic spike drains daily free quota | global budget kill-switch + queue-to-tomorrow; per-run search caps; guest cap is the first dial to turn |
| False accusations of fabrication | conservative verdicts, always show raw evidence, user owns final call |
| Web snippets match the wrong entity (observed in live test) | entity-anchoring rule (F4b) + regression guard test |
| Keyless search throttling/h2 errors, unstable results | SearXNG localhost fallback backend, 5s search timeouts, fail-fast circuit breakers, honest degraded-mode labels; never a paid-key dependency |
| Keyless engines **geo-poison silently** (observed: Camry/YouTube results for Kingsoft queries when the IP is storm-flagged) | subject-anchor gate treats "no snippet mentions the subject" as an EMPTY backend and falls through; official free-tier API lanes (Brave live) first-class when keyed |
| Free-tier LLM judge waves real evidence / misreads tense & lookalikes | numbers never judged by LLM (deterministic `_assess_number` on passages); any LLM `contradicted` demoted to `conflicting`; lookalike-entity + tense rules in prompts; blind-lego anti-overfit gate |
| Free-tier search quotas (Brave ~1k/mo ≈ ~15–30 section runs) | keyless chain stays behind it; pacing 0.7 s; per-backend breakers; BYOS path costs nothing |
| A refreshed tab orphans a running job ("hollow waiting", double runs) | one-run-per-IP 409, `/api/active` re-attach + report polling, cooperative Stop → labelled partial report |
| Budget ceilings that don't scale with the doc | every budget (incl. LLM tokens) derived from the plan; unit test locks the scaling contract |
| Over-searching manufactures false conflicts (observed: more queries/call → more coincidental matches) | early-stop ladder (escalate only on zero results) + contradiction bar higher than support (event/unit/currency guards) |
| Conversions judged out of context (1990 RMB↔USD contradicted by TODAY's rate) | FX pairs tagged before web; converted figure exempt from standalone web verdicts |
| Estimates drift from reality | planner constants re-fit on real runs; range ±; coverage % + split recommendation instead of silent depth cuts |
| Long docs feel "stuck" when LLM phases are quiet | plan-confirm UX (time is predicted, not discovered) + heartbeat events + % bar |
| LLM invents claims/evidence | verbatim-anchoring guard (F2) + LLM must cite shown snippets (F5) |
| Claim extraction recall too low at M0 | taxonomy is narrow by design; iterate prompts against golden set, not vibes |
| URL extraction fragility (paywalls, JS) | "text mode" fallback; label URL-imports as coverage-limited |
| Manus adds our differentiator | our moat = document-internal checks + line-precise evidence + BYOS; they generalize, we specialize in case/business docs |
| Zero-budget scope creep | hard M0 gate before any web code |

## 14. Decisions log (author, 2026-09-03)

1. **Name: CheckMato.**
2. **All functions free**; limitations are quotas only, as loose as the $0 budget allows (§9).
3. URL input deferred to M2 (fragility); report evidence links are unaffected — those are outputs.
4. Search stack = "free at max effort": keyless ddgs/SearXNG first, Tavily/Brave free-tier keys
   pluggable; provider interface so nothing is hard-wired.
5. Hosting: none owned → Oracle Cloud Always Free VM ($0), Docker Compose; Hetzner €4/mo fallback.
6. **No KS-case dogfooding in public marketing.** KS corpus and golden set stay private; used only
   as the offline eval harness (§11).
7. **(v0.3) No KS data in the product repo.** KS folder = read-only workflow reference only;
   CheckMato ships with the synthetic Nimbus golden set instead (§11 Tier A).
8. **(v0.3) LangGraph dropped as an engine dependency.** The deterministic pipeline runs with
   zero paid services and no framework; a graph wrapper can be added in M1 only if the web
   layer needs resumable job orchestration.
9. **(v0.3) Keys live in `.env` only** (loaded locally, gitignored, never in prompts/logs/chat);
   every LLM/web feature must degrade to the free deterministic core when absent.
10. **(v0.3) Web evidence is entity-anchored** (F4b) — adopted after a live test proved
    unanchored snippets create false "supported" verdicts for fictional entities.
11. **(v0.4) Foundation closed pre-M1** (user decision "work on the foundation first"):
    exact anchors as the UI contract, PDF/DOCX BYOS, full ZH pipeline + bilingual reports,
    alias/name layer, dual-version fact-set diff, encoding sniffing, clip caps, conflict
    components, config file, unit-test layer. Eval: 17 EN + 8 ZH seeded, 100% recall /
    100% precision, offline.
12. **(v0.6) Full-depth-for-every-sentence is the quality contract** (user: "quality over
    speed; every claim/sentence should get 5–6 searches"). The regex floor alone missed
    descriptive claims ("WPS was a word processor") and ~30% of docx text (tables/notes).
    Added: every-sentence claims, Word-compatible counting, per-doc planner. Consequence
    accepted: a 9k-word doc honestly costs ~1 h at full depth; sweet spot per run ~1.5k words.
13. **(v0.6) Estimation is a quote, not a deadline.** Time ceilings are runaway guards;
    depth is only ever traded via the honest coverage % + split recommendation in the
    preflight plan the user confirms (`--estimate` / `POST /api/estimate`).
14. **(v0.6) Fewer, smarter searches beat more searches**: early-stop ladder (only escalate
    on zero results), reading-order phrase queries (no sorted token bags, no verbatim prose
    quoting), contradiction bar above support (event agreement / non-unit shared words /
    currency present), modifiers honored ("over 90%" ⊨ 95%). Each rule came from an observed
    live false positive on the Kingsoft case.
15. **(v0.6) Stated currency conversions are arithmetic, not web comparisons** — pairs tagged
    before searching; converted figure exempt from standalone verdicts; pre-1999 uses a
    curated PBoC/IMF annual-average table (source named in evidence), never a silent guess.
16. **(v0.6) Footnote/endnote text = the source, not a claim** (user call): never web-searched;
    its URLs still liveness-probed. Also: identical repeated sentences share one check.
17. **(v0.6) Reuse what the run already fetched**: snippet pool re-matched per unverified claim
    (free), and one batched LLM pool re-judge settles cross-language proofs; both gated by
    verbatim-quote guards — the LLM still cannot invent (G2 preserved).
18. **(v0.6) SearXNG optional, second in line, localhost-only** (ddgs stays primary): keyless
    Google/Bing aggregation + outage insurance; a public instance = free proxy that gets our IP
    burned. JSON format requires the shipped settings.yml; container-down state persists 15 min
    in `.breakers.json` so restarts don't re-pay timeouts.
19. **(v0.6) UI: web+LLM default ON; plan-confirm before long runs; one live progress line + %**
    (full chain behind "details"); LLM phases must emit heartbeats ("stuck at step 52" was
    silence, not a hang).
20. **(v0.6) `HANDOFF.md` added** as the living state-of-project doc; PRD remains the spec,
    README the quickstart. Gates: run_all (7 suites) after every change; blind-lego separately.
21. **(v0.7) Conflicting sources ≠ unverified — the user rules.** When evidence both supports
    and contradicts a claim, the engine shows BOTH camps (`conflicting`, side-tagged) and the
    user decides keep/fix/dismiss; decisions persist (`decisions.json`) and re-render into every
    export. No LLM keeps contradiction power: model-level "contradicted" is demoted to
    `conflicting` by code — only deterministic guards may contradict (free judges misread tense,
    lookalike companies, and dates; observed repeatedly on the Kingsoft case).
22. **(v0.7) Eligibility triage before effort.** Headings/questions (deterministic) and author's
    commentary (LLM batch, conservative-by-construction: unlisted = factual) become `narrative` —
    visible with a reason, never searched, never pending. Essay prose counted as "unverified"
    was the single biggest perceived-quality failure on a real case study.
23. **(v0.7) Source-led deep pass replaces per-claim web judging.** The human workflow is
    "find a few articles, read each once, check many claims" — clusters of related claims share
    1–3 short queries (entity + exact figure, native script) and ≤3 full-page reads; numbers are
    judged deterministically against passages, prose in one verbatim-guarded batch per cluster.
    (Per-claim 20-snippet LLM judging was simultaneously slower, pricier on free tiers, and weaker.)
24. **(v0.7) Search backend order = official-when-keyed, keyless-as-floor:** Google CSE (wired;
    closed to new signup, re-add if ever possible) → Brave (free $5/mo credit, live) → ddgs
    (region-pinned) → local SearXNG (pinned engines) → Wikipedia API. SerpApi-style 250/mo
    third parties rejected as non-strategic. All keys stay optional; behavior unchanged without.
25. **(v0.7) Run-session safety rails are product surface, not niceties:** one run per visitor IP
    (409 + Stop), refresh re-attaches to the running job, Stop is cooperative and yields a
    labelled partial report. A dropped browser stream must never orphan compute or quota.
26. **(v0.7) BYOS acceptance run (pending, user-requested):** internal-fact documents hit a hard
    public-web ceiling by nature; the agreed validation of the whole M1.6–1.8 arc is the Kingsoft
    section re-checked with the author's own source materials attached (deterministic file:line
    verdicts expected on exactly the claims the web cannot answer).
