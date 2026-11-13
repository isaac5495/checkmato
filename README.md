# CheckMato

Free, evidence-first fact-checker for AI-written documents. Upload a case
study / article / paper draft: CheckMato extracts every checkable claim
(years, amounts, FX conversions, quotes, names, footnotes, timelines) and
returns a report where **nothing is asserted beyond the evidence shown** —
each verdict links to a `file:line`, a web snippet, or says "unverified".

Live: **https://checkmato-app.vercel.app** (Vercel frontend) ·
**https://checkmato.fly.dev** (full app + API on Fly.io).

## Gates (run before every change)

```
.venv\Scripts\python.exe tests\run_all.py
```

Current state (2026-09-06): **100% recall / 100% precision** on 17 EN + 8 ZH
seeded hallucination findings; 59 unit assertions; robustness (determinism,
9 adversarial inputs, 16k words offline in ~13 s); web-guard; FastAPI+SSE contract.
M1.5 quality pass: full-depth job planner (`--estimate` / `/api/estimate`) with
plan-confirm UX, every sentence checkable, Word-compatible docx counting (tables +
notes), early-stop query ladders, snippet reuse + pool re-judge, page deep-reads,
FX-pair arithmetic (incl. curated 1978-98 rates).

## CLI

```
.venv\Scripts\python.exe -m app.cli <doc.md|.txt|.docx> --corpus <dir> ^
    [--names aliases.csv] [--web] [--llm] [--whitelist reuters.com,gov.cn] ^
    [--max-search 60] [--out reports]
.venv\Scripts\python.exe -m app.cli <doc> --web --llm --estimate   # preflight plan only:
    # budgets + time quote for THIS document, nothing is checked, nothing costs anything
.venv\Scripts\python.exe -m app.cli diff <a.md> <b.md> --names g.csv   # EN↔ZH versions
```

Outputs: `report.md` (bilingual chrome: EN or ZH by document language),
color-coded `report.xlsx`, `claims.jsonl` (the §7 record contract),
`annotated.docx/.md` (suggestions copy; the original is never touched).

## Web (M1) — one command

Double-click **`start.bat`**, or:

```
.venv\Scripts\python.exe -m uvicorn app.server:app --port 8000
```

→ open **http://127.0.0.1:8000** (the static UI is served by the same process).
Paste or upload → web search + LLM assist are ON by default → **approve the preflight
plan** (searches / deep checks / LLM calls / time quote, sized to your document — the
deeper the doc, the longer, never the shallower) → one live progress line with % →
highlighted document view: click a span for verdict, confidence, up to 3 evidence cards
(with credibility tier) and suggested fix; when live sources DISAGREE with each other
the item is marked **"Sources disagree"** with both camps shown (supports/against) —
you decide keep/fix/dismiss and the choice is saved into every export; unverified
items say *why* and give queries you can run yourself.
Guest quota: 1 doc/day per IP in production (free, no sign-up) — budgets,
never paywalls (PRD §9); `checkmato.toml` relaxes this for local dev.

UI development mode (hot reload) — optional: `cd web && npm run dev`
then open http://localhost:3000 (talks to the API on 8000).
After editing `web/`, regenerate the single-process build with
`cd web && npm run build` (outputs `web/out/`).

## Cheap by design

Explicit search engine, no auto chain: **DeepSeek Search** by default (in-house
index, ~$0.75 per 1,000 successful requests; empty results are free) or **Brave**
free credit, selected per run with `--backend`; entity-anchored query ladder with
early-stop. Free-tier LLM optional via `.env`
(Gemini/Groq/OpenAI-compatible auto-detect; OpenRouter via `OPENAI_BASE_URL`+`OPENAI_MODEL`);
ECB/Frankfurter FX rates + a curated PBoC/IMF 1978-98 table (provenance in every
evidence line); OpenCC s2t. Without keys or network the engine still runs fully:
BYOS grep + structural/timeline/attribution checks (degraded mode labels
exactly what was not checked).

> Note: Google's free Gemini API is geo-restricted — it returns "User location
> is not supported" from some regions. Everything except optional LLM assists
> (subject inference, auto-aliases, semantic claims) works there; for LLM
> assist from such a region use a free Groq or OpenRouter key instead.

## Continuous testing

English BYOS evaluation (synthetic, not part of `run_all`):

```
.venv\Scripts\python.exe -X utf8 tests\run_eval_en.py --suite tests\eval_en
```

It prints support rate, false support, not-checked, false contradiction and
internal conflicts. Prose is excluded from the deterministic denominator until
the semantic pass lands.

`tests/test_blind_lego.py` is the anti-overfitting gate: a company in no other
fixture, facts scraped from the real web, errors seeded beforehand with
pre-registered expectations (a real source-conflict case: lego.com vs Wikipedia
disagree on the naming year — the engine still catches the *fabricated* 1929).

## Layout

- `app/` engine — `textproc` `extract` `corpus` `checks` `judge` `web` `llm`
  `enrich` `fx` `names` `diff` `annotate` `report` `estimate` `state` `cli` `server`
- `tests/` — synthetic Nimbus fixtures only (EN, ZH, versions, PDF); every
  seeded hallucination is expected-verified; no proprietary data ships
- `deploy/searxng/` — retired 2026-11-02 (kept for history; no longer read)
- `PRD_factcheck_tool.md` — product spec (v0.6) as the single source of truth
- `HANDOFF.md` — current state, ops commands, design invariants — read before changing anything
