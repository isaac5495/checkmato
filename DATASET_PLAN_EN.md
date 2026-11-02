# CheckMato Evaluation Dataset — Generation Plan (English)

Version: 1.0 · 2026-10-28
Audience: an LLM or data author asked to generate a benchmark dataset.
Purpose: evaluate CheckMato's **source-grounded** claim checking, not to train it.

---

## 0. What this dataset is

A set of fictional documents and source libraries where every checkable claim has
a hand-verified label and a locator:

- a **draft** (the document being checked),
- a **library** of 3–8 source files (md/txt/docx/pdf),
- **expected labels** per claim: `supported`, `contradicted`, `no_source`,
  `not_checked` (prose), `misattributed` (footnote), `paraphrase_flag`
  (quote differs but is close).

It is an **evaluation** set. If any part is later used for training, the test
split must stay untouched.

## 1. Non-goals

- No real company, person, or confidential case material.
- No copyrighted text; every quote is authored for the dataset.
- No labels produced by CheckMato. Labels come from reading the sources.
- No real web claims that require live retrieval to verify.

## 2. Deliverable layout

```
dataset/
  README.md
  manifest.jsonl                 # one row per case
  cases/<case_id>/
    draft.md
    library/                     # 3–8 source files
      annual-report.md
      interview.md
      press-release.pdf          # optional, text layer required
    expected.jsonl               # one row per claim / footnote
    notes.md                     # optional: author notes, ambiguity
```

`manifest.jsonl` row:

```json
{"case_id":"en-biz-001","language":"en","domain":"business",
 "split":"dev","draft":"cases/en-biz-001/draft.md",
 "library":"cases/en-biz-001/library","claims":9,"footnotes":2}
```

`expected.jsonl` row:

```json
{"case_id":"en-biz-001","language":"en","domain":"business","split":"dev",
 "claim_id":"c001","claim_type":"year","quote":"2019",
 "context":"Northwind reported revenue of US$45 million in 2019.",
 "expected":"supported","difficulty":"easy",
 "evidence":[{"source_id":"annual-report","locator":{"kind":"line","value":42},
              "page":3,"quote":"Northwind reported revenue of US$45 million in 2019."}],
 "notes":""}
```

Footnote row:

```json
{"case_id":"en-biz-001","claim_id":"f001","claim_type":"footnote",
 "ref":"1","anchor_quote":"Northwind opened its Portland depot in 2011.",
 "def_text":"Annual Report 2012, p. 4.",
 "expected":"misattributed","source_id":"annual-report",
 "notes":"source is about the 2012 depot, not the 2011 opening"}
```

## 3. Coverage and counts (minimum per language)

| Item | Count | Notes |
|---|---:|---|
| Core cases | 12 | 8 dev, 4 test; 5 domains |
| Checkable claims | 80 | 60 supported, 10 contradicted, 6 no_source, 4 quote-paraphrase |
| Prose claims | 20 | `not_checked`, no figure/quote |
| Footnotes | 12 | 7 supported, 3 misattributed, 2 no_source |
| Adversarial cases | 8 | 3 claims each, separate file |

Full target (optional, same ratios ×3): 40 cases, 240 checkable, 60 prose,
40 footnotes, 20 adversarial cases.

Domain mix per language: business case, social science, science/tech,
policy/law, healthcare. No domain may exceed 30% of core cases.

Difficulty mix for supported claims: 50% easy (verbatim), 30% medium
(paraphrase, unit conversion, one-hop), 20% hard (multi-hop, anaphora, facts
split across lines/pages).

## 4. Language rules

- **English set:** natural academic/business English, US$/HK$/£/€, commas,
  dates, direct quotes.
- **Chinese set (Simplified):** natural Simplified Chinese, 元/万元/亿元,
  percentages, dates, quotes; include ~20% sources in Traditional script to
  test t2s normalization.
- The two sets are **parallel in design, not translations**. Each has its own
  fictional entities and facts so a model cannot memorize one from the other.
- Chinese tokenisation is different: include facts split across short lines and
  paragraphs, and names that are 2–4 characters.
- Do not mix languages inside one case except deliberate cross-script cases.

## 5. Generation procedure

1. **Entity bible.** Invent a company, 3–6 people, 5–10 events, financials.
   Keep names unique per split (no entity in both dev and test).
