# CheckMato — Handoff

Status: 2026-11-11 · W1.3 + search cache + W1.4 behind `--semantic` + W5
precision/determinism + W6 coverage + free tier/UI + clue retrieval (pushed) ·
20 suites green.
BYOS + English-first + DeepSeek Search are the current engine; W1.1 (prose
retrieval), W1.2 (commentary eligibility) and W1.3 (claim units / multi-lead)
are done; W1.4 now has an opt-in support-only semantic judge behind
`--semantic` (its W0 exit-gate eval is still open). W3 (citation lane), W4
(scanned PDFs) and W6 (product surface) remain open. Written for whoever picks
this up next (AI session or human) so today's
decisions don't get re-litigated.
Product spec stays in `PRD_factcheck_tool.md`; this file is "what is true NOW".

## Repo state (2026-11-09)

- `main` is up to date with `origin/main`; the W1.3, search-cache, W1.4, W5
  and W6 changes are pushed. The only untracked file is
  `Ledgerline_New_Business_Proposal.docx`, deliberately left out (course
  document — do not add it). `.opencode` is ignored by the tooling.
- Search cost, measured on a 628-word chapter with the LLM off (2026-11-02):
  5 searches / 1 page = 4.9 s, 9 supported, ≤ **$0.00375**; full depth =
  54 searches / 20 pages (of a 243-search budget), 42.5 s, 14 supported,
  0 contradicted, ≤ **$0.0405**. DeepSeek bills successful requests only
  ($0.00075 each); page deep-reads are direct HTTP and free.
- Next session: W1.4's real true-prose exit-gate eval (the synthetic 50-case
  proxy is green, but the real 20 labels are diagnostic); W3 citation lane;
  W4 scanned PDFs; W6 UI labels. W1.4 stays opt-in and default off until the
  real gate passes. Deterministic leftovers and the parked ideas are in
  `IMPROVEMENT_PLAN.md` §12 and the "Out-of-scope findings" below.
- Verification set: `tests\run_all.py` (20 suites) plus `test_byos.py` (48),
  `test_claims.py` (10), `test_retrieval.py` (14), `test_no_case_literals.py`,
  `test_byos_offline.py` (0 connections), `run_eval_en.py` and
  `run_eval_holdout.py`.

## 2026-11-11 — 50-item gold review + clue-first retrieval (code changed)

The user reviewed the 50-item gold sheet (`reports/w1-gold-50.html`) and gave
the missing narrative/retrieval judgement. Reviewed labels:
`reports/w1-gold-50-reviewed.json`.

Review breakdown:
- **18/50 narrative/not checkable** (1,2,3,5,7,16,19,20,24,28,31,35,36,38,
  42,44,48,50).
- 21 supported, 7 not supported, 1 **partial** (c326: only 金山快译 missing),
  3 unclear/online.
- Retrieval misses despite true claims: 28元定价 (c331), 3.2英寸 /
  Microsoft-mobile (c370), 剑网3 / 西山志 (c357), 十年为维度 (c380),
  金山高管团队访谈 (c364/c365), ALL IN AI (c430), 金山快译 (c326).
- Quote/title: c381 was supported from a section heading
  (“不怕死的决心和向死而生的勇气”), not attributed speech.
- Multi-company/compositional: c404 (Xiaomi + Kingsoft) is narrative, not one
  checkable fact.
- Exact evidence: c398 has one perfect passage (`生生不息.md:2233`) plus two
  irrelevant; W1.4 should narrow to the perfect one.

Baseline on the 50 (Agnes relay; DeepSeek was unavailable/rate-limited):
- supported **2/22**, not_supported **0/6**, narrative **3/18 false**,
  partial 0/1, unclear 1/3.
- The 3 narrative false supports and the c381 quote-title false support are
  quality bugs; the 2/22 recall is mostly retrieval + model weakness.
- DeepSeek-only rerun produced 0 output (3 calls, 0 tokens, net_dead); rerun
  when the key recovers before treating this as the production baseline.

Clue-first retrieval (shipped):
- `textproc.clue_terms()` extracts figures+units (`28元`, `3.2英寸`), Chinese
  numerals (`十年`), quoted phrases (`白菜价`), all-caps/codes (`ALL IN AI`),
  and CJK names (`华光快译`).
- `Corpus.find_prose_candidates()` adds a **clue lane** (literal Ctrl+F) and
  a strong clue score, so the decisive string is not lost by the generic
  rare-token ranking.
- `tests/test_clue_retrieval.py` 10 assertions; `run_all.py` 20 suites.

Still open from the review:
- W1.2 narrative eligibility (18/50 leaked because the sheet was built from a
  sources-only run; rebuild with LLM triage and add deterministic patterns).
- Quote attribution guard (a heading/title is not a spoken quote).
- Multi-company/compositional guard.
- Partial-support state (verdict or note? — user decision).
- Source routing (game → 西山志; interview → 金山高管团队访谈).
- W1.4 exact evidence narrowing.

## 2026-11-11 — free tier (BYOS-only + 40-search lite) + W6 UI (code changed)

User decisions: 2A+2B (BYOS-only plus a 40-search lite mode), 5A (coverage in
the web UI), 3C (defer W3), 4B (keep external conversion for W4).

- `--free-tier`: `search_cap` is applied AFTER the planner/config floors, so
  `max_search` becomes a hard cap (40, `free_tier_search_cap`) instead of the
  old "floor". BYOS-only stays the zero-network option. Hosted guest runs
  (`enforce_ip_quota=true`) use the cap by default; local/desktop runs do not.
- Claims reached after the cap get `_skip_reason` "web budget reached";
  `coverage_counts()` marks them `not checked`, never `checked, not found`.
  The report/UI say so explicitly.
- Web UI (`web/app/page.js` + `globals.css`): coverage strip (supported /
  checked-not-found / not-checked / no-source / not-checkable / needs-attention
  / conflicting) and a free-tier banner. Static export rebuilt in `web/out`.
- 40-search sizing: measured 3.0 searches/claim → ~7–13 claims (planner
  5.6/claim → ~7). By claim density: 246-word/34-claim draft ~50–95 words
  (20–38%); 500-word/50-claim ~70–130 (14–26%); 14.5k-word/347-claim case
  study ~290–550 (2–4%); 628-word narrative ~250–330 (40–53%). Cache hits do
  not consume the cap; the rest is `not checked`.
- W1.4 gold set: `reports/w1-gold-50.html` is ready (50 sampled real prose
  claims + top-3 passages, localStorage progress, JSON export). Waiting for
  the user's labels before running the real recall/false-support gate.
- Tests: `test_free_tier.py` 11 assertions; `tests/run_all.py` 19 suites all
  PASS.

## 2026-11-11 — W6 coverage split: not-checked is first class (code changed)

`unverified` used to mean two different things: "we checked and found nothing"
and "we never checked it". The second is not a negative finding.
`app/report.py:coverage_counts()` now splits every run into:

supported · needs attention · conflicting · checked-not-found · not checked ·
no source · not checkable · structure.

`report.md` opens with a one-screen coverage table; `meta["coverage"]` carries
the same counts for the API/UI; the CLI prints a compact line.

- `_lane_checked()`: `_searched` only records the WEB lane. In a `sources_only`
  or `sources_then_web` run the deterministic judge/apply_byos pass already
  checked the claim against the library, so its `unverified` claims are
  "checked, not found" — not "never checked". Only a web-only run with no
  search (or budget/cancel) lands in "not checked".
- KS Chinese (347 claims, 5 BYOS sources): supported 81; needs attention 3;
  checked-not-found 206; not checked 6 (deferred web); no source 32; not
  checkable 113. The six deferred-web items are the only genuinely unrun lane.
- `tests/test_coverage.py` 9 assertions; `tests/run_all.py` 18 suites.
- Test hygiene: `test_webapp.py` no longer requires an `internal_conflict` from
  the synthetic doc (W5 removed that false positive) and clears the persisted
  guest quota before its first request.

## 2026-11-11 — W5 precision cleanup + deterministic retrieval (code changed)

The KS residual was 19 internal conflicts; the English doc had 11 timeline
flags. Nearly all were different facts, not contradictions. `app/checks.py`:

- `_metric()`: metric family closest to each figure (revenue / gross profit /
  net profit / funding / bonus / target / reserve / ownership / voting /
  cost). A known different metric is a different fact.
- `_pct_base()`: Chinese `20%的股权` vs `22.89%的投票权`; it locates the raw
  percentage first so "2020" is not read as "20%".
- `_scope()`: department-level vs group-level figures.
- `_BONUS_GENERIC`: different people's bonuses share only generic words.
- `_in_date_range()`: a year that is a range endpoint
  (2017年12月至2018年1月; December 2017 and January 2018) is not a standalone date.
- `entity_timelines()`: sentence-level entity match, full multi-word name,
  sibling skip (Kingsoft Cloud ≠ Kingsoft), months/document titles excluded.
- `timeline_conflicts()`: version split, date-range filter, and Jaccard ≥ 0.30
  between the years' sentences (same event, not just the same verb).

**Determinism bug found and fixed.** Two fresh CLI processes on the same KS
document flipped 2–5 borderline claims (supported ↔ unverified) and their
evidence. Root causes were hash-order ties, not bm25s alone:
`Corpus.rare_tokens` (df/length ties), `judge._names_present` (equal-length
entity), `detect_cjk_entities` (quoted-set tie at max_n), the bm25s equal-score
cutoff, `_field_rerank`, and `cand_p`. All now have full `(fname, start)` /
token-string tie-breaks. Two fresh end-to-end runs (det7/det8) now have **0
verdict and 0 evidence differences**.

Results:
- KS Chinese (347 claims, 5 BYOS sources): internal 19 → **0**; timeline 4 → 0;
  supported 76 → **81** (stable across two fresh processes).
