# BYOS Plan — source-grounded verification

Status: draft for approval · 2026-10-27

**Definition.** BYOS = attach the source set (PDFs, book transcripts, press
release, interview notes) and verify the final document against it, claim by
claim, with a page/line locator for every verdict. The sources are the ground
truth; the web is a fallback; comparing two translations is not part of it.

**Rules that bind every phase**

1. **No hardcoded answers.** No company name, person name, year, figure or
   expected verdict may appear in `app/`. A rule is a general pattern or a
   data-driven table, never "if the sentence says X, answer Y". Every rule
   ships with at least one fixture that does not mention Kingsoft.
2. **Evidence or honesty.** A verdict without a locator is `no_source` /
   `unverified`, with the reason. No model output is a verdict.
3. **Same-language first.** Chinese draft + Chinese sources is the primary
   path; cross-script is a capped fallback (§8).

Inputs read: `Ledgerline_New_Business_Proposal.docx`,
`Kingsoft_ACRC_Case_Draft_v20260901_English.docx` +
`C:\Users\user\Desktop\Kingsoft_ACRC_Case_Draft_v20260901_Chinese.docx`,
`AGENTS.md`, `FOOTNOTE_VERIFICATION.md`, `SESSION_STATUS.md`, `TRIM_PLAN.md`,
`pipeline/v9_corrections_plan.md` (head), `pipeline/footnotes_suggested.md`
(structure + first record), `translation_glossary.csv`, current `app/corpus.py`,
`app/judge.py`, `app/extract.py`, `app/enrich.py`, `app/server.py`,
`tests/run_all.py`, PRD G3/F4.

Deliberately not read: the v8–v17 archives and the 200–500 KB book
transcriptions. They are the test corpus, not the spec.

---

## 1. What the KS workflow actually is (the real spec)

Your hand pipeline is not "search the web and see if a number matches". It is
six artefacts, produced in this order:

| # | Artefact | What it encodes | Evidence |
|---|---|---|---|
| 1 | Source set | 5 book transcripts (`.md`, line-addressable), the matching PDFs (page-addressable), a press release, a meeting summary, public URLs | `KS CASE STUDY/*.md`, `*.pdf`, `20250913会议总结.txt` |
| 2 | Anchor map | which sentence/footnote points at which source and which locator | `pipeline/footnotes_suggested.md` (`## SENTENCE n — … line 141`) |
| 3 | Verdict table | ✓ anchored content matches · ⚠ marginal · ✗ wrong topic | `FOOTNOTE_VERIFICATION.md` (76 rows) |
| 4 | Correction plan | 54 numbered edits, each with source URL or `file:line` and author decision | `pipeline/v9_corrections_plan.md` |
| 5 | Language bridge | glossary + native-script names, so a Chinese claim is matched to a Chinese source (not against an English rendering) | `translation_glossary.csv` |
| 6 | Open items | facts that exist only in book/internal material and cannot be public-verified | `FOOTNOTE_VERIFICATION.md`, "Open items" |

Out of scope for BYOS: comparing the English and Chinese drafts against each
other. That is a translation-QA task (`EN_vs_ZH_comparison.docx`,
`app/diff.py`); it is not what "verify the final output against the sources"
means and it must not become a growth path for this feature.

Three failure classes your manual audit caught, which the tool must name:

- **wrong anchor** (F25): the footnote's content is real but belongs to another
  paragraph. Current CheckMato would call that paragraph "supported" if the
  number happened to match. It needs `misattributed`.
- **wrong source** (F22, F48): the citation is a real article about something
  else. Needs `misattributed` too, with *both* quotes shown.
- **book-only fact** (MBO terms, 26-of-40, 80% debt, Xiao Pin): public search
  can never close it. Needs `supported` from BYOS, or an honest `no_source`
  when the book is not attached — never `unverified` after a web search that
  was doomed.

That is the product. The web is the fallback, not the engine.

---

## 2. Gap analysis

