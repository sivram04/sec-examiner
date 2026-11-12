"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowRight, ArrowUpRight, Check, Lock } from "@/components/Icons";
import RuledScale from "@/components/RuledScale";
import { api, type LoopStatus } from "@/lib/api";

const EXAMPLES = ["TSLA", "BABA", "NVDA", "JPM", "COIN"];

// A real result: Alibaba's latest 20-F, examined by champion v1 on November 12, 2026.
const SPECIMEN = [
  { label: "China, Russia and sanctions", level: "High", filing: 86, missing: [] as string[] },
  { label: "Audit report and exhibits", level: "High", filing: 86, missing: [] },
  { label: "MD&A: drivers of results", level: "Medium", filing: 73, missing: ["offsetting factors"] },
  { label: "Segment reporting", level: "Medium", filing: 75, missing: [] },
  { label: "Non-GAAP measures", level: "Medium", filing: 60, missing: [] },
];

// shown until the live record loads (same values the live API reports)
const FALLBACK = {
  selection: { f1: 0.357, n: 640, baselines: { base_rate: 0.293, recent_base_rate: 0.285, industry_rate: 0.311, company_history: 0.312 } },
  holdout: { f1: 0.352, n: 380, baselines: { base_rate: 0.296, recent_base_rate: 0.318, industry_rate: 0.285, company_history: 0.289 } },
};
const BASE_NAMES: Record<string, string> = {
  base_rate: "Market base rate", recent_base_rate: "Recent market rate",
  industry_rate: "Industry rate", company_history: "Company's own history",
};

function TickerForm({ large = false }: { large?: boolean }) {
  const router = useRouter();
  const [t, setT] = useState("");
  const go = (x: string) => { const v = x.trim().toUpperCase(); if (v) router.push(`/examiner/?ticker=${encodeURIComponent(v)}`); };
  return (
    <div>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); go(t); }}>
        <label htmlFor={large ? "hero-ticker" : "close-ticker"} className="sr-only">Company ticker</label>
        <input id={large ? "hero-ticker" : "close-ticker"} className={`field num flex-1 uppercase sm:max-w-[16rem] ${large ? "text-lg" : ""}`}
          placeholder="Ticker, e.g. TSLA" autoComplete="off" value={t} onChange={(e) => setT(e.target.value)} />
        <button className="btn" disabled={!t.trim()}>Examine <ArrowRight /></button>
      </form>
      <div className="mt-2.5 flex flex-wrap items-center gap-x-1 gap-y-1.5 text-[13px]">
        <span className="mr-1 text-muted">Or try</span>
        {EXAMPLES.map((x) => (
          <button key={x} onClick={() => go(x)} className="num border border-line px-2 py-0.5 hover:border-accent hover:text-accent">{x}</button>
        ))}
      </div>
    </div>
  );
}

function Ruling() {
  return (
    <article aria-label="Example ruling for Alibaba's 20-F" className="print relative border border-rule bg-panel p-5">
      <div className="caps flex justify-between border-b border-rule pb-2 text-muted">
        <span>Ruling · Form 20-F</span><span>Period ending Mar 31, 2026</span>
      </div>
      <h2 className="head mt-3 text-2xl font-bold leading-tight">Alibaba Group Holding Ltd</h2>
      <p className="mt-1 text-[13.5px] text-muted">Topics SEC staff are most likely to raise, ranked.</p>
      <ol className="mt-3">
        {SPECIMEN.map((p, i) => (
          <li key={p.label} className="border-t border-line py-2.5">
            <div className="flex items-baseline gap-3">
              <span className="num w-4 shrink-0 text-[13px] text-muted">{i + 1}</span>
              <span className="flex-1 font-semibold leading-snug">{p.label}</span>
              <span className={`caps ${p.level === "High" ? "text-ink" : "text-muted"}`}>{p.level}</span>
            </div>
            <div className="ml-7 mt-1.5 flex items-center gap-2">
              <span className="h-[3px] flex-1 bg-chip"><span className="block h-[3px] bg-accent" style={{ width: `${p.filing}%` }} /></span>
              <span className="num w-28 shrink-0 text-right text-[12px] text-muted">{p.filing}% from filing text</span>
            </div>
            {p.missing.length > 0 && (
              <div className="ml-7 mt-2 flex flex-wrap items-center gap-2 text-[13px]">
                <span className="stamp">Not found</span><span>{p.missing.join(", ")}</span>
              </div>
            )}
          </li>
        ))}
      </ol>
      <p className="mt-2 border-t border-rule pt-2 text-[12px] text-muted">
        A real result from the live model (v1), examined Nov 12, 2026. 8 seconds, 60,050 words read.
      </p>
    </article>
  );
}

