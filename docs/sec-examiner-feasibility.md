# SEC Examiner: feasibility check (2026-11-10)

Question: is there enough free, reliable ground truth to build and **self-evaluate** a system that predicts which disclosures the SEC will question?

## Verdict: feasible

| Check | Result |
|---|---|
| Letters exist at scale | S&P 100 since 2018: **657 SEC letters (UPLOAD), 570 company replies (CORRESP)**, covering 96 of 103 companies. Whole market (EDGAR full-text search): **~4,044 substantive letters in 2024 alone**. |
| Machine-readable | 40/40 sampled letters (PDF) had extractable text. No OCR needed. Replies are HTML. |
| Linkable to the filing | Every letter's `Re:` line names the exact form and period ("Form 10-K for Fiscal Year Ended December 31, 2021, Filed February 11, 2022"). A first regex matched 20/40; a `Re:`-line parser should cover nearly all. |
| Section-level ground truth | Comments cite the section and page ("Risk Factors, page 6", "Item 7. MD&A, page 27"), so predictions can be scored per section, not just per filing. |
| Learnable patterns | Topics recur: climate disclosure, non-GAAP prominence and reconciliation, MD&A drivers and known trends, tax reconciling items, KPIs, board leadership (proxy), event exposure (e.g. Russia). |

Sample (40 letters, 2021+): 24 substantive, 10 closing ("completed our review"), 6 "no review" notices.

## What the data teaches about the design

1. **Three letter types.** Only substantive letters are labels. Closing letters mark when a review ended. "No review" notices are noise and must be filtered.
2. **SEC sweeps.** The SEC runs themed campaigns with near-identical letters (climate 2021–22; board leadership proxies 2022). What gets questioned depends on *when*, so evaluation must be strictly point-in-time: predict from the filing and from letters published before it.
3. **Threads.** Many letters follow up on earlier ones ("We note your response to comment 2…"). Only first-round comments on a filing are prediction targets; follow-ups belong to the same thread.
4. **Strong baselines are required.** Because themes repeat, a naive rule ("always flag non-GAAP prominence") may score well. The system must beat (a) topic base rates and (b) "same comments as the company's last letter", or it adds nothing.
5. **Publication lag.** Letters appear months after the review (2026 so far: 11 for the S&P 100), so the self-improvement loop grades predictions with a delay, and the judge must account for that.

## Next: build the judge first

- Corpus: substantive letters plus the referenced filing as it was *before* the letter, for the whole market (full-text search), 2018 onward.
- Labels: per-comment topic and cited section.
- Metrics: issue-level recall and precision against the real letter, by topic and by year; the baselines above; cost and latency per review.
- Splits: train on letters published before date T, test on letters after T (rolling).