2. **Sources first.** Write 3–8 source files that state the facts. Add a
   text-layer PDF version for at least one case per language to test page
   locators.
3. **Draft second.** Write 8–12 paragraphs with 6–10 checkable claims. Include
   deliberate errors and footnotes.
4. **Label by reading.** For each claim, find the exact source line and quote.
   Record the locator (1-based line, 1-based page when available).
5. **Second pass.** Re-read every label without looking at the first pass.
   Resolve disagreements by editing the source or dropping the claim.
6. **Freeze.** Run the validator (section 9), write checksums, do not edit.

## 6. Labeling rules (strict)

- `supported`: the cited source line states the same subject, figure, and event.
  The evidence quote must appear **verbatim** in the source (whitespace and
  punctuation normalized).
- `contradicted`: the source states a different value for the **same subject and
  event**. Include both the document sentence and the source quote.
- `no_source`: no line in the library contains the fact. Verify with a text
  search before labeling; do not guess.
- `not_checked`: prose with no figure and no quote (opinion, transition,
  description). Never label it `no_source`.
- `misattributed`: the footnote's cited source exists but is about another
  milestone/sentence.
- `paraphrase_flag`: the quote is close to a source line but not verbatim; it
  must not be labeled `supported`.
- No label may be derived from CheckMato output.

## 7. Adversarial catalogue (must appear)

1. Same value, different subject (value-only trap).
2. Same subject, different event or year.
3. Parent vs subsidiary vs product (e.g., `X Cloud`, `X Labs`).
4. Lookalike name (`X Hospitals` vs `X Health`).
5. Currency mismatch (US$ vs CN¥).
6. Unit/format mismatch (`122,000` vs `122 000` vs `12.2万`).
7. Decade (`1990s`) not a year claim.
8. Paraphrased quote.
9. Footnote anchored to the wrong sentence.
10. Citation whose source is not in the library.
11. Scanned PDF with no text layer (must be flagged, not silently empty).
12. Fact split across two lines or two pages.
13. Leading pronoun (`It opened…`) whose subject is in the previous sentence.
14. Duplicate metric across different years (must not be an internal conflict).
15. Cross-script case: English claim, Chinese source (optional, 1 per language).

## 8. Splits and anti-leakage

- Split by **entity and topic**, never by random claim.
- No company, person, product, or year pattern may appear in both dev and test.
- Adversarial cases live in a separate `adversarial/` split.
- Test split is frozen before any model tuning.

## 9. QA and acceptance

A case is accepted only if all are true:

- JSONL parses; every `claim_id` unique within a case.
- Every `supported` evidence quote is a verbatim substring of its source line.
- Every `contradicted` claim has a source line with a different value.
- Every `no_source` claim returns zero matches in a full-library text search.
- Every `not_checked` claim has no numeric or quoted value.
- Every locator resolves (line exists; page exists or is null).
- Footnote rows resolve to a source or are explicitly `no_source`.
- Counts match section 3; domain caps respected.
- No real brand/person; no PII; no copyrighted text.
- A 10% random human audit passes label-by-label.

## 10. Prompt to give the generating model

> You are a dataset author, not a fact-checker. Create an evaluation dataset for
> a source-grounded claim checker in **<English|Chinese>**.
>
> Follow the schema and counts in this plan exactly. Invent fictional companies
> and people; never use real ones. Write the source library first, then the
> draft, then label every claim by reading the sources. Evidence quotes must be
> verbatim. Do not use any tool output as a label. Include every item in the
> adversarial catalogue. Keep entities unique across dev/test splits. Output
> `manifest.jsonl`, `cases/<id>/draft.md`, `cases/<id>/library/*`, and
> `cases/<id>/expected.jsonl`.
>
> Before finishing, self-check: counts, unique IDs, verbatim evidence, locators,
> no real data, no split leakage. Report any case you could not label honestly
> instead of guessing.

## 11. Example (English, supported)

Source `library/annual-report.md` line 42:

```
Northwind reported revenue of US$45 million in 2019.
```

Draft:

```
Northwind reported revenue of US$45 million in 2019.
```

Expected: `supported`, evidence line 42, page 3 (if the PDF page map exists).

## 12. Handoff

Deliver a zip plus a `README.md` stating language, counts, split, and known
ambiguities. Keep the source files and the expected labels together; a claim
without its source is not a dataset row.
