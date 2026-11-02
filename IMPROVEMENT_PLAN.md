# CheckMato improvement plan — English-first, evidence-first

Status: W0 (synthetic baseline) + W2/W2.5/W5 implemented; W1/W3/W4/W6 open ·
2026-11-02
Basis: the BYOS P0–P3 implementation, the read-only KS acceptance run, the
non-supported analysis (`reports/byos/non_supported_analysis.docx`), and the
open-source survey (MiniCheck, AlignScore, HHEM, Erlangshen, bm25s, BGE-M3,
MinerU, PaperQA2, RefWarden, CiteGuard, RAGAS).

## 1. What is verified today

The engine works on English and Chinese; language is a property of the draft and
library, not a fork. The Chinese case was the harder stress test and exposed
language-neutral gaps.

Acceptance run on the Chinese draft (446 findings, 7 sources, 6,634 lines, 0
network, ~8 s):

| Outcome | Count | Meaning |
|---|---:|---|
| supported | 80 | value + milestone + subject checks passed |
| unverified — prose | 123 | no figure/quote, so no deterministic checker ran |
| unverified — value missing | 80 | subject found, exact value not confirmed |
| unverified — milestone differs | 16 | figure found on a paragraph about another event |
| demoted contradictions | 5 | conflicting value, but subject/year match too weak |
| quote paraphrase | 4 | closest source is not verbatim |
| contradicted | 3 | kept; entity/venue collisions remain |
| internal conflict | 19 | two metrics share generic context |
| deferred URL | 6 | liveness needs web |
| paraphrase flag | 2 | close but not exact |

Verified causes (not guesses):

1. **Eligibility was wrong before retrieval.** Word headings and footnote
   citations were judged as claims. Fixed: headings/citations are `narrative`.
2. **Retrieval ranked by words, never by the figure.** Fixed partially with a
   line/passage value index; supported rose 60 -> 80.
3. **Internal conflicts compared metrics across chapters.** Fixed partially
   with locality, units and metric words; 54 -> 19.
4. **Year contradictions were context years.** Fixed partially with event and
   subject proximity; 5 -> 3.
5. **Prose has no checker at all.** 123 items stay unverified by design.
6. **Scanned PDFs are only flagged.** No local OCR/import path.

## 1a. Target: support rate, not abstention rate

The case-study author's ground truth (2026-10-28): **~90% of the checkable
claims are true and supported — by the supplied sources or by the public web.**
An unverified item is therefore more likely a retrieval/normalisation failure
than a false claim. The product must PROVE the true claims; honesty is the
floor, not the goal.

Definitions that keep the number meaningful:

- **Checkable claim** = numeric/quote claim + factual prose. Excludes narrative
  (headings, questions, commentary), citation text, URL liveness and derived
  internal-conflict rows.
- **Support rate** = supported / checkable. This is the headline metric.
- **False-support rate** = supported rows whose passage lacks the claim's
  figure, subject or event. The guardrail; must stay ≤ 2%.
- **Not-checked rate** = prose with no semantic pass. Must be visible, never
  folded into "unverified".

Targets:

| Mode | Support rate | False support | Note |
|---|---:|---:|---|
| `sources_only` | ≥ 80% | ≤ 2% | sources are expected to carry most facts |
| `sources_then_web` | ≥ 90% | ≤ 2% | web fills the rest; every card labels its origin |
| `web_only` | ≥ 90% | ≤ 2% | for public facts; weakest provenance |

Current Chinese run: 80 supported of ~313 checkable ≈ **26%** (123 prose not
checked, 105 numeric/quote unmatched). The gap is recall, not truth. Hitting
90% means roughly 280 of those 313 must be proven, with the same locator and a
false-support ceiling.

## 2. Invariants that stay

- Evidence or honesty: every verdict shows a locator; otherwise `no_source`
  (nothing supplied) or `unverified` (checked, not settled).
- No model holds contradiction power. A model may add `supported`/`conflicting`;
  only deterministic guards may conclude `contradicted`.
- No case answers in `app/`. Rules are general patterns or data tables.
- `sources_only` stays zero-network. Semantic models are local and opt-in.
- Retrieval and judging remain deterministic-first; semantic passes are
  additive and gated by a held-out false-support test.
- Every change ships with a fixture that does not mention the case under test.

## 3. English-first architecture

One pipeline, three adapters:

```
draft + library
   -> extraction (docx/md/pdf)            language-neutral
   -> value/alias/entity index            language-neutral + per-language tokenizer
   -> deterministic judge                 language-neutral
   -> optional semantic judge (NLI)       per-language model
   -> report / audit / corrections        language-aware labels
```

Language selection is explicit: `language = "en" | "zh"` in the manifest/draft,
`--lang` override. Default is `en`. A Chinese draft against an English library
still runs but is labelled cross-script and capped at `medium`.

## 4. Workstreams

### W0 — English baseline and evaluation set (2–3 days)

Why: the current acceptance data is Chinese, so English quality is unmeasured.

- Build an English golden set of 100–150 claims from public papers/drafts plus
  10–20 real student-style drafts. Two libraries: one small (10–20 docs), one
  large (100+ docs).
- Labels per claim: true/false/unsupported-independent of the engine, plus the
  expected verdict. The case-study prior is ~90% true.
- Metrics: **support rate** (primary), false-support rate (guardrail),
  not-checked rate, false-contradiction rate, footnote anchor precision, run
  time.
- Store as a private, gitignored `tests/eval_en/`; commit only synthetic
  fixtures.
- Exit: a repeatable `python tests/run_eval_en.py` that prints the metrics and a
  diff against the previous run.

### W1 — Semantic judge for prose (3–4 days) — critical path

Why: 123 of 228 unverified are prose; the 90% target cannot be reached without
checking them. The install stays optional; the mode is opt-in, the capability is
core.

- `app/nli.py`: lazy-loaded adapter, two backends:
  - English: `MiniCheck-Flan-T5-Large` (MIT, 770M) — claim vs document.
  - Chinese: `Erlangshen-Roberta-330M-NLI` (Apache-2.0) or
    `mDeBERTa-v3-base-mnli-xnli` (MIT).
- Premise = top 3 passages from the value/BM25 retrieval; hypothesis = the
  claim sentence. Batch, cache, CPU-first.
- Mapping: entailment ≥ threshold -> `supported` (medium); contradiction ->
  `conflicting` (never `contradicted`); neutral -> `unverified` with the lead.
- CLI `--semantic`; optional extra `requirements-semantic.txt`. Base install
  and all gates stay unchanged.
- Exit gate: on the W0 true-prose set, recall ≥ 80% with false-support ≤ 2%.
  If it fails, the mode stays off and prose stays "not checked".

### W2 — Retrieval upgrade (2–3 days) — critical path

Why: 80 value-missing and 16 milestone-mismatch items remain; value indexing
helped but ranking is still lexical.

- `bm25s` (MIT) over passages, with the value index as the first filter.
- Rerank top 20 by: value match > entity proximity > event match > BM25.
- Optional BGE-M3 (MIT) embeddings behind the semantic extra; no vector server,
  numpy only.
- Exit: recall@5 on W0 improves ≥ 15 points; support rate +10 on numeric
  claims; no increase in false supports.

### W2.5 — Claim normalisation and evidence expansion (3–4 days)

Why: a long sentence mixes facts, pronouns hide the subject, and aliases split
the same entity; retrieval then misses a true claim that is present. This is the
largest remaining recall lever after W1/W2.

- Split compound sentences into atomic claims while keeping the original span
  and sentence for display.
- Resolve pronouns/anaphora to the paragraph subject (deterministic, with an
  alias map fallback).
- Expand short/full forms and allow the verified `same` aliases from
  `glossary.py`; never merge parent/subsidiary.
- Evidence expansion loop: top-3 passages, neighbouring paragraphs, then one
  sharp retry by value/entity before declaring `no_source`.
- Exit: support rate +8–10 points on W0; false-support unchanged; no claim
  loses its original locator.

### W3 — English citation lane (3–4 days)

Why: citations are the product's trust surface and currently only use supplied
text.

- Parse authors/title/year/DOI from docx footnotes (already anchored).
- Existence/metadata via Crossref, OpenAlex, Semantic Scholar, Unpaywall —
  free, no keys, cached, rate-limited.
- Claim support still uses only the supplied PDF/passage. Verdicts split:
  `citation_missing`, `metadata_mismatch`, `misattributed`, `supported`.
- Borrow RefWarden's three-check framing; do not adopt its web-first pipeline.
- Exit: on 30 real citations, metadata precision ≥ 95%, zero false
  `misattributed`.

### W4 — Scanned/complex PDF ingestion (3–4 days)

Why: scans are flagged but not readable.