- English doc (541 claims, no library): timeline 11 → **0**.
- Tests: `tests/test_precision.py` 14 assertions; `tests/run_all.py` 17 suites,
  all PASS.

Caveat: 0 flags on these two documents means no remaining contradiction was
found, not that the documents are proven consistent; the true-positive controls
(same revenue, same shares, same version, same person's bonus) still fire.

## 2026-11-11 — W1.4 semantic prose judge, support-only (code changed)

User chose W1.4. Shipped the LLM baseline from `IMPROVEMENT_PLAN.md` §W1 behind
`--semantic` (default off); the base install and all gates are unchanged.

- `app/nli.py` (new): optional semantic judge. Reads the FULL sentence
  (`sentence_context` > `context_sentence` > `sentence`), W1.1 BYOS
  `find_prose_candidates` and this run's web pool. Batches 8 claims per call;
  max 24 claims/run. A support must quote a **verbatim** span of the evidence,
  checked before any verdict is set. Only `supported` is accepted, confidence
  capped at `medium`. Model `contradicted`/`conflicting` are ignored — only
  deterministic guards may flag those. No new dependency: it uses the existing
  LLM chain; the MiniCheck/Erlangshen backend can replace `judge()` later
  without changing the contract.
- `enrich(..., semantic=False)`: runs AFTER `_pool_judge`, so a conflicting
  source is surfaced before a support can hide it; before `_share_result` and
  `_explain`.
- CLI `--semantic` (requires `--llm`; without it the run warns and prose stays
  unverified). Meta `semantic` / `semantic_rescued`; report line.
- Tests: `tests/test_nli.py` (11 assertions: verbatim support, invented quote
  rejected, contradiction ignored, numbers excluded, no-evidence no-call, web
  evidence, unavailable LLM). `tests/run_all.py` is now 16 suites, all PASS.
- Smoke test (synthetic Nimbus Cloud draft + one BYOS source, `--web --llm
  --semantic`): prose event supported, medium, evidence `source.md:1`; 3
  searches, 7 LLM calls.
- **Synthetic exit-gate proxy** (`tests/bench_nli_prose.py`, network benchmark,
  not in `run_all`): 50 cases (25 true paraphrases + 25 near-misses, English
  and Chinese). Result: **recall 25/25 (100%), false support 0/25 (0%)**,
  6 LLM calls, ~30 s, DeepSeek. The benchmark's per-claim evidence blocks are
  deliberate: a shared evidence list let the model borrow a true passage for a
  near-miss twin, which is why the prompt scopes evidence per claim.
- **Real 20 diagnostic labels** (private KS doc, 5 BYOS sources, no web):
  `search_wrong` 1/11 rescued (c300 from 金山AI辯論戰.md:1961); `not_checkable`
  0/5 touched; `model_wrong` 0/1; the one uncertain item rescued (c323 from
  生生不息.md:289). The two labels recorded as "supported" in the earlier run
  are `unverified` in this 5-source reconstruction, so they are not clean
  recall evidence. 2 LLM calls, ~21k tokens.
- **Honest conclusion:** the semantic judge is safe (zero false greens in both
  the synthetic suite and the real labels), but real recall on long, multi-fact
  Chinese sentences is still low. The bottleneck is evidence packing/retrieval
  (one passage rarely covers a whole W1.3 sentence), not the prompt. So
  `--semantic` stays opt-in and default off; the next lever is W2-style
  multi-passage retrieval, not a looser judge.
- Still open: W2 retrieval/evidence packing; add the 62-case hard suite to
  `tests/`; cluster-first / first-query benchmarks. Free-tier policy is settled
  (BYOS-only + 40-search lite; see the 2026-11-11 free-tier section).

## 2026-11-09 — persistent search cache + quote pool-first (code changed)

User constraint: no quality trade. Only levers that cannot remove an evidence
chance were shipped; the hard cap / ladder cut / claim skipping stay rejected.

- `app/searchcache.py` (new): SQLite SERP cache. Key = SHA-256(backend +
  NFKC/casefold/whitespace-normalized query + max_results). TTL 14 d
  (`search_cache_days`). Stores **results only, never verdicts**; empty SERPs
  are NOT cached (a transient miss must not freeze a claim for 14 d). Default
  path `%LOCALAPPDATA%\CheckMato\search_cache.sqlite` (or
  `$XDG_CACHE_HOME/checkmato`); `CHECKMATO_CACHE_DIR` overrides. Config
  `search_cache` (bool) and `search_cache_path` (tenant-specific file for
  hosted deployments). CLI `--refresh-search` (bypass read, still write) and
  `--no-search-cache`.
- `WebEvidence.search`: persistent lookup BEFORE the budget check; a hit costs
  no budget and is still added to `_pool` (cross-claim reuse and pool-judge
  must see the same pages as run 1). In-run `_cache` now keys on normalized
  query + max_results, so case/whitespace variants dedupe within a run.
- `app/enrich.py`: `_apply_reuse()` helper; **quote-only** pool-first. A
  verbatim quote already in the pool is the same >=0.9 `_assess_quote` match a
  direct search would apply, and quotes have no contradiction path. Numbers
  still search: only the direct search can surface a conflicting value.
- Report/CLI: `web_cache_hits` / `web_cache_misses`; summary and `report.md`
  show hits separately (a hit is free, not counted as a search).
- Quality bug found by the verification: LLM context extraction returned the
  STRING `"None"`/`"??"` as native names, which became entity anchors; a
  tianyancha annual report containing the literal word "None" then
  "supported" an unrelated 2019 claim (c014 in run 1). `textproc.clean_name()`
  now drops placeholders before they reach `entities`/`entity_pairs`.

Measured on `tests/case_ai_draft.md` with one shared cache dir:
- run 1 (cold): 91/215 searches, 0 hits, ~$0.068 search.
- run 2 (warm): 4/232 searches, 90 hits, ~$0.003 search.
- run 3 (warm): 1/209 searches, 70 hits, ~$0.00075 search.
- Claim count varies 35–39 across runs because the LLM triage/semantic stage
  is nondeterministic — pre-existing, not caused by the cache. The
  deterministic cache gate is `tests/test_search_cache.py` (same query, TTL,
  empty-SERP, refresh, quote-reuse, number-still-searches).
- The only same-claim verdict change (c014 supported → unverified) was the
  `"None"` false green above; after `clean_name()` the anchor is gone.

Tests: `tests/run_all.py` — 15 suites, all PASS (ruff + 188 unit assertions +
7 subject-guard assertions + the new cache suite).

Still open: the 62-case hard suite is not in `tests/`; cluster-first and
better-first-query remain measure-then-adopt; free-tier policy (BYOS-only vs
quota) is a user decision; W1.4; push the three W1 commits plus this change
after user confirmation.

## 2026-11-07 — search cost: quality-first constraint (research, no code changed)

- User constraint: never trade quality for cost. No hard caps, no skipped
  claims, no ladder reduction, no cheaper backend unless a benchmark proves
  no loss. This supersedes the earlier free-tier hard-cap idea.
- Measured on `tests/case_ai_draft.md` (246 words, 34 claims, 31 searched):
  **93/204 searches**, 52 pages, 7 LLM calls, **$0.06975**; search is ~91% of
  variable cost. 93 = 31 × 3: the ladder exhausted its 3-query cap because
  the test company is fictional. Real docs should early-stop more; the
  planner's 5.6/claim is a ceiling (actual here 3.0).
- No persistent cache exists (`WebEvidence._cache` is per-run, exact-string
  only). `max_search` is a floor, not a cap (`scaled_budgets()` takes max).
- Rejected as quality-reducing: free-tier hard cap, ladder 3→2 without proof,
  skipping claims, unbenchmarked backend swap.
- Quality-preserving levers (pending implementation): (1) persistent SERP
  cache — SQLite, TTL 14 d, normalized key, results only, per-install;
  (2) pool-first — run `reuse_pool` before `_apply_web` spends a search;
  `_reuse_pass()`/`_pool_judge()` currently run only at the END;
  (3) canonicalize the cache key only; (4) optional 3-day negative cache.
- Measure-then-adopt: better first query (instrument which rung supports);
  cluster-first ordering; whitelist ordering. Gate on the 62-case hard suite:
  supported recall and false support must be unchanged.
- Free tier: a quota is a coverage cut; the only quality-preserving free tier
  is BYOS-only. Pending user decision.
- Next: user asked for handoff first. Then implement cache + pool-first,
  re-run the same doc twice, confirm identical verdict distribution and
  materially fewer searches on run 2.
- Full cost/revenue detail and the provider comparison:
  `C:\Users\user\AppData\Local\Temp\opencode\checkmato-cost-revenue-handoff-2026-11-06.md`
  (§13 provider comparison, §14 this analysis).

## 2026-11-05 — W1.3 claim units, fragments, multi-leads (code changed)

The private eval's E case (c321) started at "时，总结出了…" because a closing
quote split the sentence; the flat 446-row run also counted 94 footnote/URL
structure rows as claims.

- `app/extract.py`: `_sentences()` rejoins a continuation clause after a
  closing quote/comma. `_assign_sentence_units()` adds `sentence_id`,
  `sentence_context`, `slot_kind`, `is_primary`, `sentence_claim_count`,
  `fragment_of_previous` and `parent_sentence`. Numeric/quote rows remain slots
  of the sentence; per-figure verdicts are untouched.
- `app/cli.py`: `_query` uses the joined sentence; citation/URL/placeholder
  rows get `slot_kind="structure"`; meta and the CLI report
  `sentences / claims / structure`.
- `app/byos.py`: prose claims keep the top 3 `lead_candidates`; the primary
  lead is still a lead, never evidence.
- `app/judge.py` / `app/enrich.py`: event/name/speaker context uses the joined
  sentence for fragments.
- `app/report.py`: §7 records carry the sentence-unit fields; report.md shows
  "Sentences / claims" and other leads.
- `tests/test_claim_units.py`: 11 synthetic assertions; `test_prose_retrieval`
  extended to 11 (multi-fact leads); `run_all` is now 14 suites.
- Private KS run: **268 sentences / 347 claims / 94 structure** (was 446 flat
  findings). c321 is now one full sentence with 2 slots (no orphan `时，`);
  c314/c315 each carry 3 lead candidates; 6 fragments were attached.

## 2026-11-05 — W1.2 commentary eligibility (code changed)

The 20-item eval's 5 `not_checkable` cases were essay commentary ("38年来…",
"历经多次危机…", "已逐渐凝聚为…", "我们将深入剖析…", "从来不是…而是…").
`mark_narrative` only covered headings/questions; a `sources_only` run has no
LLM triage, so they stayed `unverified` and entered retrieval.

