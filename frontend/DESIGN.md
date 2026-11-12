# Design

World: **the Federal Register page.** The product is set like an official government document: a dated issue, numbered sections, and rulings. Seed de1977c0. Code-led build.

## Tokens (src/app/globals.css)
| Role | Light | Dark (night edition) |
|---|---|---|
| Ground (government stock) | `#fbfaf7` | `#11131a` |
| Panel (ruling paper) | `#ffffff` | `#171a22` |
| Ink | `#121212` | `#ece9e1` |
| Muted text (≥4.5:1) | `#55524b` | `#a9a59b` |
| Hairline | ink at 12% | ink at 15% |
| Heavy rule | ink | ink |
| Agency blue: heads, actions, our numbers | `#1c3d8c` | `#8fb0ff` |
| Red stamp: **findings only** (NOT FOUND, Rejected) | `#b3261e` | `#ff8a7a` |

## Type
- **Display and labels:** Archivo, condensed (wdth 75–87.5%). Headlines are black weight, poster scale (up to 5.6rem). `.caps` is used for small uppercase labels and table heads, never as a kicker above a heading.
- **Text:** Source Serif 4. Numbers use `.num`, which sets Archivo with tabular lining numerals.

## Components and rules
- **Rules, not cards:** `rule-heavy` (3px ink) opens each section, `rule-double` is the colophon, and hairlines separate rows. Corners are square (2px radius on controls only). No shadows: print is flat.
- **Ruling:** a printed result with a caps header line, a black condensed company name, a ranked list of 5 with blue rank numerals, a filing-vs-history split bar, and `.stamp` NOT FOUND marks.
- **RuledScale:** every score sits on a ruler next to the baselines it must beat. Ours is the blue tall mark; baselines are muted short marks. Never a lone hero metric.
- **Buttons:** `.btn` is agency blue with caps. Disabled is an outlined muted label, not a washed fill. `.btn-ghost` is an ink outline that inverts on hover.
- **Sections:** a two-column grid, with the heading and lead at 18rem on the left and content on the right; collapses to one column on mobile.
- **Icons:** `components/Icons.tsx`, 1.5px square-cap strokes on a 16px grid. No unicode glyphs.
- **Motion:** a single `.print` reveal (clip-path, 700ms, expo ease-out) on rulings, and a step list while examining. Respects reduced motion.
- **Browser surfaces:** themed selection, focus ring, caret and scrollbar.

## Pages
- **`/` landing (Persuade):** masthead; the question at poster scale with a ticker form beside a real Alibaba ruling; then Why it exists (2-column print text), How it works (§1–§4), The record (ruled scales plus the live version ledger), Who it is for, Privacy and limits, and a closing CTA.
- **`/examiner` (Operate):** a sticky docket on the left (mode tabs, input, free-checks meter); on the right the ruling, a working state with steps, or an empty state explaining how to read a ruling. Arriving with `?ticker=` examines straight away.
- **`/loop`:** the self-improvement record in the same grammar.
