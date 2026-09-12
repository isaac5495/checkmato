# CheckMato — Handoff

Status: 2026-09-06 (M1.8) · all gates green · web tool live · Brave Search key
in `.env` (Google CSE attempted: Google closed JSON-API signup, keys disabled).
Written for whoever picks this up next (AI session or human) so today's
decisions don't get re-litigated.
Product spec stays in `PRD_factcheck_tool.md`; this file is "what is true NOW".

## Run / stop / test

- Start: double-click `start.bat` (or run its Start-Process line) → hidden server
  on http://127.0.0.1:8000; UI is served by the same process from `web/out`.
  Use **127.0.0.1**, not `localhost` (IPv6 refusal trap). Stop: `stop.bat`.
- SearXNG (second search backend, optional): `docker compose -f deploy\searxng\docker-compose.yml up -d`
  → 127.0.0.1:8888, localhost-only ON PURPOSE (a public instance = free proxy for the
  world, gets your IP blocked by Google). Enabled via `searxng_url` in `checkmato.toml`
  or env `SEARXNG_URL`. JSON format only works because `deploy/searxng/searxng/settings.yml`
  enables it (plain image refuses).
- Gate after EVERY change: `.venv\Scripts\python.exe tests\run_all.py` (ruff lint +
  7 suites, ~1 min). `test_blind_lego.py` (network, anti-overfit) is NOT in run_all — run it
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

1. **$0 by design**: keyless ddgs + self-hosted SearXNG + Wikipedia API +
   free-tier LLM/search keys only (Brave free credit, Agnes). No paid APIs, ever.
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
    SEARCH-ENGINE selector (auto | Brave | DuckDuckGo) IS exposed by user
    request 2026-09-07 (the `backend` field on /api/check → WebEvidence.only;
    a selection without a usable key normalizes to auto; reports label the
    backends that ACTUALLY ran). plan dialog
    (searches/deep/pages/LLM/time/coverage) must be confirmed before a run;
    progress = one live line + % bar weighted to where time REALLY goes
    (source-cluster pass 39%, keyword pass 8%) + an "Ns on this step" idle
    counter (heartbeats during LLM phases — "stuck at step 52" was a missing
    heartbeat). ONE run per visitor IP (409 + Stop button); a refresh must
    RE-ATTACH to the running job, never orphan it.
11. Circuit breakers: transient (429 storm, geo-block) must not pin; SearXNG-
    and ddgs-down persist 15 min via `.breakers.json` so restarts don't re-pay
    timeouts. Keyless engines geo-poison silently (Camry/YouTube results for
    Kingsoft queries): a result set that never mentions the subject is treated
    as EMPTY and flows to the next backend — never trusted as evidence.
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