- `app/enrich.py`: `mark_commentary()` — a deterministic, conservative floor
  for authorial method/transition, temporal summaries, interpretive summaries,
  belief/value statements, evaluative contrasts and method/analysis. Only
  `event`/`sentence` claims; numeric/quote claims are untouched. A false
  negative is safer than silently dropping a fact.
- `app/cli.py`: called after `mark_narrative()` and before `classify_prose()`.
- `tests/test_narrative_floor.py`: 15 synthetic assertions (fictional 华光),
  in `run_all` (13 suites).
- Private 20-item check: **5/5 A -> narrative; 0 of the other 15 changed**.

## 2026-11-05 — W1.1 prose retrieval (code changed)

The 20-item prose eval (private KS material, not committed) found 11/20 search
misses, 5/20 narrative, 2/20 missed support, 1/20 library-empty, 1/20
segmentation, and **0/20 pure semantic-model failures**. Retrieval was the
bottleneck, not NLI.

- `app/corpus.py`: new `find_literal_lines()` (exact substring / Ctrl+F lane)
  and `find_prose_candidates()` (BM25 + the existing bounded field rerank +
  rare-token passages + literal lines; scores unique terms, multi-term
  coverage, source-title matches and the longest shared phrase). `norm_lines`
  is cached once per Corpus.
- `app/byos.py`: event/sentence leads now use `find_prose_candidates()` instead
  of `tokens(sentence)[:8]` + `find_passages(min_shared=2)`. Prose verdicts
  stay `unverified`; only the lead changes (a lead, never proof).
- `tests/test_prose_retrieval.py`: 9 synthetic assertions, no KS material; added
  to `run_all` (12 suites).
- Private check (not committed): the 11 B cases went from 6/11 to **11/11**
  correct source file in the top 3; 9/10 manually-labelled sections are in the
  top 3 and 7/10 are top-1. **c319** (canteen/villa) still ranks the right
  section #7 — a same-company/different-section case that needs a second pass
  or W1.4, not a private-case keyword hack. No rule was tuned to KS text; the
  synthetic fixture covers the general multi-term pattern.

## 2026-11-02 — compound claims, venue guard, DeepSeek-only search

Three deterministic gaps closed, plus the search-engine replacement the user
asked for.

- **W2.5 compound splitting is wired** (`app/extract.py` calls
  `normalize.split_compound`). A sentence with one numeric clause and one prose
  clause now yields BOTH: the figures as numeric claims and the remaining
  clause as an `event` claim. The displayed `sentence` stays the original
  sentence; `raw`/`span` point at the clause, so the hover contract is
  unchanged. Gate: `tests/test_compound.py` (14 assertions, in `run_all`).
- **W5 venue guard** (`judge._same_instance`). A contradiction now requires the
  same place-like name on both sides ("in Bergen" / "Bergen plant"); a
  different venue is `unverified`, not `contradicted`. Entity mismatch was
  already covered by `_names_present`. Guard-disabled A/B: the same fixture
  came back `contradicted` without the guard and `unverified` with it. Gate:
  `tests/test_venue_guard.py` (6 assertions, in `run_all`), including two
  controls (same venue/different year still contradicts; a one-sided
  attribution still contradicts).
- **Search is DeepSeek-only by default; the auto chain is gone.** Removed
  `ddgs`, `SearXNG`, `WikidataAPI`, `WikipediaAPI`, `GoogleCSE`, the auto
  backend mode and their breakers from `app/web.py`. `WebEvidence` now carries
  `deepseek` (default) and `brave`, selects exactly one, and reports
  web-unavailable when neither key exists. CLI: `--backend deepseek|brave`
  (default deepseek). API/UI: `backend` defaults to `deepseek`; the page offers
  `DeepSeek Search` / `Brave only` (rebuilt into `web/out`). Config keys
  `searxng_url`/`searxng_engines` are ignored (kept in the example only as a
  historical note). DeepSeek Search is billed per successful request
  ($0.75/1,000; empty sets free) — rule 1 was rewritten from "$0 by design".
- **Gates**: `run_all` PASS (11 suites), BYOS 48, claims 10, retrieval 14,
  no-case-literals, offline 0 connections, eval_en 100%/0%, holdout 100%/0%.
- **Cross-claim reuse is support-only** (found by the budget A/B): a snippet
  fetched for another claim may confirm a figure, never contradict it. A WPS
  retrospective listing 1988/1989/1993/1995/1996/2010 "refuted" a 1997 launch
  claim it never named; `reuse_pool` now drops a `contradicted` result and
  `_reuse_pass` ignores one defensively. Direct searches keep the full
  contradiction guards. Gate: `test_web_guard` reuse cases (same-subject
  snippet still supports; a year-list snippet no longer contradicts). Re-running
  the 5-search budget now yields 0 contradicted, 31 unverified, 9 supported.

Out-of-scope findings (recorded, not acted on):

- `PRD_factcheck_tool.md` still describes the keyless ddgs/SearXNG/Wikipedia
  chain; it is a v0.6 historical spec and was not rewritten.
- `deploy/searxng/` remains on disk, retired; nothing reads it.
- A `library.toml` written outside the library folder resolves source paths
  relative to itself, so `Library(toml)` can load 0 lines and every claim reads
  "No corpus provided."; `library check` reports it, but the silent-empty case
  still deserves a warning.

## Run / stop / test

- Start: double-click `start.bat` (or run its Start-Process line) → hidden server
  on http://127.0.0.1:8000; UI is served by the same process from `web/out`.
  Use **127.0.0.1**, not `localhost` (IPv6 refusal trap). Stop: `stop.bat`.
- Search (default): **DeepSeek Search** — `DEEPSEEK_API_KEY` in `.env`,
  `POST https://api.deepseek.com/v1/tools/search`. In-house index, billed per
  successful request ($0.75/1,000; empty results are free), 100 QPS, results
  carry `summary` + `authority` + `rerank_score`. Brave remains an explicit
  alternative (`--backend brave`, free monthly credit). There is **no auto
  chain and no keyless fallback**: the selected engine is the only one that
  runs, and an unkeyed selection is reported as web-unavailable, never
  silently replaced. The old ddgs / SearXNG / Wikidata / Wikipedia clients and
  their breakers were removed 2026-11-02.
- Gate after EVERY change: `.venv\Scripts\python.exe tests\run_all.py` (ruff lint +
  11 suites, ~1-2 min). `test_blind_lego.py` (network, anti-overfit) is NOT in run_all — run it
  separately after touching web/extraction logic.
- Lint: `ruff.toml` is deliberately narrow (pyflakes + core errors only — broad
  excepts are rule-11 design, style rules would just churn). Do not widen without
  sign-off. The old silent `except: pass` sites (config/corpus/extract/state) now log
  to `checkmato.*` loggers: warnings hit stderr (→ logs\server.err) by default,
  `CHECKMATO_LOG=DEBUG` surfaces the best-effort-path debug lines too.
- UI dev: `web\app\page.js` (plain React, no TS) → after edits: `npm run build`
  in `web/` → restart server. Preflight CLI: `python -m app.cli doc --web --llm --estimate`.
- RESTART TRAP (cost an hour on 2026-09-07): `start.bat` launches uvicorn WITHOUT
  `--reload`; `run_server.ps1` runs the supervised reload variant. If a no-reload
  server is up while you edit `app/*.py`, the UI silently tests OLD code (the
  "outside the cap" report came from exactly this). When restarting: kill BOTH
  the uvicorn python AND the run_server powershell (the while-loop respawns),
  then start exactly one. `stop.bat` only kills pythons.
- LLM keys in `.env` (Agnes current; OpenAI-compatible via OPENAI_BASE_URL/MODEL).
  Search keys in `.env`: `BRAVEX_API_KEY` set (free plan = $5 credit/mo ≈ 1,000
  queries); `GOOGLE_CSE_*` present but DISABLED — Google no longer lets new
  projects enable the Custom Search JSON API (engine sunsets 2027 anyway).
  The provider stays wired: re-enable by uncommenting if access is ever granted.
  Logs: `logs/server.err` + `logs/server.log`. Restart hangs → see table in chat history.
- Web UX safety rails (learned the hard way in the field): ONE live run per
  visitor IP (`/api/check` returns 409 + running_job), refresh RE-ATTACHES via
  `/api/active` + `/api/report` polling (a dropped SSE stream must never orphan
  a run), Stop button = cooperative cancel (`POST /api/cancel/{job}`; engine
  checks between units, finishes with an honestly-labelled partial report).

## BYOS (2026-10-27) — sources-first verification, P0–P3

The engine can now verify a draft against a folder of the user's sources
instead of the web. Modes: `sources_then_web` (default when `--library` is
given), `sources_only` (no network at all, no LLM either), `web_only`.

