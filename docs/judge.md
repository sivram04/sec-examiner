# The judge

The fixed yardstick every version of the SEC Examiner is graded by. The self-improving worker may change anything about itself except `src/research_desk/judge/`, which is hash-sealed: the harness refuses to grade if any judge file differs from `MANIFEST.json`. Sealing needs an explicit `desk judge-seal --yes`.

## What it measures

For each 10-K / 10-Q / 20-F that the SEC staff reviewed, the Examiner predicts a ranked list of topics. The judge compares the top 5 with the topics the SEC actually raised in its **first-round** comments.

- **Precision@5**: share of flags that were real SEC issues.
- **Recall@5**: share of the real SEC issues that were flagged.
- **F1**, and **hit rate** (at least one real issue flagged).
- Breakdowns by year and per topic, plus mean seconds and cost per review.

## Rules that keep it honest

| Rule | Why |
|---|---|
| **Point-in-time.** Each case sees only letters published before the filing date, and the harness (not the predictor) enforces it. | A version can't peek at the letter it is graded on. |
| **First-round only.** Follow-ups ("we note your response…") are excluded, detected by the judge's own rule. | They react to the company's replies and can't be predicted from the filing. |
| **Earliest letter per filing.** | Later letters continue the same exchange. |
| **"Other" never counts**, in gold or in predictions. | It isn't actionable, and as the most common label it would earn free credit. |
| **Deterministic labels.** Fixed keyword rules, not an LLM. | Gold labels can't drift or be shaped by the model under test. |
| **Gate.** Beat the best baseline by ≥ 0.02 F1, on ≥ 100 cases, under 60 s and $0.05 per review (`gates.json`). | "Better" must be measurable, and must not cost more than it's worth. |

## Corpus (`desk examiner-build`, 2023–2024)

9,514 substantive letters scanned (0 errors); **2,946** review a periodic report; **2,870 (97%)** are linked to the exact filing reviewed, filed before the letter. Of 10,034 parsed comments, 2,784 are follow-ups; 7,250 are first-round. Labels cover 80.4% of first-round comments; the remaining 19.6% are a long tail labeled "other".

## Baselines on 2024 filings (`desk judge-baselines --test-from 2024-01-01`, 572 cases)

| Baseline | Precision@5 | Recall@5 | F1 | Hit rate |
|---|---|---|---|---|
| Most common topics overall | 0.188 | 0.559 | 0.282 | 70.8% |
| Most common in the past year | 0.187 | 0.558 | 0.281 | 70.6% |
| Most common in the same industry | 0.201 | 0.604 | 0.302 | 75.5% |
| The company's past letters, then industry | 0.202 | 0.606 | **0.303** | 75.7% |

**To pass the gate, the Examiner needs F1 ≥ 0.323.** The baselines never read the filing; they only know what the SEC tends to ask. Beating them means the system actually reads the disclosure.

## Examiner versions

| Version | What it is | F1@5 | Recall@5 | Hit rate | Cost / review | Gate |
|---|---|---|---|---|---|---|
| v1 | TF-IDF over the filing's sections, one logistic regression per topic (`desk examiner-train --version v1`) | **0.346** | 0.677 | 79.4% | $0, 1.5 s | **PASS** (bar 0.323) |

v1 per-topic recall, i.e. when the SEC raised a topic, how often v1 flagged it: non-GAAP 0.94 (234 cases), MD&A drivers 0.89 (125), segments 0.79 (82), revenue recognition 0.73 (56), geopolitical 0.73 (41), controls 0.72 (82). Weak: impairment 0.11 (28), financial instruments 0.21 (24), cybersecurity 0.24 (25), presentation 0.31 (52).

What v1's numbers say, and where v2 should look:
- **Validation overstated quality**: F1 0.498 on late-2023 cases against 0.346 on 2024. Either the topic mix shifted or the 163-case validation slice is too small. Use a larger, rolling validation.
- **Tuning dropped the priors entirely** (`weight_text = 1.0`), although company and industry history beat the plain base rate. They may need to be model features rather than a fixed blend.
- **The weak topics are specific, quantitative disclosures** (impairment tests, fair value, cyber). Section-aware features (which item a phrase sits in) and more history (2018–2022) are the obvious next steps.

## Known limits

- The training history starts in 2023, so early-2024 cases have only a year of prior letters. Adding 2018–2022 is a re-run of `examiner-build`.
- Topic labels are rules; about 20% of comments fall outside the taxonomy. An LLM-assisted labeler checked against a hand-labeled sample is the next judge improvement, and it must be sealed like any other judge change.
- Scoring is at topic level. Section-level scoring (did we flag the right passage?) is the next metric to add.