- Optional MinerU extra: PDF -> Markdown/JSON with page anchors; fallback to the
  existing external-conversion import.
- Keep it out of the base install. Verify the MinerU licence (Apache-2-based
  with conditions, YOLO/AGPL caveat) before commercial use.
- Exit: a scanned English PDF yields page-level evidence; a scanned Chinese PDF
  is labelled OCR confidence.

### W5 — Precision cleanup (2–3 days)

- Entity/venue proximity for amount/percentage contradictions (3 residual).
- Internal conflicts: require same metric word within the same paragraph;
  re-measure 19 residual.
- Quote matching: paraphrase band and low-similarity wording; no false quote
  upgrades.
- Exit: false-contradiction rate < 2% on W0; internal conflicts < 5 on the
  English set.

### W6 — Product surface (3–5 days)

- English report/UI labels; coverage split into "supported / not checked /
  no source / conflicting".
- "Not checked" is a first-class state, not a grey `unverified`.
- Keep `audit.md`, `corrections.md`, analyzer docx; add a one-page coverage
  dashboard.
- Exit: a student can see in one screen what is proven, what is contradicted,
  and what they still must find.

## 5. Dependencies and licensing

| Dependency | License | Size / cost | When |
|---|---|---|---|
| `bm25s` | MIT | small | W2, base |
| MiniCheck-Flan-T5-L | MIT (model), Apache-2.0 (code) | ~770M, ~3 GB with torch | W1 optional |
| Erlangshen-Roberta-330M-NLI | Apache-2.0 | ~330M | W1 optional (zh) |
| mDeBERTa-v3-mnli-xnli | MIT | ~0.3B | W1 fallback |
| BGE-M3 | MIT | ~567M | W2 optional |
| MinerU | MinerU OSS (Apache-2-based + conditions) | multi-GB, GPU advised | W4 optional |
| Crossref / OpenAlex / Unpaywall | free APIs | no key, rate-limited | W3 |
| RAGAS | Apache-2.0 | eval only | W0/W1 |

No paid API is required. Models are local; `sources_only` stays offline.

## 6. Timeline

| Week | Work | Decision gate |
|---|---|---|
| 1 | W0 English baseline + W1 prototype | support rate measured; prose recall |
| 2 | W1 hardening + W2 retrieval | prose recall ≥ 80%, false-support ≤ 2% |
| 3 | W2.5 normalisation + evidence expansion | support rate +8–10 points |
| 4 | W3 citation lane + W5 precision | metadata ≥ 95%, false-contradiction < 2% |
| 5 | W4 scan ingestion + W6 surface | scanned evidence, one-screen coverage |

Roughly 4–5 weeks part-time, 2–3 weeks focused. The engine rewrite is zero;
the work is adapters, evaluation, and product surface.

## 7. Risks and stop rules

- **False greens from NLI** — support-only, held-out gate, human spot check.
  Stop if false-support > 2%. The 2% ceiling outranks the 90% support target: if
  both cannot hold, report the lower support rate, never a false green.
- **Model/dependency weight** — optional extras; base install and gates must
  stay green without them.
- **English eval bias** — mix public claims with real drafts; keep the blind
  LEGO-style test.
- **Chinese regression** — keep the zh suite as a secondary lane; do not let it
  drive product metrics.
- **MinerU licence** — legal review before shipping; keep it an external
  optional path until cleared.
- **Scope creep** — do not adopt PaperQA2 as a framework; it duplicates the
  pipeline and adds an LLM dependency. Borrow evidence packing only.

## 8. What not to do

- Do not use English-only NLI (MiniCheck, AlignScore, HHEM-2.1) on Chinese.
- Do not let a model produce `contradicted`.
- Do not add a vector database or a hosted service.
- Do not tune rules on the private case; every rule needs a non-case fixture.
- Do not claim coverage before the W0 evaluation exists.

## 9. Immediate next actions

1. Approve W0 scope and the English golden-set sources.
2. Add `app/nli.py` behind `--semantic` with MiniCheck; run on 50 true prose
   claims and report recall against the 90% prior.
3. Add the W2.5 evidence-expansion loop (neighbouring passages + one sharp
   retry) before any more model work; it is cheap and language-neutral.
4. Report support rate, false-support and not-checked together; never quote the
   support rate alone.

## 10. 2026-10-30 — pith assessment (rejected; one idea kept)