| Capability | Today | Needed |
|---|---|---|
| Ingest md/txt/csv/pdf/docx | Yes (`corpus.py`) | Keep; add import of externally converted PDFs + html/rtf later |
| Locator | `file` + `line`; pdf adds `p.N` in the ref string | Structured locator (source, kind, value), plus **dual locator** (md line ↔ pdf page) |
| Source metadata | None (only filename) | Library manifest: title, author, year, publisher, url, accessed, language, hash |
| Retrieval | token inverted index, line-scored | Passage windows (paragraph/page), BM25-ish scoring, alias expansion already present |
| Judging | number/quote/predicate/subject guards | Add **same-event-in-source**, **anchor validity**, `misattributed`, `no_source` |
| Modes | BYOS → web, always | `sources_then_web` (default), `sources_only`, `web_only` |
| Footnotes | text extracted, refs in display order | Ref → paragraph + char offset; audit each anchored claim against the cited source |
| Library reuse | per-request upload only | Named library, persisted, attachable to many drafts |
| Outputs | report.md/xlsx/jsonl/annotated | Plus `audit.md` (✓/⚠/✗ table), `corrections.md`, `sources.json` |
| Language matching | alias expansion only (cross-script names) | **same-language first**: claim language vs source language decides the retrieval lane; cross-script is a capped fallback |
| Metric | recall/precision on seeded fixtures | **false-support rate** as the primary number |

Two structural facts from the code:

- `read_doc()` returns `footnote_refs` and `footnote_defs` but **not where each
  ref sits** (`app/extract.py:106`). Footnote auditing is impossible until that
  is added.
- `Corpus` stores `(file, lineno, raw, tokens, precision)` and nothing about the
  file itself (`app/corpus.py:68`). Per-source metadata has to be introduced
  outside the line index, or every line pays for it.

---

## 3. Product framing

Three modes, one code path (decided 2026-10-27):

- **`sources_then_web` — default.** Check the library first; a claim that gets
  a locator stops there. Only claims with **no** source link go to the web, and
  the report labels the origin (`from your sources` / `from the web`) on every
  evidence card. This is "both": you never lose a book-only fact, and you never
  pay for a search that the library already answered.