```
.venv\Scripts\python.exe -m app.cli library index <dir> --out library.toml
.venv\Scripts\python.exe -m app.cli library check library.toml
.venv\Scripts\python.exe -m app.cli library import <lib> <converted.md|docx> --derived-from <scan.pdf>
.venv\Scripts\python.exe -m app.cli glossary draft.docx --library <dir|toml> [--glossary-llm]
.venv\Scripts\python.exe -m app.cli draft.docx --library <dir|toml> --footnotes
.venv\Scripts\python.exe -m app.cli draft.docx --library lib --sources-only --footnotes
```

Built in this pass:

- `app/library.py` — manifest (`library.toml`), generic discovery, line and
  page locators, md↔pdf page map, `no_text_layer` detection,
  `import_converted()` for externally converted scans. Skipped dirs: `.venv`,
  `archive`, `reports`, `logs`, `node_modules`.
- `app/byos.py` — `no_source` conversion, evidence enrichment with
  `source_id` + `page` (and `page_unavailable` when there is no page map),
  footnote audit (`misattributed` when the anchored sentence and the cited
  source are about different milestones), `audit.md`, `corrections.md`, and the
  conservative contradiction guards described below.
- `app/glossary.py` — same-language alias rules with `scope`
  (`same|parent|subsidiary|product`), and `verify_pair()`.
- `app/glossary_build.py` — deterministic harvest (glosses, org suffixes,
  repeated prefixes) + optional model proposal + corpus verification. The
  model returns candidates by signature only; nothing ships without the
  source occurrence proof.
- `app/corpus.py` — passage index (300–900 chars, never across a heading) used
  as a support-only fallback when a fact is split across lines.
- `app/extract.py` — `footnote_anchors` for `.docx` and markdown `[^n]`.
- `app/judge.py` — evidence rows carry `source_id`/`page`; passage fallback.
- `app/report.py` — `mode` in `claims.jsonl`, source/page in evidence lines,
  mode + library lines in `report.md`.
- `app/cli.py` — `--library`, `--sources-only`, `--footnotes`,
  `library index|check|import`, `glossary`.

Gates added (not in `run_all`; run separately):

```
.venv\Scripts\python.exe -X utf8 tests\test_byos.py            # 44 assertions
.venv\Scripts\python.exe -X utf8 tests\test_byos_offline.py    # 0 connections
.venv\Scripts\python.exe -X utf8 tests\test_no_case_literals.py
```

### Real-case acceptance (read-only, 2026-10-27)

The KS folder was reachable. A manifest was written to `%TEMP%` (never into the
repo) listing 7 sources — the five book transcripts, the meeting summary and
the 2025 results press release — 6,634 indexed lines. The Chinese draft was run
`sources_only --footnotes`; nothing in the folder was modified and no network
call was made.

Result of the final run:

```
446 findings
  87 supported
   5 contradicted
 147 unverified
  54 internal_conflict
   2 paraphrase_flag
   6 deferred_web
   1 narrative
48 footnotes audited
~8 s, 0 network
```

Two bugs surfaced on the first run and were fixed:

1. A manifest whose sources live outside its own folder caused `Corpus` to scan
   the manifest folder instead (it judged the draft against an old report). The
   library now ingests exactly the listed files.
2. Footnote citations carry the full title ("《生生不息：一个中国软件企业的…》")
   while the manifest carries the short one. Resolution now accepts either
   direction of containment with a minimum length.

Contradictions were also cut from 61 to 5 by two general guards: a year on a
book page is context, so a contradiction needs the same milestone; and a
contradiction needs a distinctive shared term, not just a shared year.

### Why items were not supported (2026-10-28)

A reusable analyzer now explains every non-supported outcome of a run and writes
a portable docx. It reads the run's `claims.jsonl` plus the library, retrieves
the top candidate line for each item, groups them by cause, and prints the
general rule each group points to. No case answers are in the code — the
examples come from the run.

```
.venv\Scripts\python.exe -X utf8 -m app.cli analyze <run>\claims.jsonl ^
    --library <dir|toml> --out reports\byos\non_supported_analysis.docx
```

Latest acceptance run (`ks_byos_out11`), after the fixes below:

```
supported          80
unverified        228  (123 prose with no checker, 105 numeric/quote)
narrative         108  (eligibility: headings/citations — intentional)
internal_conflict  19
contradicted        3
deferred_web        6
paraphrase_flag     2
```

The docx (and its markdown twin) is at
`reports\byos\non_supported_analysis.docx`; `reports/` is gitignored.

Fixes derived from the analysis (all general, no case data):

1. **Eligibility before retrieval** — docx heading styles and footnote
   citation paragraphs are classified before judging. `read_doc()` now returns
   `heading_paras`, and citation claims become `narrative` instead of being
   searched. This removed ~120 false pending items and 3 false contradictions.
2. **Prose honesty** — a sentence with no figure/quote has no deterministic
   checker. It now stays `unverified` with the nearest passage as an explicit
   "lead, not proof", instead of claiming no source covers it.
3. **Local, unit-aware internal conflicts** — counts need the same unit (age
   vs staff vs lines), amounts/percentages must be within 3 paragraphs and
   share a metric word. This cut document-internal conflicts 54 -> 19 without
   touching source verdicts.
4. **Year proximity for contradictions** — a conflicting year must be stated
   next to the claim's own subject in the cited line. Contradictions fell from
   8 to 3.
5. **Value-first retrieval** — lines and passages are indexed by the value they
   state, so "12.2万行" finds "122,000 lines"; space-grouped numbers
   ("122 000") are parsed as one value. Supported rose 60 -> 80.

Before/after on the same draft (446 findings):

| pass | supported | contradicted | unverified | internal | narrative |
|---|---|---|---|---|---|
| pre-eligibility | 70 | 61 | 108 | 54 | 1 |
| after eligibility | 55 | 5 | 85 | 54 | 105 |
| after prose/conflict fixes | 60 | 5 | 238* | 19 | 116 |
| after value-first retrieval | 80 | 3 | 228 | 19 | 108 |

*The rise is reclassification, not regression: 123 prose claims that were
wrongly called `no_source` are now honestly `unverified` with a lead.