Evaluated `l-zhi/pith-wiki` (Apache-2.0, 23★, v0.6.1, verified by opening the
repo) as a retrieval upgrade: import-time LLM "hydration" of each source into a
dense Markdown entry (~30% of the original), then weighted keyword
(title×2, tags×2, summary×1, content×0.5) + BFS link traversal + exact grep, no
embeddings.

**Verdict: do not adopt the product or the hydration step.**

- Hydration puts a model-written restatement in the evidence path. That breaks
  rule 2 (evidence or honesty), rule 14 (no model holds contradiction power) and
  rule 19 (an explanation is not a second opinion): a hydrated entry is the
  smoothed caveat that rule 17's guard was written to stop. A verdict citing it
  no longer points at `file:line` / `page` in the source.
- `sources_only` is zero-network by guarantee (`cli.py`: `use_llm = False` for
  that mode). Runtime hydration would silently end that. Precomputed cards would
  not, but they still only help routing, never proof.
- Its retrieval is weaker than what is here: no value index, no subject/event
  guard, no locators. Link traversal has no object in a flat manifest, and
  `wiki_grep` is what the corpus judge already does deterministically.
- It is an Electron app + CLI, not an importable engine (Windows not CI-covered).

**Kept and implemented today (W2): field weighting.** pith's title×2 / tags×2
mapped onto what a source actually has — filename and section heading — as a
*bounded* rerank of the BM25 pool (`corpus._field_rerank`, bonus cap 0.5×, so a
field hit breaks a near-tie and cannot overturn a clearly better text match).
A heading now labels every passage below it, so a section stays searchable when
a later paragraph drops the subject word. Ranking metadata only: `fname`/`start`
locators, `find_value_passages` and every verdict path are unchanged.

Gates after the change: `test_retrieval.py` 14 assertions (rerank mechanism,
heading inheritance, locator integrity), `run_all.py`, `test_claims.py`,
`test_byos.py` (48), `test_byos_offline.py` (0 connections),
`test_no_case_literals.py`, `run_eval_en.py` (100% / 0% false / 10 not checked)
— all green.

**Parked, with a trigger:** `library prepare` — optional, precomputed "source
cards" (entities, figures, dates, aliases, each carrying `source_id:line`) used
only to route a query to the right passage. Build it only if W1 plus field
weighting still leave the numeric recall gap open, and ship it with a test that
no `claims.jsonl` row may cite a card. Precomputed keeps `sources_only` offline.

**Corrections to the research note that prompted this:**
- "keyword retrieval 0% recall on typos vs MiniSearch 100%" is a Fantazio bench
  result (`tools/bench-retrieval.mjs`); not rerun here, so it should not be
  quoted without the command and fixture count.
- `@orama/orama` is in Fantazio's `package.json` but never imported in `src/` —
  dead weight or a half-finished migration. Unrelated to CheckMato, same
  retrieval question.
- pith's "avoid embedding cost" premise is moot for both repos: Fantazio already
  runs local MiniLM vectors with a 1.2 s keyword fallback, and CheckMato's $0
  rule is satisfied by BM25 + grep.

**Do not:** import pith as a dependency, vendor its Electron/TS code, or add any
LLM step to the BYOS read path.

## 11. 2026-10-30 — hand-search queries (what the reader does next)

An `unverified` row is supposed to hand the reader their next move. It did not:
the query was `entity[0]` + the first five non-stopwords **in reading order**
("acme systems reported revenue 125"), and a library run offered the
instruction "Find the source for: 12.2万行" — neither is pasteable. Two
different failures, one cause: the reader's query was never built by the same
rules as the engine's own ladder.

`app/queries.py` builds it now, deterministically (no model, no network):

1. **The claim's own subject** — an entity named in THIS sentence beats
   `entity[0]` (a draft about one company still writes sentences about its
   founder). Only variant anchors are kept (native script, shared-token alias);
   a different entity from the document is not offered. A numeric claim takes
   the subject's native-script form, because digits travel and translated names
   do not.
2. **The figure as a page writes it** — `US$125 million`, `1984`, `15.68%` —
   never `125000000`.
3. **Every distinctive content word the sentence states** — names, verbs,
   objects: `Zhang Xuanlong funding Qiu Bojun write word processor`, not
   `Zhang Xuanlong Qiu`. Rarity in the library decides which words survive a
   long sentence; reading order decides how they read. Reporting/evaluative
   words ("reported", "announced", "determined", "proposed") are never
   keywords; the fact they frame is.