- **`sources_only`** — no web call at all. A claim with no matching source is
  `no_source`, with a "find this" instruction (author, title, year, quoted
  phrase). This is the Ledgerline product mode (*"match each to the student's
  own uploaded source, never the open web"*) and the trust claim the proposal
  makes.
- **`web_only`** — today's behaviour, kept for debugging and for libraries that
  are irrelevant to a run.

The mode must be visible in the report header and in `claims.jsonl`
(`"mode": "sources_then_web"`), because `no_source` (nothing was supplied) and
`unverified` (supplied sources were searched and did not settle it) are
different facts.

---

## 4. Data model

### 4.1 Library manifest (`library.toml`, human-editable, portable)

```toml
[library]
id = "ks-acrc"
name = "Kingsoft ACRC source set"
created = "2026-10-27"

[[source]]
id = "shengsheng"
path = "生生不息.md"
kind = "book"
title = "生生不息"
author = "范海涛"
year = 2025
publisher = "Kingsoft (authorized publication)"
language = "zh"
locator = "line"            # line | para | page
paired_path = "生生不息.pdf" # optional: page numbers for the same text
notes = "transcription, no page numbers"
```

Why a file and not a database: it is diffable, portable, and the student can
fix a wrong year without a UI. The manifest lives beside the sources, so a
library is a folder you can zip and hand over.

A draft declares its own language; it is not compared to another draft:

```toml
[draft]
path = "Kingsoft_ACRC_Case_Draft_v20260901_Chinese.docx"
language = "zh"
```

The language is used only to choose the retrieval lane (§8), never to weaken a
verdict.

### 4.2 Locator

```json
{"source_id": "shengsheng", "kind": "line", "value": 918,
 "page": 211, "quote": "verbatim source text", "span": [0, 74]}
```

`page` is filled when a `paired_path` exists and the text aligns. If it cannot
be aligned, `page` stays `null` and the report says `line 918 (page unavailable)`
— exactly the honesty your `SESSION_STATUS.md:13` records.

### 4.3 Claim record (extends the §7 JSONL contract)

```json
{
  "claim_id": "c005",
  "quote": "… spent nearly HK$300 million of his own money in 2012 and 2013 …",
  "verdict": "supported",
  "links": [{
    "source_id": "shengsheng",
    "locator": {"kind": "line", "value": 2499, "page": 318},
    "role": "supports",
    "checks": {"subject": true, "figure": true, "event": true, "anchor": true}
  }],
  "mode": "sources_then_web"
}
```

`checks` is the same structure `provenance.py` already renders, so the report
block and the audit table share one source of truth.

### 4.4 Footnote audit record (new)

```json
{
  "ref_id": "25", "display_no": 25,
  "anchor_para": 47, "anchor_quote": "… nobody was willing to cast the vote …",
  "def_text": "范海涛《生生不息》Part Two (破局) Ch.3, on the 2010 Xishanju MBO …",
  "resolved_source": {"source_id": "shengsheng", "confidence": 0.91},
  "verdict": "misattributed",
  "reason": {"t": "anchor_mismatch", "claim": "2002 vote", "source": "2010 MBO"}
}
```

Output table is literally your `FOOTNOTE_VERIFICATION.md` shape:
`# | anchor quote | footnote subject | ✓/⚠/✗ | fix`.

---

## 5. Ingestion pipeline (BYOS index)

1. **Discover** — walk the library root, skip `.venv`, `archive/`, `__pycache__`,
   and anything matched by `.byosignore` (default: the same denylist).
2. **Fingerprint** — sha256 per file; skip unchanged on re-index (cache keyed by
   hash). A re-run on 300 files must not re-parse 300 files.
3. **Extract**
   - `.md/.txt/.csv` — existing `sniff_bytes` (UTF-8 → charset-normalizer).
   - `.pdf` — PyMuPDF text only. If a page yields < 40 chars, mark it
     `no_text_layer` and **do not OCR in-house**. The UI shows a "convert this
     externally" instruction (any PDF-to-Word/Markdown service the user trusts),
     and the user drops the converted `.docx`/`.md` back into the library with
     `derived_from = "<original.pdf>"`. The tool itself never uploads a file.
     An empty page is never treated as "not in source".
     Note: local text extraction is free (it costs no model tokens); the
     external route exists for scanned files that have no text layer at all,
     not as a cost saving on normal PDFs.
   - `.docx` — body in order, tables flattened, text boxes, footnotes; keep the
     existing Word-compatible flattening.
   - `.html` — text-only fallback (one file in your set is a font page; it
     should not become evidence).
4. **Segment**
   - citation unit = line (md/txt) or paragraph (docx) or page (pdf);
   - retrieval unit = **passage**: adjacent lines/paragraphs merged to 300–900
     chars, never crossing a heading. Books have long paragraphs; line-only
     retrieval is what makes a correct quote look absent.
5. **Metadata** — from the manifest; if absent, infer nothing silently. A source
   without a title is `untitled source (filename)` in the report, and the
   citation builder says `[metadata missing]`.
6. **Index** — keep the inverted token index; add:
   - `df` already exists; add passage length for BM25 scoring;
   - a heading map per source (`h1/h2` stack → section label) so evidence can
     read `生生不息 · Part Two (破局) Ch.3 · line 918`;
   - optional local embedding index behind `--semantic`, off by default
     (deterministic gates must not depend on a model).
7. **Page map** — a page number is only claimable when the PDF has a text
   layer (align md lines to PDF pages by exact text overlap) or when an
   external conversion preserves page breaks. Otherwise accept an optional
   `page_map.csv` (`page,start_line,end_line`) and keep the locator as `line`
   with page marked unavailable. Never invent a page number.
8. **Caps** — 40 MB/file, 200k lines/file stay. Add a library-level cap
   (`max_library_bytes`, default 2 GB) and a clear failure line, not a silent
   skip.

Performance target on your real set (5 books + PDFs, ~1.6 M chars):
first index < 15 s, warm index < 2 s, query p95 < 80 ms, RSS < 1.5 GB.

---

## 6. Retrieval and judging

### 6.1 Candidate retrieval

1. rare tokens from the claim (`Corpus.rare_tokens`, alias-expanded);
2. entity anchor — the claim's subject must appear in the passage (reuse
   `_mentions_entity`, but on the passage, not the whole line);
3. number-aware rung — if the claim has a figure, passages containing that
   figure rank first (this is the one thing the web pass already does well);
4. backoff — if no passage shares two content tokens, the claim is `no_source`,
   not `unverified` after a fake search.

### 6.2 Deterministic checks (unchanged rules, new inputs)

- figure match: `values_equal`, modifiers respected ("over 90%" vs 95%);
- event match: `_predicate_ok` on the **passage**, not the single line;
- subject: `shares_subject` + verified `same` aliases (short/full forms first,
  then cross-script). Parent/subsidiary/product aliases may widen retrieval but
  never satisfy this check;