Still open (recorded in the analyzer's "General fixes" section): entity
proximity for amount/percentage contradictions; overlapping passages and
figure-first ranking (the main recall gap); numeric formatting normalisation;
and the 5 residual contradictions are all same-event collisions on different
entities/venues.



### Still open after this pass

- **3 contradictions remain.** Inspect them via the analyzer before trusting the
  red section; the known residual is a same-event label on a different entity
  or venue (year proximity now demotes most, not all).
- **19 document-internal conflicts remain.** The locality/unit/metric-word rule
  removed 35 of 54; the residual pairs sit within three paragraphs and share a
  generic context word. The pre-existing timeline checker is not involved here.
- **228 unverified.** 123 are prose claims with no deterministic checker (each
  now carries a lead passage); the other 105 are numeric/quote claims where
  retrieval or formatting missed. This is the main remaining quality gap.
- **Glossary builder is unmeasured with the model.** The offline run produced
  105 pairs (1 verified, 33 retrieval-only, 71 unverified). The model proposal
  path is wired but has not been run against the real library; cross-script
  pairs stay retrieval-only by design.
- P4 (web UI) and P5 (private acceptance as a repeatable gate) remain separate
  goals. The acceptance above was a manual read-only run.
- `Ledgerline_New_Business_Proposal.docx` is untracked at the repo root. It is
  a course document: ignore or remove it before any commit; do not add it.
- Fixtures use synthetic names (`Acme`, `華光`) because the no-case-literal
  gate forbids the real case names in `app/`; the tested properties are the
  same ones the plan describes for the real pair.



## English-first (2026-10-28) — W0/W2/W2.5/W5

The deterministic English foundation is in place. Scope of this pass: an
English evaluation suite, bm25s retrieval with value-first ordering, claim
normalisation/evidence expansion, and precision guards. W1 (semantic prose),
W3 (citation metadata), W4 (MinerU scans), W6 (UI) remain separate goals.

```
.venv\Scripts\python.exe -X utf8 tests\run_eval_en.py --suite tests\eval_en
.venv\Scripts\python.exe -X utf8 tests\test_retrieval.py
.venv\Scripts\python.exe -X utf8 tests\test_claims.py
```

Definitions (do not quote the support rate alone):

- **Checkable** = numeric/quote claim. Prose has no deterministic checker and
  is **not checked** (visible, excluded from the denominator).
- **Support rate** = supported / true checkable.
- **False support** = supported claim whose passage lacks the subject/figure.
- **False contradiction** = `contradicted` on a claim expected to be absent.
- **Internal conflicts** = draft-internal value clashes.

Current synthetic suite (`tests/eval_en/`, committed, no case material):

```
SUITE: 50 true, 10 false, 10 prose
SUPPORT RATE: 100.0% (50/50)
FALSE SUPPORT: 0.0% (0/50)
NOT CHECKED: 10
FALSE CONTRADICTION: 0.0% (0/5)
INTERNAL CONFLICTS: 0
```

That 100% is a fixture baseline, not the 90% program target: the suite states
every true fact verbatim. The private English set is still the real measure.

What changed:

- `tests/eval_en/suite.py` + `tests/run_eval_en.py` — repeatable metrics.
- `app/retrieval.py` — bm25s (MIT, 0.3.15) passage index; no service/network.
- `app/corpus.py` — BM25 index, value-first passage lookup, neighbour expansion.
- `app/normalize.py` + `app/cli.py` — retrieval query resolves leading pronouns
  and appends verified alias forms; the displayed claim is unchanged.
- `app/judge.py` — BM25 + value + neighbour candidates, subject-token guard on
  support **and** contradiction (a value in another subject's line is never a
  verdict), so value-only matching cannot create a false green.
- `app/checks.py` — internal conflicts stay local: same unit, nearby paragraphs,
  shared metric word.
- `requirements.txt` — one new pinned dependency: `bm25s==0.3.15`.

Honest limits:

- The synthetic suite is exact-match by construction; it proves the machinery,
  not real-world recall. W0's private English set is still required.
- 123 prose claims on the Chinese stress test remain not-checked until W1; the
  overall ~90% target is not reached by this pass.
- bm25s is English-word oriented; Chinese still relies on the CJK tokenizer and
  value index.
- `app/retrieval.py` degrades with a warning if bm25s is absent, but
  `requirements.txt` now installs it.

### Subject guard + CJK entities (2026-10-28)

The adversarial dataset (20 cases, EN+ZH) found four real false supports that
the English fixture baseline missed:

| Failure | Cause | Fix |
|---|---|---|
| Caelum Labs supported by Caelum Cloud | subject checked against the whole 3-line passage | check the sentence that carries the value |
| Helios 2021 certification supported by 2021 clearance | both milestone words were unknown, so `event_of` returned `None` | `certification` / `clearance` event anchors |
| 恒宇健康 supported by 恒宇科技 | CJK "names" were 2-char bigrams; `恒宇` matched both | suffix-anchored `detect_cjk_entities` (集团/科技/健康/云/办公…) + full-entity/rival check |
| 恒宇集团 supported by 恒宇云 | same 2-char bleed | same |

Code: `app/textproc.py` (`detect_cjk_entities`, `entity_head`),
`app/judge.py` (`_names_present` entity anchor, `_value_sentence`,
contradiction checks the conflicting value's sentence), `app/cli.py` feeds
draft+library CJK names into `_doc_entities`.
`tests/test_subject_guard.py` (6 assertions) is in `tests/run_all.py`.

Gates after the change:

```
BYOS TESTS: PASS (48 assertions)
RETRIEVAL TESTS: PASS (8 assertions, bm25s 0.3.15)
CLAIM NORMALISATION: PASS (10 assertions)
SUBJECT GUARD: PASS (6 assertions)
ADVERSARIAL: PASS (15 assertions)
SUITE: 50 true, 10 false, 10 prose -> 100.0% (50/50), 0.0% false support
HOLDOUT: 40 true, 6 false, 6 prose -> 100.0% (40/40), 0.0% false support
ALL GATES: PASS
```

Chinese KS acceptance (read-only, same draft/library, `sources_only
--footnotes`):

| Metric | Before | After |
|---|---:|---:|
| supported | 75 | **78** |
| contradicted | 2 | **1** |
| unverified | 221 | 202 |
| no_source | 13 | 30 |
| internal conflicts | 19 | 19 |
| narrative | 108 | 108 |

+8 supports recovered, 5 lost, no new contradiction. The 17 extra `no_source`
rows are claims whose subject appears only in a previous paragraph (Chinese
prose drops the subject); they are honestly `no_source`, not false greens.
Known remaining leak: modality (`宣布` vs `预计`) is still `supported`; that is
W1 work, not a numeric subject error.

## Pipeline order (the contract)

analyze→extract (every sentence without a number/quote becomes a claim: `origin="sentence"`)
→ deterministic eligibility: mark_narrative (heading/question) + classify_prose
(LLM: FACTUAL vs COMMENT → `narrative`, visible, never searched)
→ judge vs BYOS corpus (deterministic grep, file:line evidence)
→ citation/fx/alias tagging → PLAN + budgets scaled to THIS doc
→ token web pass (keyword ladder + compact entity·figure rungs, early-stop;
  NUMBERS judged here deterministically — never deferred to the LLM again)
→ SOURCE-LED DEEP PASS (M1.8, replaced per-claim planned-query judging):
  cluster unverified claims by shared entities/vocabulary → 1–3 short queries
  per cluster → deep-read ≤3 pages ONCE → every figure judged by
  `_assess_number` against full-page passages, every prose batch judged in
  ONE `judge_pool` call per cluster → cross-claim snippet reuse → pool
  re-judge (backstop) → FX pairs (parenthetical conversions, arithmetic
  verdict) → structural/timeline/drift → reports (md/xlsx/jsonl/annotated/docx).

## Design rules (do not break without user sign-off)

1. **Cheap by design, explicit engine**: DeepSeek Search is the default
   ($0.75 per 1,000 successful requests; empty results are not billed) with
   Brave free credit as the explicit alternative; the LLM stays free-tier
   (Agnes). No auto chain: a run uses the engine the user selected, and the
   report names it. No other paid APIs.
2. **Evidence or honesty**: every verdict links a file:line, a snippet/passage, or
   an arithmetic proof; else `unverified` + why + a readable "try by hand" query.
   Never assert beyond evidence; never guess.
3. **No silent skipping**: every non-citation claim is attempted or marked unsearched
   with a reason. Time is a PREDICTION of the plan, never a deadline that cuts depth.
4. **Footnotes/endnotes = the source, not claims** (URLs inside still liveness-probed).
5. **"RMB X (about US$Y)"** = one money statement: judged by FX arithmetic
   (Frankfurter ≥1999; curated PBoC/IMF table 1978-1998, provenance shown). The web
   must never contradict the restated figure (today's rate ≠ 1990's rate).
6. **Modifiers matter**: "over 90%" is SUPPORTED by a 95% source, contradicted only
   by <90%. Sorted-token-bag queries are banned; `rare_phrase()` keeps reading order.
 7. **Early-stop > more searches**: escalate the query ladder when a query
    returned zero results; results that don't match are information — the ONLY
    exception is a DISTINGUISHING figure (decimal/exact: 15.68%, 22.89%,
    122,000): retrying with the sharp entity·figure query is not "a sloppier
    variant", it is the query a human would type. Contradiction has a HIGHER
    bar than support (same event or ≥3 non-name, non-unit words).
 8. **Prose is never verbatim-searched**: narrative claims → topical phrase queries;
    only real quoted text gets quoted into search.
 9. **Budgets scale, caps are sanity-only**: every budget — searches, pages,
    llm_calls AND llm_max_tokens — is derived from THIS document (the static
    token ceiling once starved every deep pass at call ~22: the silent
    "everything unverified" failure). Cluster reads cover the remaining claims.
10. **UI**: web+LLM always on (toggles hidden from users by design); the
    SEARCH-ENGINE selector (DeepSeek | Brave) IS exposed by user request
    2026-09-07 (the `backend` field on /api/check → WebEvidence.only; a
    selection without a usable key falls back to the other keyed engine, and
    with neither key the run is honestly web-unavailable — never a silent
    third vendor; reports label the engine that ACTUALLY ran). plan dialog
    (searches/deep/pages/LLM/time/coverage) must be confirmed before a run;
    progress = one live line + % bar weighted to where time REALLY goes
    (source-cluster pass 39%, keyword pass 8%) + an "Ns on this step" idle
    counter (heartbeats during LLM phases — "stuck at step 52" was a missing
    heartbeat). ONE run per visitor IP (409 + Stop button); a refresh must
    RE-ATTACH to the running job, never orphan it.
11. Circuit breakers: transient (429 storm) must not pin. DeepSeek Search and
    Brave use per-request caps (`SEARCH_DEADLINE`) and the run's search budget;
    there is no keyless breaker store to heal any more. A result set that never
    mentions the subject is treated as EMPTY, never trusted as evidence.
12. Original documents are NEVER edited; suggestions go to annotated copies.
13. **Conflicting sources ≠ unverified**: when retrieved evidence both supports
    and contradicts a claim (lego.com vs Wikipedia case), the verdict is
    `conflicting` with BOTH camps as evidence (side: support/contradict tags) —
    the engine never picks a side; the user decides keep/fix/dismiss in the UI
    (`POST /api/decision/{job}`), persisted to the job's `decisions.json` and
    re-rendered into claims.jsonl/report.md/report.xlsx.
14. **No LLM holds contradiction power**: any `contradicted` produced by an
    LLM (snippet OR passage OR pool judge) is demoted to `conflicting` in code
    — free judges ignore the lookalike-entity and tense rules they're given.
    Only deterministic guards (corpus judge, `_assess_number` predicate/time
    checks, FX arithmetic) may conclude `contradicted`.
15. **Numbers are judged deterministically, prose is judged in clusters**:
    never send a figure to the LLM when `_assess_number` can settle it (the
    free judge waved 20-snippet confetti 'unverified' while the page text
    carried the fact); never send a page back to 20 per-claim judge calls.
16. **Eligibility before effort**: heading/question/commentary claims become
   `narrative` (visible, reason-given, not searched, not counted pending) —
   essay prose flooding the pending column reads as "low quality" even when
   the engine behaves correctly.
17. **A guard that protects one verdict must equally protect the other**
   (added 2026-09-26). The corpus judge had a PREDICATE guard on the
   contradiction path only, so a line about a *different* milestone that
   happened to share a year produced `supported`: "Solaris Grid opened its
   Bergen plant in 2011" was backed by "Solaris Grid was founded in 2011"
   (5 of 5 such probes, all `supported (high)`, pre-fix). The rule is now ONE
   definition, `_predicate_ok()` in `app/judge.py`, called by both paths, so
   they cannot drift apart again. Consequence: `EVENT_ANCHORS` surface lists
   are load-bearing for correctness — an unrecognized event reads as "no
   event", which silently disables the guard on exactly the claims that need
   it (the KS cross-script case needed 宣布/問世 added, not the guard disabled).
   When a case-study number moves, the other path moves with it or not at all.
18. **A model may stand in for exactly one dimension, and only after the
   deterministic path has already declined** (added 2026-09-26). `supported`
   normally needs three things: the figure matches (`num_matches`), the
   milestone matches (`_predicate_ok`), and the subject overlaps lexically. The
   lexical subject bar is the weak one — it is blind to cross-script and
   paraphrased subjects — so a Jev `noul` may replace THAT check alone, and
   only inside `_subject_fallback()`, which runs after every deterministic
   path has returned. Properties this buys, all deliberate:
   - **Monotone**: it runs only on `unverified`, so it can add a `supported`
     and never alter one. Every failure mode is a lost recall gain, never a
     flipped verdict.
   - **The model holds no contradiction power** (reinforces rule 14).
   - **Deterministic preconditions first**: the figure and the milestone must
     already agree, and `tp.shares_subject()` must confirm the line actually
     names the claim's subject. That last one is not paranoia — on anaphoric
     evidence the model answers 0.85–0.93 regardless of truth, so asking it
     there is asking it to guess.
   - **Offline by default**: `run_all.py` exports `JEV_SUBJECT_FALLBACK=0` so
     the main gate stays deterministic and network-free. A corpus verdict being
     deterministic must not depend on whether a developer's `.env` has a key.
   - A model-rescued claim reports confidence `medium`, never `high` — the
     subject was not established lexically and saying otherwise overstates it.
19. **An explanation is not a second opinion (added 2026-09-26).** `supported`
   means three checks passed, so the report shows which three and how each went:
   `- ✓ same subject / ✓ same figure / ✗ same event — your claim is about
   launch, the source line is about founding`. Rules that keep it honest:
   - **Template only, no LLM.** Offered and declined. An LLM asked to explain a
     verdict smooths the caveat away ("the source confirms 2011"), which
     re-creates the exact false green rule 17 closed, in prose. Same reasoning
     as rule 18, one layer out.
   - **Recorded at the decision, not re-derived.** `judge._rec()` attaches the
     checks at each `return`, so the rows a user reads are the ones that
     produced the verdict. A re-derivation could drift and describe a decision
     that never happened.
   - **The judge records facts; `provenance.py` phrases them.** Details are
     `{"t": "event_mismatch", "claim": "launch", "line": "founding"}` — an id
     plus slots, never a finished sentence. All user-facing text lives in
     `provenance.DETAILS` as (en, zh) pairs, so a Chinese report gets a Chinese
     *reason* and not just a Chinese label. Half-translated is worse than none.
   - **The invariant worth testing** (not the wording): no `supported` may ever
     render a failed check. Also: unknown detail ids render empty rather than
     inventing a reason, and a finding with no checks at all still gets a
     headline, so prose/quote/structural rows are unaffected.
   - The model-assisted path says so, in both languages, so a `medium` from the
     Jev fallback is never mistaken for a deterministic match.
   - Named `provenance.py`, NOT `explain.py` — `enrich._explain` already exists
     and is a different pass (why a web search found nothing). They are
     complementary, and the near-collision would have cost an hour.


## Word counts

MS-Word-compatible (`textproc.count_words`): tables + text boxes + footnotes/endnotes
ARE read and counted (docx flattening in `extract.read_doc` — python-docx .paragraphs
alone lost ~30% of the Kingsoft case study). Quota counts words, not bytes.

## Known limits / next steps

- M1.12 green-audit pass (user caught 2 false greens in 13: "supported 13 but
  actually 11" — I was reporting matchers' output as truth; audit the
  EVIDENCE TEXT, not the verdict). Three general lies fixed, each pinned by a
  non-KS unit assertion (units now 119):
  (1) 'the 1990s' matched year 1990 — YEAR_RE now rejects decade/'s forms on
  BOTH doc and snippets;
  (2) lookalike-name cross-script greens (张旭龙 — the LLM's WRONG native for
  Zhang Xuanlong — anchored a Kingsoft date to a stranger's pages; and
  company+year alone: 'Kingsoft…2021…stock news' 'supported' a 2021 dinner
  anecdote) — the relaxation now demands TWO distinct document entities
  adjacent (touching, not windowed) to the figure (user's precision-over-
  recall choice: company-only milestone years need a 2nd co-named entity);
  (3) 'Room 501' matched Kingsoft's own HKEX OFFICE ADDRESS via the
  distinctive-value bypass — IDF labels are never self-anchoring figures
  (checks.py already knew; web.py didn't).
  RESIDUAL (honest): a company's OWN encyclopedia page that states the claim's
  year near any second document entity still supports a bare event-year
  (2021) — cross-lingual same-event matching is the only way to reject it
  and that is an LLM-pool-judge job (7-10 calls/run; the cyzone hospital-ward
  passage already sits in the pool waiting for it). Prose unverified count is
  therefore partly an LLM-budget question, not search quality.

- M1.11 SERP-chrome guard (user caught it in ddgs-only mode): DuckDuckGo/Google
  leak their UI into snippets — '缺少字詞：Qiu Bojun november exhibition old
  1991' = the engine confessing the PAGE LACKS our query terms while ECHOING
  them back; the echo carried the entity + the figure, so a generic 'Major
  events in computer science in China' hub page passed the anchor, the number
  match and even the cross-script proximity relaxation and appeared as
  evidence, repeatedly, for claims it never mentions. Fixed: (1)
  tp.clean_snippet truncates body+title at the chrome marker at the ONE
  search() chokepoint (cache/pool/UI all downstream), (2) _cjk_near: a
  cross-script figure match must sit beside actual CJK ('1991年', not
  'old 1991'), (3) plan_queries gets an explicit keyword-hygiene rule. 7 new
  unit assertions incl. an end-to-end monkeypatched junk-SERP that must never
  settle a claim. Live ddgs-only KS: chrome gone, hub rejected, 1991 backed
  by 3 real CJK sources (mi.com/zhihu/sina). NOTE: ddgs-only green-rate is
  measurably lower than brave (10 vs 13-14 of the same doc) — the UI engine
  selector lets the user compare directly.

- M1.10 depth/honesty/UI pass (user QA on the KS section): the deep pass no
  longer TRUNCATES clusters (`_deep_cluster_cap` deleted — a static cap left
  62/193 searches idle and mislabeled the starved claims "outside the cap";
  visit loop is bounded ONLY by budget/time/cancel, clustering is lossless
  per the new unit invariant). Read-page PASSAGES now join the snippet pool
  (`add_passage_pool`; pool-judge dedupes per source, richest text wins) —
  a page fetched for one figure can settle another claim's anecdote for free.
  Suggestion/quality: `_prop_words` (mid-sentence capitals only — killed
  "Kingsoft Even"), compact-ladder latin rungs filtered isascii (killed
  bigram confetti "的今 的明"), pronouns/connectives into STOP (even/his/…),
  the doc's OWN Chinese phrases become quoted queries & lead the "try by
  hand" list (`cjk_runs`; verify_quote + cluster rungs + _explain), numeric
  suggestions lead native entity·digit ("求伯君 30000"), bare-entity
  suggestions/bare-entity searches banned in _apply_narrative. UI: engine
  selector (Auto/Brave/DuckDuckGo → /api/check `backend` → WebEvidence.only;
  unusable choice normalizes to auto; report labels only engines that RAN)
  and narrative verdict now BLUE (page.js + xlsx BDD7EE). KS live after:
  "outside cap" gone, 13-14/25-29 green, brave-vs-ddgs A/B verified on the
  Sony scratch case (brave: 6+1 contradicted; ddgs: 4).
- M1.9 cross-script quality pass (the EN-doc-about-CN-subjects "too many
  unverified" campaign): extraction stopped swallowing checkable numbers
  (month-before-year is a DATE not a product version; 'lines/copies/行/本'
  count nouns; hyphenated word-ages; spelled hundreds); the query planner now
  types the native-script entity·figure queries (求伯君 1984) it previously
  only suggested as "try by hand" — Latin↔CJK pairs come from
  resolve_subject's people/people_native zip (WebEvidence.entity_pairs),
  ranked: sentence-mention > doc-frequency (pronoun sentences lead with the
  SUBJECT, not whoever's named first); cross-script SUPPORT needs figure
  PROXIMITY to the query's own entity in the snippet (张旭龙-author-list
  lookalikes fail it — the 1984-green now cites 百度百科's "1984年，毕业于
  国防科技大学"); IDF labels (room 501) can never be contradicted by an
  unrelated figure; generic place tokens (Beijing/Wuhan) are banned from the
  entity-anchor set (they let an HRW PDF "support" a 1991 claim); count-claim
  internal-conflict needs >=3 shared words (2 linked an age to lines-of-code
  via "word processor"). Kingsoft section: 26%→38% green, false greens gone,
  stale "reserved for deep check" reason replaced with honest "outside
  cluster cap". REMAINING: prose/event lane still weak (garbage short
  queries like "Kingsoft Even"; CJK verbatim in parenthetical quotes not
  extracted; prose can only be judged by the LLM pool vs read pages —
  non-deterministic run to run); deep-cluster cap leaves ~4 event claims
  unvisited on small docs.
  GENERALITY (not a Kingsoft special-case): every M1.9 rule is data-driven
  and pinned by NON-KS unit fixtures (Sony/Matsushita, New York Times,
  Nimbus) — no KS name in any branch, only in illustrative comments. The
  cross-script path fires for ANY CJK subject (proven on 松下電器), not just
  Chinese; the entity-anchoring is generic (locative-preposition rule, so a
  city in NO gazetteer like Kobe is still dropped); count nouns are measure
  words (units/items/台/部), not "N lines of code". A generality bug the
  non-KS test caught: cross-script entity match compared a t2s-normalized
  entity against the RAW query, so a traditional-script query ('松下電器')
  missed its simplified snippet — fixed by normalizing the query too
  (test_units has the traditional/simplified case). A second real web case
  (EN doc about Sony) goes green via the same path: 11 searches, 7/11
  supported, cross-script evidence on the TR-55/original-name claims.
  test_blind_lego (a THIRD subject, Danish) still PASS.

- M1.6 speed/visibility pass: every LLM call has a hard 90 s wall-clock deadline
  (`llm._with_deadline`; a chunked-but-trickling provider never trips socket
  timeouts — the "13-min plan, 2 h actual" trap), the whole-doc semantic scan is
  chunked to 10 paragraphs/call with progress events, and the SSE gains
  `webpass_done` / `deepdone(done/total)` / `reporting` so the bar matches reality.
- M1.7 quality pass (the "too many unverified" campaign): claims triage into
  FACTUAL vs COMMENT (LLM batch + deterministic heading/question floor →
  verdict `narrative`, visible but never searched/pending); CJK queries go
  entity-first to zh.wikipedia (Western surrogates return garbage for Chinese);
  deep-reads Ctrl+F by rare-token overlap, not entity first-mentions; the query
  planner gets AUTHORITATIVE native spellings (free models invent wrong
  characters otherwise — 求伯君→邱伯均); llm_max_tokens scales with the plan
  (the static 60k ceiling silently starved every deep pass at call ~22);
  ddgs joins SearXNG in the 15-min breaker store; undated figures can never
  contradict dated claims; snippet-level contradiction of PROSE claims demotes
  to `conflicting` (user decides — snippet judges misread tense). Random
  paragraph of the real Kingsoft draft: 4/6 supported with source links,
  1 conflicting (shareholding tension, real), 1 unverified + hand queries,
  67 s / 18 searches / 12 LLM calls.
- M1.8 source-led pass + official-API lanes (this session): per-claim planned-
  query judging REPLACED by source-cluster reads (group claims by shared
  entities/vocab → 1–3 short queries/cluster, human-shaped: entity+figure,
  native script, decimals first → read ≤3 whole pages once → numbers judged
  by `_assess_number` on passages, prose by ONE judge_pool call/cluster).
  A 250-word section: ~90 LLM calls → ~6, 2–15 min → ~60–140 s. Windows from
  rival claims now MERGE (a window-overlap skip silently deleted the '15.68%'
  passage); every visited cluster's claims get honest attempt marks (stale
  "reserved for deep check" reasons lied about coverage). Backends now:
  Google CSE (wired but UNUSABLE — Google closed JSON-API signup for new
  projects; keys commented in .env) → Brave (KEY LIVE in .env; new prepaid
  console = $5 free credit/mo ≈ 1,000 queries; parser handles BOTH
  web.value and web.results schemas + extra_snippets) → ddgs (region-pinned:
  cn-zh for CJK, wt-wt else; 6-consecutive-failure 15-min breaker) →
  SearXNG (locale/region for CJK; engines PINNED "bing,mojeek" — captcha'd
  ddg/brave/startpage engines crash SearXNG's whole combined response to 0)
  → Wikipedia API (entity-only CJK queries; AND-soup returns unrelated).
  The `llm.exhausted`-at-22-calls starvation (static token ceiling) killed
  whole deep passes silently — budgets derived from the plan, always.
- **PENDING ACCEPTANCE TEST (user asked to save it)**: run the Kingsoft
  section (or the whole ACRC draft) WITH the user's source materials attached
  as BYOS "source" files — internal-fact docs (Xishanju MBO terms, 26-of-40,
  80% debt, Xiao Pin anecdote) are NOT on the public web at all; only BYOS
  verdicts can close them, deterministically. Until that run exists, do not
  judge web quality by those claims: expected ceiling for web-only =
  mainstream figures (15.68%, 22.89%, dates, IPO) green; internal terms
  honestly unverified + hand queries.
- Keyless search is flaky by nature: ddgs h2 errors under burst; the bigger
  trap is SILENT geo-poisoning (DDG/Bing serving Camry/YouTube for serious
  queries when the IP is storm-flagged) — the subject-anchor gate
  (`_take`/`_mentions_entity`) must keep rejecting those sets. Brave (key)
  is the stable lane; keep it first-class but count quota (~1k runs/mo).
  Never promise determinism in web verdicts (corpus verdicts ARE).
- ~9k-word doc at full contract ≈ 60–90 min; sweet spot per run is 1.2–1.8k words.
  "Section mode" (split, merge reports) would be the natural next feature.
- Estimate constants (SEARCH_S/LLM_S) were fit on this machine + Agnes; recalibrate
  after 5+ more runs.
- Consider: per-source credibility tiers beyond community/published; PDF text-box
  coverage; test_blind_lego in CI (network-gated).
- **JEV (`JEV_API_KEY`, free tier) is retrieval-only, never a verdict.** It is a
  structured-classification endpoint (`POST https://api.typesafe.ai/v1/systemone`,
  `model=jev-latest`, observed `jev-1.13.0`): it returns choices/noul, never
  prose, so it CANNOT write a verdict or a `file:line` — rule 2 + rule 14 hold.
  Measured on an 18-pair benchmark (`tests/test_jev_gate.py`, network-gated):
  isolated 18/18, recall 1.000, false-green 0.000; batched per-claim 16/18
  (false-green 0.182); batched all-at-once 14/18 (false-green 0.364).
  **Batching unrelated evidence into one context is unsafe** — recall collapses
  under distraction, which is silent because the call still succeeds. Do NOT
  re-litigate this: `tests/test_jev_gate.py` gates the isolated shape for
  correctness and holds the batched shapes only to their recorded baseline.
- **Jev is NOT a useful line RETRIEVER, and that was worth measuring.** Building
  it as one recovered 0 extra claims: Jev ranks the right line first almost
  always, but `find_lines()` is keyword-gated, so a better ranker cannot rescue
  a line that was never a candidate. The binding constraint is the judge's
  lexical subject bar (`shared_n >= 2` shared NON-NUMERIC tokens). What Jev is
  good at is exactly the thing that bar cannot do — judging subject identity
  across scripts.
- **A model may stand in for the ENTITY check and nothing else** (rule 18).
  `app/jev.py` + `_subject_fallback()` in `app/judge.py`. Measured on named-
  entity pairs, where the line names the wrong organisation the model answers
  0.03 and where it names the right one 0.99 — a wide, reliable margin
  (`tests/test_jev_entity_risk.py`: recall 1.000, false-green 0/6).
- **Jev's blind spot is ANAPHORIC evidence, and it is not subtle.** On "The
  company was founded in 1994…" the subject is never written down, so there is
  nothing to contradict and Jev answers 0.85–0.93 — confident, and useless.
  So the fallback may only be consulted on lines that actually name the claim's
  subject, tested deterministically by `tp.shares_subject()` (which excludes
  digits, stopwords, generic placeholders and all predicate vocabulary, because
  two anaphoric texts share ONLY the predicate). Without that precondition the
  fallback would manufacture false greens on same-year/same-event/wrong-entity
  lines. Part 2 of the entity-risk test is the gate that matters: 7/7, 0 false
  greens.
- **Correction to an earlier claim in this file:** Jev is far more stable than
  first measured. A controlled 2×2 (sequential/concurrent × one/two payloads)
  shows spread ≤0.04 everywhere and clean separation 0.99 vs 0.03, so
  concurrency does NOT corrupt responses (16 workers, ~15×, no drift). An
  earlier "0.98 spread / concurrency corrupts" reading was MY OWN BUG — results
  grouped by `i // REPS` while the job list was reps × cases, so each "case"
  row mixed cases. Group results by carrying the case index in the job tuple.
  Two probes also disagreed only because they asked DIFFERENT questions
  (support-instruction vs subject-instruction) — always state the instruction
  when comparing Jev numbers.
- **CORRECTION — I was wrong about `NEW_AGNES_API_KEY`.** I recorded it as
  "structurally valid but unusable (`401 Invalid token`), do not wire it in".
  That was a **host-scoping error, not a dead key**: I had probed it against
  the hardcoded `apihub.agnes-ai.com` and generalised. The user then showed it
  working on `https://tonewapi.duckdns.org/v1`, and it is a real, fast,
  fully-featured key. **Lesson: a 401 from one endpoint says nothing about the
  key.** The same key 401s on the official host and succeeds on the relay.
  Before writing off a credential, enumerate its host — ask, or read the
  provider's docs — never infer from one endpoint. I would otherwise have
  silently discarded a working key on the strength of a single wrong URL.
- **Second Agnes host, tried FIRST (user's explicit call), official behind it.**
  `llm.py`: `AGNES_RELAY_URL` / `NEW_AGNES_API_KEY`, then `AGNES_URL` /
  `AGNES_API_KEY`. Measured on the relay: 6/6 calls, 0.70/1.00/2.82s,
  `response_format: json_object` returns valid JSON, identical answers at
  temperature 0, a 24k-char / 7,236-token prompt in 1.2s, 8 concurrent calls
  with 0 errors. So it is not a degraded path — it is the good one.
  - `_openai_candidates()` replaces the single-pick provider branch with an
    ordered list of `(url, key, model, name)`, tried in turn.
  - **The candidate tuple is passed in, never re-derived from an index.** My
    first version passed `ci` and re-resolved the list inside the call; the
    breaker can change that list mid-loop, so the same index would have called
    the wrong host. Pinned by a test.
  - **A 401/5xx/DNS failure falls through and is counted, not absorbed.** The
    report gains an `LLM provider` line, plus `(relay failed Nx this run; the
    official host took over)` when it happened. A shared relay is not something
    to depend on quietly.
  - **Breaker after 3 consecutive HARD failures**, so a lapsed relay costs one
    timeout rather than one per call. A 429 is explicitly excluded: busy is not
    dead, so it falls through for that call without retiring the host, and (as
    the pre-existing `rate_limited` carve-out already argued) must not set
    `net_dead`. Both are asserted.
- **`.env` is NOT auto-loaded for the main app.** Only `app/jev.py` has a
  `_load_env_file()`. `AGNES_API_KEY` reaches the app only because it is
  exported in the environment — so **`NEW_AGNES_API_KEY` must be exported too**,
  or the relay-primary ordering is inert and only the official host is in the
  chain. Deliberately not changed: making every `.env` key load implicitly is a
  posture change (it would auto-load `OPENAI_API_KEY`, `GROQ_API_KEY`, …), and
  it is not mine to make silently.
- `NEW_AGNES_API_KEY` is now read by the app (it was dead `.env` weight before).
  The official host's model list is unchanged and still worth remembering:
  `agnes-2.5-flash` / `agnes-3.0-flash` answer, pro models return
  `403 insufficient_user_quota`, and `agnes-2.0-flash` times out. The relay
  lists only `agnes-2.5-flash`.
- `NEW_AGNES_API_KEY` appears in plaintext in this session's transcript. If that
  transcript is shared or logged anywhere, **rotate the key** — it is a
  credential, and a DuckDNS relay key is trivially reusable by anyone who has it.

## 2026-09-26 session — verdict provenance in the report (code changed)

Third session on 2026-09-26. Added `app/provenance.py` (new) and wired it into
`app/judge.py` (`_rec`, `_event_detail`) and `app/report.py` (markdown block,
`Why (checks run)` xlsx column, `explanation` field in the JSONL record).
`tests/test_units.py` 138 → 164 assertions. All 7 main gates PASS; the four
network-gated tests still PASS.

- **What the user gets now.** Every number row states which checks ran and how
  each turned out, so `unverified` stops being a shrug:

  ```
  **Could not confirm this one**
  - ✓ Same subject — source names the same subject
  - ✓ Same figure — the figure 2011 does appear in the source
  - ✗ Same event — your claim is about launch, the source line is about founding
  ```

  That last line is the whole point: it teaches the method at the exact moment
  someone would otherwise conclude the tool is broken.
- **Two record-layer bugs I introduced and caught before shipping.** `to_record`
  first stored a *live reference* to the finding's `explain` dict, so mutating
  a finding after serialization would silently rewrite a written record; it now
  copies field by field. And the explanation had to round-trip through
  `from_record`, because `rerender_with_decisions()` re-reads the JSONL when a
  user records a decision — a missing key would have dropped the checks from
  every re-render. Both are now asserted. I stored the RAW structure rather
  than rendered text, so a re-render in a different language still localizes.
- **`_rec` had a comprehension bug**: `for k, (s, d) in order if s` unpacks
  before the filter, so a skipped check raised `TypeError` on `None`. Only
  visible by actually running the demo — ruff and reading it did not catch it.
- **THE BIG ONE — I destroyed a test file with a shell command.** To rename a
  variable I ran
  `(Get-Content tests/test_units.py -Raw) -replace ... | Set-Content -Encoding UTF8`.
  PowerShell 5.1's `Get-Content` read the UTF-8 file through the ANSI codepage
  and `Set-Content` wrote the mojibake back as UTF-8: every CJK literal in the
  file was destroyed, irreversibly (`2011年成立` → `?011年?立?`, literal `?` for
  every unrepresentable char). 173 ruff syntax errors. I recovered by
  `git checkout` (HEAD was intact at 126 assertions) and re-applying my three
  additions, and rewrote all CJK as `\uXXXX` escapes so it cannot recur.
  **NEVER edit a source file with Get-Content/Set-Content, redirect, or `sed`.
  Use the edit tool.** A rename is not worth a whole file, and the console was
  already showing me mojibake for these exact lines — I had written that lesson
  down earlier in this same session and still walked into it. When a file has
  CJK, prefer `\uXXXX` escapes in source over literals, and verify by running
  the file, not by reading the diff.
- Left the pre-existing `web/out` build artifacts untouched; nothing committed.


## 2026-09-26 session — corpus-judge false green fixed (code changed)

Second session on 2026-09-26 (the recon session below was read-only). Changed
`app/judge.py`, `app/textproc.py`, `tests/test_units.py`; `HANDOFF.md` updated.

- **The bug**: BYOS `supported` had no predicate guard, so a figure matched on a
  line about a different milestone. 4 non-KS false greens reproduced (founded vs
  plant opening / title launch / supplier acquisition / fundraise vs office
  closure), all `supported (high)`.
- **The fix**: one shared `_predicate_ok()` for both verdicts (rule 17), plus the
  anchors the corpus actually uses (`announce/introduc/open/rais`, and
  宣布/問世 for the cross-script pair). Off-event lines now return `unverified`
  with the reason "mentions N at file:line, but that line is about a different
  event" — honest and actionable, rather than a bare "value not confirmed".
- **Pinned**: 6 new assertions in `tests/test_units.py` (126 → 132) — 4
  off-event must-stay-unverified, 1 genuine match must-stay-supported, 1
  cross-script anchor pair. `test_blind_lego.py` 8/8 on the independent Danish
  LEGO corpus, so the guard did not over-tighten.
- **Then the Jev subject fallback** (rule 18): `app/jev.py` (new),
  `app/judge.py`, `app/textproc.py` (`shares_subject`), `tests/run_all.py`
  (offline pin), `tests/test_jev_entity_risk.py` (new, network-gated).
  Assertions 132 → 138. All 7 main gates PASS plus all 4 network-gated tests.
- **SELF-INFLICTED REGRESSION, and the lesson.** Mid-session, KS precision fell
  95% → 62% and `K1b_predicate_guard` began returning `contradicted`. Cause: I
  had "refactored" a regex in `name_tokens()` from `(?=于|在|从)` (prepositions —
  the name-capture that makes 求伯君于1986年 parse) to `(?=说|稱|称)` (speech
  verbs). CJK arrives in my editing context as mojibake, I transcribed what I
  could not read, and the edit tool matched anyway. It presented as a logic
  bug in the predicate guard and cost a long wrong diagnosis. **Never retype a
  CJK literal you cannot read back** — splice the original bytes from
  `git show HEAD:<file>`, and after any CJK edit run a functional check (does
  `name_tokens()` still find 求伯君?) rather than trusting the diff, which is
  mangled in the console too. Same for new CJK: a wrong character in
  `EVENT_ANCHORS` silently disables a guard, and a wrong character in
  `_GENERIC_SUBJECT` silently stops the anaphoric precondition firing.
- **Three of my own measurement errors this session, all caught by re-checking
  rather than by reasoning**: (a) results grouped by `i // REPS` over a
  reps × cases job list, which manufactured a phantom 0.98 instability and a
  phantom "concurrency corrupts responses" conclusion; (b) comparing two Jev
  numbers taken with different instructions; (c) test fixtures that I assumed
  exercised the fallback but which the alias map or tokenisation resolved
  deterministically, so the fallback path was never hit. Fix: make the test
  prove it reached the code it is testing (assert on the confidence tier, which
  differs between the deterministic and model-assisted paths).

## 2026-09-26 session — read-only recon, no code changed

This session was **investigation and planning only**. No source file was
modified; the working tree carries no new code from this session (the
`web/out/*` entries in `git status` are the pre-existing rebuild artifacts,
untouched here). Treat everything above as still true.

### Read and confirmed

- CheckMato is a real, working local prototype, not a mock: deterministic
  corpus verdicts, source-cluster deep pass (M1.8), SSE progress, per-run
  budget derivation, and a documented REST surface all exist in `app/`.
- The motivating case study is real: a bilingual Kingsoft/ACRC draft with
  ~75 footnotes and multiple revised versions — hence the emphasis on
  version drift, bilingual figure checks, and "same number, different base"
  conflicts. Origin story is recorded in `PRD_factcheck_tool.md`.
- The pending acceptance test at line 270 above is still genuinely pending;
  BYOS has never been exercised end-to-end on real source material.
- Known production gaps remain as documented: job state is in-process, so a
  restart loses active runs; retention/deletion of stored documents is not
  enforced; no external-user validation exists.

### Plan agreed for the next sessions (nothing implemented yet)

1. **API cost controls (highest priority).** Add hard per-run ceilings that
   scale with document size but cannot be exceeded, surface provider + call +
   token usage in the CLI, the report, and the web UI, and stop `--llm` from
   implicitly enabling web search. Config keys intended:
   `llm_call_ceiling` (default 60) and `llm_token_ceiling` (default 120000),
   plus per-run overrides `--llm-max-calls` / `--llm-max-tokens`. The current
   `llm_max_tokens` scales with the plan but a runaway loop can still burn the
   whole allowance, so a separate ceiling is the gap.
2. **BYOS acceptance.** Sanitize a copy of the Kingsoft section plus its
   internal-fact source files, run it as BYOS "source" material, and record
   the honest verdict mix. Use local/sanitized fixtures only — do not send
   confidential case material to a third-party LLM relay.
3. **Provider flexibility.** Agnes is the working provider; the OpenAI-
   compatible path (`OPENAI_BASE_URL` / `OPENAI_MODEL`) already exists for a
   second key when cost or limits demand it. No new provider is required for
   step 1; treat any relay as unverified until base URL, model name, usage
   reporting, and rate limits are all confirmed locally.
4. **Hardening (later).** Persistence/retention/deletion and a restart-safe
   job store. No target-user pilot — the owner declined it; rely on
   secondary market research instead.
5. **Assignment.** 500-word Personal Reflection + 1,000-word Innovative Idea
   (both compulsory), by KWOK Pak Yin Issac (25218506). Target market:
   final-year HK business/econ/social-science undergraduates (~21–24) doing
   evidence-heavy case studies. Part B needs several concrete cited data
   points from reputable secondary sources; the CheckMato cost-control and
   BYOS acceptance work above is the raw material for both sections.

### Do not

- Do not claim production deployment, passing tests, external validation, or
  persistence until each is actually verified by a run.
- Do not paste real API keys into chat, commits, or `checkmato.toml.example`.
- Do not re-litigate the pipeline order or the M1.8 source-cluster design in
  this file; those decisions are settled above.
