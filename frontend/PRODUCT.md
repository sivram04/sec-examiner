# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Two audiences, served equally:
- **Finance and legal teams** preparing a 10-K, 10-Q or 20-F: SEC reporting managers, controllers, securities lawyers. Job: find out, before filing, which disclosures SEC staff are likely to question, and what expected disclosure is missing.
- **Recruiters and hiring managers** evaluating the author's AI engineering: they want to see what was built, how it learns, and proof that the numbers are honest.

## Product Purpose

The SEC Examiner predicts which topics SEC staff will raise in a comment letter on a periodic report, and which expected disclosures appear to be missing. It exists because a comment letter is costly: weeks of lawyers and auditors, and a public record of what the company got wrong. Knowing the likely questions before filing lets a team fix them first. Success: the top predicted topics match what the SEC actually asks, on filings the model never saw.

## Positioning

Graded against reality, not opinion: every version is scored on real SEC comment letters by a hash-sealed judge, on a later year it was never tuned on, against simple baselines it must beat. It improves itself without anyone writing code (it proposes settings changes and writes its own sandboxed feature code), and ships a new version only when the judge approves. It learns only from public SEC letters; user drafts are never stored or used for training.

## Operating Context

- Examine by ticker (latest 10-K/10-Q/20-F pulled live from SEC EDGAR, 6-10 s first time) or paste an unfiled draft (about 0.2 s).
- Public demo: no sign-up; 2 examinations per visitor IP per day, 300 site-wide. Unlimited when run locally (open source, Apache-2.0, github.com/sivram04/sec-examiner).
- Also available as a REST API and an MCP server for AI assistants (Claude, Cursor).
- Pages: landing, Examiner (the tool), Self-improvement dashboard.

## Capabilities and Constraints

- 23 SEC comment topics; top 5 shown with High/Medium/Lower likelihood, the split of each score between the filing's own text and past SEC letters, and "not found in the filing" disclosures for 17 topics.
- Not legal or accounting advice; not affiliated with the SEC.
- Stateless: no accounts, no database of user data.

## Evidence on Hand

- 5,107 real SEC comment letters, 2,597 reviewed filings (2021-2026).
- Champion v1: F1@5 0.357 on 640 filings from 2024 (selection) and 0.352 on 380 filings from 2025-26 (holdout, never used to choose); best baselines 0.312 and 0.318.
- Self-improvement record: 7 versions tried (2 written as code by the system), 1 shipped; all in the audit log and on the dashboard.
- Live example outputs (e.g. Alibaba 20-F: China/Russia/sanctions ranked first).
- No customers, testimonials, press or usage numbers exist. Do not fabricate any.

## Product Principles

1. Honest numbers first: show the holdout score and the baselines, including what failed.
2. Explain every prediction: why it ranked, what is missing.
3. Privacy by design: nothing a user submits is kept.
4. A human decides: the tool prepares; counsel and auditors judge.

## Accessibility & Inclusion

WCAG AA contrast, keyboard operable, works at phone width, respects reduced motion and the system light/dark theme.