- quote: `_windowed_ratio` for verbatim, paraphrase band for `paraphrase_flag`;
- anchor: does the passage belong to the section the footnote claims?

### 6.3 Verdict mapping

| Situation | Verdict |
|---|---|
| figure + event + subject agree, quote shows it | `supported` |
| library states a different value for the same event/subject | `contradicted` (deterministic only) |
| source exists, but supports a different claim/milestone | `misattributed` |
| both camps present (web or two sources) | `conflicting` |
| library attached, nothing relevant found | `no_source` |
| no library attached | `unverified` (web path, as today) |

`misattributed` is the honest home for your F22/F25/F48 class and must always
show **both** quotes: the draft sentence and the source sentence, plus what the
source actually says.

### 6.4 False-support guard (the one metric that matters)

Define `false_support` as a `supported` verdict where the evidence passage does
not contain (a) the claim's figure, (b) the claim's subject, and (c) an event
anchor matching the claim. That is computable offline from the JSONL and should
be asserted in tests, not just reported. Target: 0 on the seeded set, < 2 % on
the KS library.

---

## 7. Footnote mode (the differentiator)

This is the feature no competitor has, and it is already specified by your
`FOOTNOTE_VERIFICATION.md`.

### 7.1 Extraction change

`_docx_footnotes()` must return, per reference: `{id, para_index, char_offset,
surrounding_quote}`. Implementation: walk `w:p` elements in `document.xml`,
count `w:footnoteReference` per paragraph; `footnote_defs` stays as is.

### 7.2 Resolution

1. parse the footnote definition for `Author`, `《Title》`, year, page, URL;
2. match to a manifest source: exact title → alias → author+year → unresolved;
3. if unresolved and mode is `sources_then_web`, that URL may be fetched
   (liveness + title match only, never a text search); record `resolved_from:
   "url"`; untrusted URL text is never evidence without a matching passage
4. if unresolved and `sources_only`, verdict `no_source` with the citation as
   the "find this" instruction.

### 7.3 Check

For each anchored sentence:
- run the normal BYOS check against the **resolved source only**;
- additionally require that the source passage sits in the section named by the
  footnote (if the footnote names a chapter/section);
- if the passage supports a different claim → `misattributed`;
- if the footnote is unused or duplicated → `structure` finding;
- if refs are not sequential 1..N → `structure` finding (your TRIM_PLAN rule 4).

### 7.4 Output

`audit.md` mirrors your manual table, plus a machine file `audit.json`. The
xlsx gets a second sheet (`Footnotes`) using your three columns
`No. | Translation | Comments/Suggestions` — same shape the team already reads.

---

## 8. Language strategy (same-language first)

BYOS verifies the final output against the sources. Language is a retrieval
property, not a second document. The KS set makes the rule concrete:

- the sources are Chinese (book transcripts, PDFs, interview notes, press
  release);
- the Chinese draft (`..._Chinese.docx`, 48 footnotes) is the high-precision
  target because claim and source share a script and vocabulary;
- the English draft can still be checked against the same sources, but that is
  the weaker cross-script lane and the report must say so.

Your instinct is correct: give the tool a Chinese draft when the sources are
Chinese. It is not a convenience — it removes the two failure modes that made
the English run noisy.

### 8.1 Lanes

| draft language | source language | lane | confidence ceiling |
|---|---|---|---|
| ZH | ZH | same-language | full |
| EN | EN | same-language | full |
| EN | ZH | cross-script (glossary + digits) | medium |
| ZH | EN | cross-script | medium |

"Full" means all three deterministic checks (figure, event, subject) run on the
source text. "Medium" means the subject check is lexical/alias-based and the
report says so. It is the same verdict engine, with an honest ceiling.

Alias expansion runs in **every** lane, not only across scripts: same-language
short/full forms first (§8.2), cross-script names second (§8.3).

### 8.2 Same-language aliases (zh→zh, en→en)

Same language does not mean the same string. A claim says 金山, the source says
金山软件股份有限公司; a claim says Kingsoft, the source says Kingsoft
Corporation. Without aliases, a correct passage looks absent.

Most of this needs no model:

- normalise width, punctuation, spacing, case; Traditional→Simplified;
- strip legal/company suffixes: Corp, Corporation, Inc, Ltd, Co, Group,
  Software, Technology / 公司, 集团, 软件, 科技, 股份有限公司;