function Section({ id, title, children, lead }: { id: string; title: string; lead?: string; children: React.ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-h`} className="rule-heavy mt-16 pt-5 sm:mt-24">
      <div className="grid gap-x-10 gap-y-3 lg:grid-cols-[18rem_1fr]">
        <div>
          <h2 id={`${id}-h`} className="head text-[2rem] font-extrabold leading-[1.05] text-balance">{title}</h2>
          {lead && <p className="mt-3 text-[15px] leading-relaxed text-muted">{lead}</p>}
        </div>
        <div>{children}</div>
      </div>
    </section>
  );
}

const STEPS = [
  { t: "Read the report", d: "Pulls the latest 10-K, 10-Q or 20-F from SEC EDGAR (or reads your draft) and reads the business, risk factors, MD&A and the notes." },
  { t: "Compare with SEC history", d: "Weighs what staff asked this company, its industry and the whole market, using only letters published before the filing date." },
  { t: "Flag what is missing", d: "Ranks 23 comment topics and checks 17 of them for the disclosures staff usually expect, such as goodwill headroom or the comparable GAAP measure." },
  { t: "Judge every version", d: "A hash-sealed judge grades each new version on real SEC letters. It ships only if it passes and beats the current one." },
];

export default function Landing() {
  const [s, setS] = useState<LoopStatus | null>(null);
  useEffect(() => { api.loopStatus().then(setS).catch(() => {}); }, []);
  const sel = s?.selection.f1 != null ? s.selection : FALLBACK.selection;
  const hold = s?.holdout.f1 != null ? s.holdout : FALLBACK.holdout;
  const marks = (w: { f1: number | null; baselines: Record<string, number> }) => [
    { label: "SEC Examiner", value: w.f1 ?? 0, ours: true },
    ...Object.entries(w.baselines).map(([k, v]) => ({ label: BASE_NAMES[k] ?? k, value: v })),
  ];
  const attempts = s?.attempts ?? [];
  const shipped = attempts.filter((a) => a.decision === "promote").length;
  const coded = attempts.filter((a) => a.rationale.startsWith("llm-code:")).length;

  return (
    <>
      {/* first viewport: the question at poster scale, a real ruling beside it */}
      <section className="grid items-start gap-10 pt-8 sm:pt-12 lg:grid-cols-12 lg:gap-12">
        <div className="lg:col-span-7">
          <h1 className="head text-[3.1rem] font-black leading-[0.92] tracking-[-0.02em] text-balance sm:text-[4.6rem] lg:text-[5.6rem]">
            What will the SEC ask about your&nbsp;10&#8209;K?
          </h1>
          <p className="mt-6 max-w-[38rem] text-[1.2rem] leading-relaxed">
            SEC Examiner predicts the topics SEC staff are likely to raise in a comment letter, and the disclosures
            they will find missing, before you file. It is trained and graded on <strong>5,107 real comment letters</strong>.
          </p>
          <div className="mt-7"><TickerForm large /></div>
          <p className="mt-4 flex items-center gap-2 text-[13px] text-muted">
            <Lock className="shrink-0" /> No sign-up. 2 free examinations a day. Drafts are never stored.
          </p>
        </div>
        <div className="lg:col-span-5 lg:pt-3"><Ruling /></div>
      </section>

      <Section id="why" title="Why it exists"
        lead="A comment letter is expensive to answer and public forever. The questions are not random.">
        <div className="text-[16px] leading-[1.7] md:columns-2 md:gap-10 [column-rule:1px_solid_var(--line)]">
          <p>
            When the SEC&apos;s Division of Corporation Finance reviews a 10-K, 10-Q or 20-F, it sends the company a letter
            of numbered comments asking it to explain, revise or add disclosure. In 2024 alone, staff sent roughly 4,000
            letters with comments.
          </p>
          <p className="mt-4">
            Each one opens a correspondence that pulls in the reporting team, outside counsel and the auditors, and every
            letter and every reply is later published on EDGAR for investors and competitors to read.
          </p>
          <p className="mt-4">
            But staff ask about the same things again and again: non-GAAP measures, segment reporting, what drove the
            results, China exposure. Those patterns are written down in thousands of public letters. SEC Examiner reads
            them so a team can see the likely questions while there is still time to answer them in the filing itself.
          </p>
        </div>
      </Section>

      <Section id="how" title="How it works" lead="Four steps, the same for a public company's report or your unfiled draft.">
        <ol className="grid gap-x-8 sm:grid-cols-2">
          {STEPS.map((x, i) => (
            <li key={x.t} className="border-t border-rule py-4">
              <div className="flex items-baseline gap-3">
                <span className="head text-[2.4rem] font-black leading-none text-accent">§{i + 1}</span>
                <h3 className="head text-xl font-bold">{x.t}</h3>
              </div>
              <p className="mt-2 text-[15px] leading-relaxed text-muted">{x.d}</p>
            </li>
          ))}
        </ol>
      </Section>

      <Section id="record" title="The record, in public"
        lead="Scored with F1@5: how many of the topics the SEC actually raised were in the top five, net of wrong guesses. Higher is better.">
        <div className="divide-y divide-line border-t border-rule">
          <RuledScale title="Holdout: filings from 2025–26" note={`${hold.n} filings it never saw while being built or chosen`} marks={marks(hold)} />
          <RuledScale title="Selection: filings from 2024" note={`${sel.n} filings, used to decide whether a version ships`} marks={marks(sel)} />
        </div>
        <div className="mt-6 border-t border-rule pt-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="head text-lg font-bold">Every version it has tried</h3>
            {attempts.length > 0 && (
              <span className="text-[13px] text-muted">{attempts.length} tried · {shipped} shipped · {coded} written as code by the system</span>
            )}
          </div>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full min-w-[34rem] border-collapse text-[14px]">
              <thead>
                <tr className="caps text-left text-muted">
                  <th className="border-b border-rule py-1.5 pr-3 font-semibold">Version</th>
                  <th className="border-b border-rule py-1.5 pr-3 font-semibold">Proposed by</th>
                  <th className="border-b border-rule py-1.5 pr-3 text-right font-semibold">Holdout F1</th>
                  <th className="border-b border-rule py-1.5 font-semibold">Judge</th>
                </tr>
              </thead>
              <tbody>
                {(attempts.length ? attempts : []).slice(0, 7).map((a) => (
                  <tr key={a.version}>
                    <td className="num border-b border-line py-1.5 pr-3">{a.version}</td>
                    <td className="border-b border-line py-1.5 pr-3 text-muted">
                      {a.rationale.startsWith("llm-code:") ? "Gemini, wrote code" : a.rationale.startsWith("llm:") ? "Gemini" : a.rationale.startsWith("rule:") ? "Fixed rule" : "Starting recipe"}
                    </td>
                    <td className="num border-b border-line py-1.5 pr-3 text-right">{a.holdout_f1?.toFixed(3) ?? "–"}</td>
                    <td className="border-b border-line py-1.5">
                      {a.decision === "promote"
                        ? <span className="inline-flex items-center gap-1 font-semibold text-good"><Check /> Shipped</span>
                        : <span className="text-muted">Rejected</span>}
                    </td>
                  </tr>
                ))}
                {!attempts.length && (
                  <tr><td colSpan={4} className="py-3 text-muted">Loading the audit log…</td></tr>
                )}
              </tbody>
            </table>
          </div>
          <Link href="/loop/" className="btn-ghost mt-5">See how it improves itself <ArrowRight /></Link>
        </div>
      </Section>

      <Section id="who" title="Who it is for">
        <div className="grid gap-x-10 md:grid-cols-2">
          <div className="border-t border-rule py-4">
            <h3 className="head text-xl font-bold">Reporting and legal teams</h3>
            <ul className="mt-3 space-y-2.5 text-[15px] leading-relaxed">
              <li>Run your draft MD&amp;A or notes before filing and see which topics staff are likely to question.</li>
              <li>Get a checklist of expected disclosures that could not be found, topic by topic.</li>
              <li>See what the SEC asked your company before, and how your industry is being reviewed.</li>
            </ul>
          </div>
          <div className="border-t border-rule py-4">
            <h3 className="head text-xl font-bold">Engineers and hiring managers</h3>
            <ul className="mt-3 space-y-2.5 text-[15px] leading-relaxed">
              <li>A model that improves itself: it proposes changes and writes its own feature code, which is safety-checked and run in a sandbox.</li>
              <li>A hash-sealed judge, point-in-time data and a later-year holdout, so the numbers cannot flatter themselves.</li>
              <li>A web app, REST API and MCP server for Claude or Cursor, all open source.</li>
            </ul>
          </div>
        </div>
      </Section>

      <Section id="privacy" title="Privacy and limits">
        <dl className="grid gap-x-10 text-[15px] leading-relaxed sm:grid-cols-2">
          {[
            ["Your draft is not kept", "Drafts are read in memory and discarded. Nothing you submit is stored, logged or used for training. The model learns only from public SEC letters."],
            ["Free, with a daily limit", "The public demo allows 2 examinations per visitor each day, with no account. Run it on your own machine for unlimited use."],
            ["Use it your way", "Web app, REST API, or the MCP server inside an AI assistant. Install steps are in the README."],
            ["A human decides", "It ranks likely topics from public data. Counsel and auditors make the call. It is not affiliated with the SEC."],
          ].map(([t, d]) => (
            <div key={t} className="border-t border-rule py-4">
              <dt className="head text-lg font-bold">{t}</dt>
              <dd className="mt-1.5 text-muted">{d}</dd>
            </div>
          ))}
        </dl>
      </Section>

      <section aria-labelledby="close-h" className="mt-20 border-y-[3px] border-rule py-10 sm:mt-28">
        <div className="grid items-end gap-8 lg:grid-cols-2">
          <h2 id="close-h" className="head text-[2.6rem] font-black leading-[0.95] text-balance sm:text-[3.4rem]">
            Find the questions before the SEC sends them.
          </h2>
          <div>
            <TickerForm />
            <a href="https://github.com/sivram04/sec-examiner#quick-start" className="mt-4 inline-flex items-center gap-1.5 text-[14px] underline hover:text-accent">
              Run it locally for unlimited use <ArrowUpRight />
            </a>
          </div>
        </div>
      </section>
    </>
  );
}