4. **Quotes are searched as themselves** (the document's own native-script run
   first, then the verbatim span), not by the sentence's year.

Rules that keep it honest: at least two terms unless quoted; a lone entity is
never a query; a figure leads only when the claim states digits ("US$125
million" yes, "three times" no — that becomes "chronic liver disease flared");
cap 4 queries; dedupe by normalised text. These strings are advice for the
reader and never evidence — they are not read by any verdict path.

Wired into both run modes:

- `enrich._explain` (web) — builds first, then merges the engine's own ladder as
  a fallback; the "Try by hand" tail shows two, `manual_checks` keeps four.
- `byos.apply_byos` (library) — every unverified/no_source row gets queries,
  including prose (which previously got only a lead passage) and the
  contradiction-demotion rows.

Honest limit: without a POS tagger this cannot know that "determined" is the
author's framing rather than a fact. A curated lexicon handles the common
evaluative/reporting verbs; anything beyond that needs a model, which this
module deliberately does not call (and `sources_only` cannot call).

Surfaced in `report.md` as a **Search yourself** line, in `claims.jsonl` as
`search_suggestions` (PRD §7, unchanged contract), and in the web panel as
clickable chips (Google, new tab) under the note.

Gate: `tests/test_queries.py` (24 assertions: own-subject, native·figure,
written money form, noise, rarity, quote-first, whole-fact queries,
multi-term, cap, determinism, and the four reader-reported sentences) is in
`run_all.py`. `test_units` keeps its two original expectations (`求伯君 1984`
leads; the quote leads with the doc's own Chinese).

Observed while testing, not fixed here: a `library.toml` written **outside** the
library folder stores source paths relative to itself, so `Library(toml)` loads
0 lines and every claim reads "No corpus provided." — `library check` already
reports missing paths; the silent-empty corpus deserves the same warning.

## 12. 2026-11-02 — W2.5 and W5 closed; DeepSeek-only search

The two workstreams the plan claimed as "implemented" were not fully wired.
Both are now, with gates that fail if they regress.

- **W2.5 compound splitting**: `extract._inject_sentences` calls
  `normalize.split_compound` per sentence and emits one `event` claim per
  uncovered clause, with `raw`/`span` on the clause and the original sentence
  kept for display. A numeric clause no longer hides the other clause's prose.
  Gate: `tests/test_compound.py` (14 assertions, instrumented to prove the
  splitter is actually called).
- **W5 venue guard**: `judge._same_instance` compares place-like names only
  (`_venue_tokens`: after a locative preposition or before a facility noun).
  "Foo's Bergen plant opened 2011" vs "Foo's Oslo plant opened 2012" is
  `unverified`; entity mismatch stays covered by `_names_present`. Gate:
  `tests/test_venue_guard.py` (6 assertions, two controls). A/B proof: the same
  fixture returns `contradicted` with the guard patched out and `unverified`
  with it enabled.

**Search replacement (user directive):** the auto chain
(DuckDuckGo → SearXNG → Wikidata → Wikipedia) and its clients/breakers were
removed. `WebEvidence` now selects exactly one engine — **DeepSeek Search**
(default, `DEEPSEEK_API_KEY`, `$0.75/1,000` successful requests, empty sets
free) or **Brave** — and reports web-unavailable when neither key exists. CLI
`--backend deepseek|brave`; API/UI default `deepseek`; the UI offers
`DeepSeek Search` / `Brave only` and was rebuilt. `searxng_url`/`searxng_engines`
are ignored. HANDOFF rule 1 changed from "$0 by design" to "cheap by design,
explicit engine".

Gates after both passes:

```
run_all: ALL GATES PASS (11 suites incl. compound + venue + queries)
BYOS 48 · claims 10 · retrieval 14 · no-case-literals · offline 0 connections
eval_en 50/50, 0 false support; holdout 40/40, 0 false support
```

**Budget A/B (2026-11-02)** on this chapter: 5 searches / 1 page = 4.9 s,
9 supported, 1 **false** contradicted (a year-list snippet reused across
claims), ≈$0.004; planner depth = 54 searches (of 243 budget), 42.5 s,
14 supported, 0 contradicted, ≈$0.041. Reuse is now support-only, so the
5-search run reports 0 contradicted and 31 unverified.

Not changed (recorded): the PRD still documents the old keyless chain, and
`deploy/searxng/` is retired on disk.