- read parenthetical glosses already in the text: `西山居（Seasun）`;
- person name order: Lei Jun / Jun Lei;
- acronyms with their expansion when both occur in the corpus: MBO /
  管理层收购, IPO / 上市.

The model is consulted only when the rule is ambiguous (西山居 vs Xishanju vs
Seasun), and it must return a **scope**:

| scope | meaning | may be used for |
|---|---|---|
| `same` | same entity | retrieval + subject anchor |
| `parent` | parent company | retrieval only |
| `subsidiary` | subsidiary or brand | retrieval only |
| `product` | product line | retrieval only |

This is not pedantry: 金山 vs 金山云, Kingsoft vs Kingsoft Cloud, WPS vs
金山办公 are different subjects. Merging them is exactly how a subsidiary's
figure becomes a false green for the parent.

Verification for a `same` pair (any one is enough):

1. one form contains the other after suffix stripping;
2. both occur inside the same paragraph somewhere in the corpus;
3. the draft itself glosses them together (`A（B）`).

Parent/subsidiary/product pairs may be stored without co-occurrence, but they
never satisfy the subject check.

### 8.3 Cross-script rules (partly built already)

1. **Entity bridge** — `translation_glossary.csv` (`en,zh_simplified,note`) →
   `names.AliasMap`. Names only; the `note` column is a warning ("translation
   choice"), never an alias.
2. **Figures are script-independent** — normalize before comparing
   (`122,000` / `12.2万`); `parse_amount_text` already handles 万/亿.
3. **Subject precondition stays** — `shares_subject` on the native line plus an
   alias hit; never the model alone.
4. **No `high` on the cross-script lane** — rule 18 already prescribes this for
   the Jev fallback; extend it to every cross-script verdict.
5. **Translations are labelled** — when the report shows an English rendering of
   a Chinese source line, the original quote is always shown beside it.

### 8.4 Building the glossary (LLM proposes, sources decide)

**The model does not search.** A chat model cannot open your folder and cannot
prove a string exists. It can only look at text we put in the prompt and guess a
pairing. So the workflow is ours; the model is one step inside it.

#### A. Harvest candidates (no model)

Four deterministic sources:

1. **Bilingual glosses already in the draft** — `English name（中文名）` and
   `中文名（English name）` patterns. Highest value: the author already told us.
2. **Footnote definitions** — `《title》`, author names, publisher lines.
3. **Repeated strings** — Latin capitalised runs (with or without a corporate
   suffix: Group, Cloud, Office, University, Bank...) and CJK runs of 2–8
   characters that occur at least twice, or occur in both the draft and the
   library. A general Chinese surname list is a *data table*, never a
   case-specific rule.
4. **Manifest metadata** — the title and author fields of each source.
5. **Same-language variants** — suffix-stripped forms (金山软件 / 金山,
   Kingsoft Corporation / Kingsoft), parenthetical glosses, name-order swaps
   (Lei Jun / Jun Lei), acronyms with an expansion in the corpus (MBO /
   管理层收购).

Output `candidates.csv`: `a, b, lang_pair, kind, context, where`.
Dedupe by normalised form; rank by occurrences × number of distinct sources.

#### B. Ask the model (one batch, strict JSON)

For each candidate send: the candidate, its kind (person / organisation / term),
and at most two short contexts (the sentence where it appears, max 300 chars
each). Require:

```json
{"pairs": [{"a": "...", "b": "...", "lang_pair": "zh-zh|en-en|zh-en",
            "kind": "person|org|product|term", "scope": "same|parent|subsidiary|product",
            "confidence": 0.0, "why": "..."}]}
```

Batch 20–40 candidates per call. Reject a response that is not valid JSON or
that contains a pair not in the candidate set. The model is never asked about
claims or verdicts.

#### C. Verify against the corpus (the gate)

For every proposal:

1. **Normalise** both sides: NFKC, Traditional→Simplified via OpenCC, strip
   whitespace/punctuation, lowercase Latin.
2. **Occurrence is mandatory** — the source-language form must appear at least
   once in the library; record every locator (file + line/page).
3. **Same-language pairs** pass only if one of the §8.2 identity checks holds
   (containment after suffix stripping, co-occurrence in one paragraph, or a
   gloss in the draft). If the strings co-occur but the relationship is
   parent/subsidiary/product, store the pair with that scope and mark it
   retrieval-only.
4. **Boundary check for CJK** — a 3-character name must not count when it only
   occurs inside a longer name (张旋龙 contains 旋龙). Require a plausible
   boundary (neighbouring characters not CJK) or an exact run already in the
   glossary.
5. **Ambiguity** — if several strings are proposed for one name, keep the one
   with the most source occurrences and the best context overlap; the rest
   become `proposed_unverified`.
6. **Jargon needs the second side** — a term mapping also requires the term to
   appear in the draft (it is a term the author uses). If the Chinese term is a
   paraphrase and never appears literally, it stays `proposed_unverified` and
   can only generate retrieval queries.

States: `verified` (identity proven — may anchor a subject), `retrieval_only`
(stored, widens search, never anchors: parent/subsidiary/product and every
cross-script pair), `proposed_unverified` (no proof), `user` (human override).

#### D. Human review

The CSV ships with the evidence: occurrences, two sample locators, and the
model's `why`. Editing a row sets `origin=user`, which always wins. Deleting a
row is permanent for that library — a re-import must not resurrect it.

#### E. Use

An alias widens the candidate set. It never raises confidence and never produces
a verdict. Cross-script matches stay `medium` even on a `verified` alias. A
contradiction still requires the deterministic checks on the source passage.

#### Why the model cannot do this alone

- it cannot read local files;
- it cannot count occurrences;
- it invents plausible characters (求伯君 -> 邱伯均);
- it cannot tell two real people with similar names apart.

The corpus proof fixes all four; the model only saves a human from typing pairs
by hand.

#### Measurement before trust

Run the builder on the KS library and count: proposals, `verified`, `rejected`,
and — by hand — how many rejected ones were actually right. Target: **zero wrong
pairs in `verified`**, even if that costs coverage. A missed alias costs one
failed search; a wrong alias costs a false green.

Without a key the stage still runs from the existing CSV plus deterministic
harvesting; the LLM only adds coverage. It is never required for a run to
finish.

Column format (superset of the current file):

`a,b,lang_pair,kind,scope,origin,occ_a,occ_b,state,note`

`lang_pair` is `zh-zh | en-en | zh-en`; `kind` is `person | org | product |
term`; `scope` is `same | parent | subsidiary | product`; `origin` is
`user | doc | llm`; `state` is `verified | retrieval_only |
proposed_unverified`; `note` keeps the "translation choice, not an alias"
warning.

### 8.5 Acceptance implication

The Chinese draft is the primary acceptance target (same language as the
library). The English draft gets a second, explicitly weaker run: it must not
produce false greens, and its lower coverage is expected and reported, not
treated as a regression.

### 8.6 Out of scope

Version-to-version comparison (EN vs ZH, v8 vs v9) is not BYOS. `app/diff.py`
already handles it as a separate command. If it is ever wanted inside a report,
it is a link, not a merge of verdicts.

One measured note, kept so it is not re-discovered: the final EN/ZH pair is
259/258 paragraphs, 48 footnotes each, with a one-paragraph shift (18% naive
figure overlap, 89% at offset −1). That is a translation-QA fact, not a BYOS
requirement.

---

## 9. CLI, API, UI

### CLI

```
# default when --library is given: library first, web only for the rest
python -m app.cli draft.docx --library "C:\...\KS CASE STUDY" --footnotes --out reports

# paid/Ledgerline mode: no network at all
python -m app.cli draft.docx --library lib.toml --sources-only --footnotes

# explicit web-only run (old behaviour)
python -m app.cli draft.docx --web --llm --footnotes

python -m app.cli library index <dir> --out library.toml     # build/refresh manifest
python -m app.cli library check <lib.toml>                   # missing files, hash drift
python -m app.cli glossary draft.docx --library lib.toml --glossary-llm  # propose + verify names
```

New flags: `--sources-only`, `--footnotes`, `--glossary-llm`,
`--require-source`, `--semantic` (off). `--web` is still accepted but is the
default fallback when a library is attached; `--web-only` is explicit.

### API

- `POST /api/library` (multipart, files[]) → `{library_id, sources:[…], warnings[]}`
- `GET /api/library/{id}` → manifest + coverage stats
- `DELETE /api/library/{id}/{source_id}`
- `/api/check` gains `library_id`, `mode`
  (`sources_then_web|sources_only|web_only`), `footnotes` (bool). SSE adds
  `indexing`, `byos_done`, `footnotes_done`.
- Jobs store `library_id`; deleting a library invalidates reports that cite it
  (explicit error, not a broken link).

### UI

1. **Sources shelf** — drop folder / files; shows title, author, year, pages,
   indexed lines, "needs conversion" badge for scanned PDFs.
2. **Coverage bar** — `n claims · m linked · k no_source`.
3. **Evidence card** — source title · section · line/page · verbatim quote;
   "open at line" copies `file:line` (and `p.N` when available).
4. **No-source panel** — the "find this" list: exact citation to obtain, plus a
   pre-typed query (never executed in sources-only mode).
5. **Footnotes tab** — the ✓/⚠/✗ table, click a row to jump to the anchor.
6. **Mode banner** — "Sources only: 0 web requests made" — this is a trust
   feature, not chrome.

---

## 10. Privacy and cost posture

- Library files stay on the machine; no upload to a model. `--llm` is **off**
  by default in `sources_only`, and when on, only the claim + retrieved passage
  leave the machine (never the whole draft, never the library).
- The one exception is the glossary proposal (§8.4): it sends harvested names
  plus one sentence of context each, on an explicit `--glossary-llm` opt-in.
  The library itself is not uploaded, and the returned pairs are useless until
  they are found verbatim in the corpus.
- Hash-only dedupe; `library.toml` stores paths, not contents.
- Deletion cascade: removing a source rewrites reports' evidence to
  "source deleted" rather than silently dropping the row.
- Cost: BYOS path is $0 (no search, no LLM needed). Search stays free until
  2026-11-01; after that DeepSeek search is $0.75/1k and must remain opt-in.

---

## 11. Tests and evaluation

New fixtures under `tests/byos/` (synthetic, no KS material):

| Fixture | Purpose |
|---|---|
| `book.md` + `book.pdf` | dual locator (line ↔ page), heading map |
| `wrong_anchor.docx` | footnote belongs to another paragraph → `misattributed` |
| `wrong_source.docx` | footnote cites a real but unrelated article → `misattributed` |
| `book_only.docx` | fact only in the library → `supported` in sources-only, `no_source` without library |
| `translated_source/` | EN claim ↔ ZH source via glossary (cross-script lane, confidence capped) |
| `same_language_zh/` | ZH claim ↔ ZH source; the primary lane, full confidence |
| `alias_short_full/` | 金山 ↔ 金山软件, Kingsoft ↔ Kingsoft Corporation: same entity, may anchor |
| `alias_parent_sub/` | 金山 ≠ 金山云, Kingsoft ≠ Kingsoft Cloud: may retrieve, must never satisfy the subject check |
| `same_number_other_event.md` | the rule-17 trap, now on passages |
| `scanned.pdf` | no text layer → `no_text_layer` + external-convert instruction, never a silent miss |
| `glossary_llm/` | LLM proposes a wrong native name (absent from the corpus) → rejected; the correct pair → accepted |

Two enforcement tests that are not about fixtures:

- **No-case-literals gate** — a test that greps `app/` for the fixture and KS
  names and fails if any appears. Rules may be generic patterns or data tables;
  a company name in a branch is how a "general" tool quietly becomes a demo.
- **No-network gate** — `sources_only` runs with a socket stub that raises on
  any connection; the run must still complete.

Private regression (gitignored): point the suite at `KS CASE STUDY` and the
archived v7/v8 drafts. Expected outcomes are already written down in
`FOOTNOTE_VERIFICATION.md` (F22/F25/F48 are ✗ pre-fix, ✓ post-fix).

Metrics, reported on every BYOS run:
- **false-support rate** (primary; target 0 on fixtures),
- anchor precision (footnote → correct source),
- coverage (claims linked / claims checkable),
- abstention correctness (no_source when truly absent, not when present).

---

## 12. Phases

| Phase | Deliverable | Exit criteria | Est. |
|---|---|---|---|
| P0 | Manifest + ingestion + locators + `library index` | 5 KS books index in < 15 s; every line/page addressable; tests green | 3–4 d |
| P1 | Modes + `misattributed` + `no_source` + passage judging | default stops at the library when a locator exists; `sources_only` makes 0 network calls; seeded false-support = 0 | 3–4 d |
| P2 | Footnote extraction with anchors + `audit.md`/`audit.json` | reproduces the 76-row table shape; F25-class caught | 4–5 d |
| P3 | md↔pdf page pairing + external-convert import + glossary build/verify | page numbers filled where a text layer or page map exists; `glossary.csv` generated with source-occurrence proof; a wrong LLM name is rejected | 4–5 d |
| P4 | Library API + UI shelf/coverage/evidence/footnotes tab | upload → check → export in one flow; external-convert instruction shown for scanned PDFs | 4–6 d |
| P5 | KS acceptance + metrics + hardening | see §13 | 3–5 d |

Order matters: P0–P2 produce the artefacts your manual workflow produced, so
the plan is useful even before any UI exists.

---

## 13. Acceptance test (the one HANDOFF has been waiting for)

1. Build a manifest over `KS CASE STUDY` (5 transcripts, 5 PDFs, press release,
   meeting summary; skip `archive/`, `.venv`, comparison docs).
2. **Primary run A:** `sources_only --footnotes` on
   `Kingsoft_ACRC_Case_Draft_v20260901_Chinese.docx` — same language as the
   library, full-confidence lane, zero network.
3. **Primary run B:** the same draft and library in the default
   `sources_then_web` mode. Requirement: every claim that the library can settle
   must be settled **before** any search is spent, and the report must label the
   origin of each evidence card.
4. **Regression run:** the archived pre-fix draft that still contains the
   F22/F25/F48 errors (the v7 English file, if that is the only copy). This is a
   known-answer test of the `misattributed` detector, run through the
   cross-script lane; it is not a product path and its coverage is not a target.
5. **Scanned-source rule:** if a book PDF has no text layer, run with the
   externally converted copy (`derived_from` recorded). A missing text layer
   must never be reported as "fact not in source".
6. **Secondary, later:** the English draft against the Chinese library. Deferred
   by decision (Chinese first); when built, it must cap confidence at `medium`
   and report coverage separately.
7. Pass criteria:
   - ZH primary: 0 `misattributed`; every footnote resolved or honestly
     `no_source`; every figure-bearing claim with a source passage is
     `supported` at the correct locator;
   - default mode: searches spent only on claims the library could not settle;
   - v7 regression: F22, F25 and F48 reported as `misattributed` (the three your
     audit found by hand);
   - the book-only MBO claims (26 of 40, 80 % debt, valuation) become
     `supported` with `生生不息` line references;
   - **zero** web requests in `sources_only`;
   - false-support rate 0 on the claims listed in `FOOTNOTE_VERIFICATION.md`
     that are marked ✓.
8. Archive the resulting `audit.md` + `claims.jsonl` as the golden output.

That is also the Ledgerline demo: same engine, student library, page-level
evidence, "cannot verify" as a first-class answer.

---

## 14. Decisions — recorded 2026-10-27

1. **Mode** — both. Default `sources_then_web`: the library answers first, and
   only unsettled claims reach the web. `sources_only` remains the Ledgerline
   product mode (0 network, "find this" instructions).
2. **Page numbers** — yes. Align `.md` ↔ `.pdf`. When the PDF has no text
   layer, use the externally converted copy or an optional `page_map.csv`.
   A page is never invented.
3. **Scanned PDFs** — no in-house OCR. The tool points the user to external
   PDF-to-Word/Markdown conversion and imports the result with `derived_from`.
   No vendor is hardcoded: a generic instruction plus an operator-configurable
   URL, not a baked-in service.
4. **Language** — Chinese first. The English draft stays designed (cross-script
   lane, `medium` ceiling) but is not built in P0–P3.
5. **Glossary** — built automatically. DeepSeek proposes pairs in one batch; the
   corpus must contain both strings verbatim; a human can override. Unverified
   pairs may widen retrieval, never conclude a verdict.
6. **`misattributed` vs `contradicted`** — kept separate (an anchoring error and
   a factual conflict need different fixes).
7. **LLM in sources-only** — off by default; explicit per-run override. The
   glossary call is the one separate opt-in.
8. **Library scope** — named libraries, reusable across drafts (the same sources
   serve every chapter), with per-draft attachment.
9. **No hardcoding** — binding rule (top of file), enforced by tests.

Still open, can wait until P2:

- Keep a configurable list of external conversion services, or only the generic
  "convert it yourself and drop the file back" instruction?
- Is `page_map.csv` a first-class UI import, or a CLI-only power-user option?
