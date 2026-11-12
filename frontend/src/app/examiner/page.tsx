"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ArrowRight, ArrowUpRight, Lock } from "@/components/Icons";
import { api, type ExamResult, type Prediction, type Quota } from "@/lib/api";

const REPO = "https://github.com/sivram04/sec-examiner#quick-start";
const EXAMPLES = ["TSLA", "BABA", "NVDA", "AAPL", "JPM", "COIN"];

const SECTION_NAMES: Record<string, string> = {
  "1": "Business", "1A": "Risk factors", "1B": "Staff comments", "1C": "Cybersecurity",
  "3": "Legal proceedings", "5": "Equity market", "7": "MD&A", "7A": "Market risk",
  "8": "Financial statements", "9A": "Controls", "15": "Exhibits and notes",
  "I-1": "Financial statements", "I-2": "MD&A", "II-1A": "Risk factors",
  body: "Full document", other: "Other sections",
};

const SAMPLE_DRAFT = `Management's Discussion and Analysis
Revenue increased 18% to $2.4 billion, primarily due to higher demand. We use Adjusted EBITDA, a
non-GAAP measure, to evaluate performance; Adjusted EBITDA was $610 million.
We have goodwill of $1.2 billion. We operate in two reportable segments.
We have deferred tax assets of $340 million. Our operations in China are conducted in part
through contractual arrangements.`;

const STAGES = {
  ticker: ["Finding the latest report on SEC EDGAR", "Reading business, risk factors, MD&A and notes",
    "Comparing with past SEC letters", "Checking for expected disclosures"],
  draft: ["Reading your draft", "Comparing with past SEC letters", "Checking for expected disclosures"],
};

function level(score: number) {
  return score >= 0.75 ? "High" : score >= 0.5 ? "Medium" : "Lower";
}

function Topic({ p, rank }: { p: Prediction; rank: number }) {
  const total = p.from_filing + p.from_history || 1;
  const filing = Math.round((p.from_filing / total) * 100);
  const l = level(p.score);
  return (
    <li className="border-t border-line py-4">
      <div className="flex items-baseline gap-3">
        <span className="head w-7 shrink-0 text-[1.6rem] font-black leading-none text-accent">{rank}</span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <h3 className="head text-[1.3rem] font-bold leading-tight">{p.label}</h3>
            <span className={`caps ${l === "High" ? "text-ink underline decoration-2 underline-offset-4" : l === "Medium" ? "text-ink" : "text-muted"}`}>{l} likelihood</span>
          </div>
          {p.about && <p className="mt-0.5 text-[14.5px] text-muted">{p.about}</p>}
          <div className="mt-2.5 flex items-center gap-3" title={`${filing}% from the filing's text, ${100 - filing}% from past SEC letters`}>
            <span className="flex h-[5px] flex-1 bg-chip" aria-hidden>
              <span className="bg-accent" style={{ width: `${filing}%` }} />
              <span className="bg-muted/45" style={{ width: `${100 - filing}%` }} />
            </span>
            <span className="num shrink-0 text-[12px] text-muted">{filing}% filing · {100 - filing}% history</span>
          </div>
          {p.missing.length > 0 && (
            <div className="mt-3 flex flex-wrap items-start gap-x-3 gap-y-2">
              <span className="stamp mt-0.5">Not found</span>
              <ul className="flex-1 text-[14.5px] leading-snug">
                {p.missing.map((m) => <li key={m}>{m}</li>)}
              </ul>
            </div>
          )}
        </div>
      </div>
    </li>
  );
}

function Ruling({ r }: { r: ExamResult }) {
  const sections = [...new Set(r.sections_read.map((s) => SECTION_NAMES[s] ?? s))];
  const draft = !r.filing.url;
  return (
    <article className="print" aria-live="polite">
      <div className="caps flex flex-wrap justify-between gap-2 border-b border-rule pb-2 text-muted">
        <span>Ruling · {draft ? "Draft" : "Form"} {r.filing.form}</span>
        <span>{r.filing.period ? `Period ending ${r.filing.period}` : `Examined ${r.filing.filed}`}</span>
      </div>
      <div className="mt-3 flex flex-wrap items-start justify-between gap-3">
        <h2 className="head text-[2.2rem] font-extrabold leading-[1.02] text-balance">{draft ? "Your draft" : r.filing.company}</h2>
        {r.filing.url && (
          <a className="btn-ghost shrink-0" href={r.filing.url} target="_blank" rel="noreferrer">Open filing <ArrowUpRight /></a>
        )}
      </div>
      <p className="mt-3 max-w-[60ch] text-[17px] leading-relaxed">
        SEC staff are most likely to comment on <strong>{r.predictions.slice(0, 3).map((p) => p.label).join(", ")}</strong>.
      </p>
      {r.note && <p className="mt-3 border border-warn/50 bg-warn/10 px-3 py-2 text-[14px] text-warn">{r.note}</p>}

      <ol className="mt-4 border-b border-rule">
        {r.predictions.map((p, i) => <Topic key={p.topic} p={p} rank={i + 1} />)}
      </ol>

      <div className="mt-6 grid gap-x-10 gap-y-6 md:grid-cols-2">
        {!draft && (
          <section>
            <h3 className="caps border-b border-rule pb-1.5">Past SEC letters to this company</h3>
            {r.past_letters.length ? (
              <ul className="text-[14px]">
                {r.past_letters.map((L) => (
                  <li key={L.date + L.comments} className="flex gap-3 border-b border-line py-1.5">
                    <span className="num w-24 shrink-0 text-muted">{L.date}</span>
                    <span>{L.comments} comment{L.comments === 1 ? "" : "s"}{L.topics.length ? `: ${L.topics.join(", ")}` : ""}</span>
                  </li>
                ))}
              </ul>
            ) : <p className="pt-2 text-[14px] text-muted">None in the letter corpus (2021 onward).</p>}
          </section>
        )}
        <section>
          <h3 className="caps border-b border-rule pb-1.5">Less likely topics</h3>
          <ul className="text-[14px]">
            {r.others.slice(0, 8).map((o) => (
              <li key={o.topic} className="flex items-center gap-3 border-b border-line py-1.5">
                <span className="flex-1">{o.label}</span>
                <span className="h-[3px] w-20 bg-chip" aria-hidden><span className="block h-[3px] bg-muted" style={{ width: `${o.score * 100}%` }} /></span>
              </li>
            ))}
          </ul>
        </section>
      </div>
      <p className="mt-5 text-[12.5px] text-muted">
        Read: {sections.join(", ")} · {r.words.toLocaleString()} words · model {r.model} · {r.cached ? "from cache, " : ""}{r.secs}s.
        Statistical prediction from public SEC letters, not legal advice.
      </p>
    </article>
  );
}

function Working({ mode }: { mode: "ticker" | "draft" }) {
  const [step, setStep] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setStep((s) => Math.min(s + 1, STAGES[mode].length - 1)), mode === "ticker" ? 1800 : 500);
    return () => clearInterval(id);
  }, [mode]);
  return (
    <div aria-live="polite" className="border-t border-rule pt-4">
      <ol className="space-y-2 text-[15px]">
        {STAGES[mode].map((s, i) => (
          <li key={s} className={`flex items-center gap-3 transition-opacity duration-300 ${i > step ? "opacity-35" : ""}`}>
            <span className={`h-2 w-2 shrink-0 ${i < step ? "bg-accent" : i === step ? "animate-pulse bg-accent" : "bg-chip"}`} />
            {s}{i === step ? "…" : ""}
          </li>
        ))}
      </ol>
      <div className="mt-6 space-y-3" aria-hidden>
        {[0, 1, 2].map((i) => <div key={i} className="h-16 animate-pulse bg-chip/70" />)}
      </div>
    </div>
  );
}

function Empty() {
  return (
    <div className="border-t border-rule pt-4">
      <h2 className="head text-[1.6rem] font-bold">How to read a ruling</h2>
      <dl className="mt-3 grid gap-x-8 gap-y-4 text-[15px] leading-relaxed sm:grid-cols-2">
        <div><dt className="font-semibold">Ranked topics</dt><dd className="text-muted">The 5 of 23 comment topics staff are most likely to raise, with High, Medium or Lower likelihood.</dd></div>
        <div><dt className="font-semibold">Filing vs. history</dt><dd className="text-muted">How much of each score came from the report&apos;s own words, and how much from what the SEC asked before.</dd></div>
        <div><dt className="font-semibold"><span className="stamp mr-2">Not found</span>marks</dt><dd className="text-muted">Disclosures staff usually expect with that topic that could not be found in the text.</dd></div>
        <div><dt className="font-semibold">Past letters</dt><dd className="text-muted">The company&apos;s recent SEC comment letters and what they were about.</dd></div>
      </dl>
      <p className="mt-6 text-[14px] text-muted">
        How accurate is it? <Link href="/loop/" className="underline hover:text-ink">See the public record</Link>.
      </p>
    </div>
  );
}

export default function ExaminerPage() {
  const [mode, setMode] = useState<"ticker" | "draft">("ticker");
  const [ticker, setTicker] = useState("");
  const [draft, setDraft] = useState("");
  const [sic, setSic] = useState("");
  const [res, setRes] = useState<ExamResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [quota, setQuota] = useState<Quota | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  const refreshQuota = () => api.quota().then(setQuota).catch(() => {});
  const outOfQuota = quota?.limited === true && quota.remaining === 0;

  async function run(p: () => Promise<ExamResult>) {
    setBusy(true);
    setError("");
    setRes(null);
    if (window.matchMedia("(max-width: 1023px)").matches) {
      resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    try {
      setRes(await p());
    } catch (e) {
      const m = (e as Error).message;
      setError(m === "Failed to fetch" ? "Cannot reach the Examiner. Check your connection and try again." : m);
    } finally {
      setBusy(false);
      refreshQuota();
    }
  }

  const examineTicker = (t: string) => {
    const clean = t.trim().toUpperCase();
    if (!clean) return;
    setMode("ticker");
    setTicker(clean);
    run(() => api.examineTicker(clean));
  };

  useEffect(() => {
    refreshQuota();
    // arriving from the landing page with ?ticker=XYZ examines it straight away
    const t = new URLSearchParams(window.location.search).get("ticker");
    if (t) examineTicker(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="grid gap-10 pt-8 lg:grid-cols-[22rem_1fr] lg:gap-14">
      <aside className="lg:sticky lg:top-6 lg:self-start">
        <h1 className="head text-[2.5rem] font-black leading-[0.95] text-balance">Examine a filing</h1>
        <p className="mt-3 text-[15px] leading-relaxed text-muted">
          A public company&apos;s latest 10-K, 10-Q or 20-F, or your own draft before you file it.
        </p>

        <div className="mt-6 grid grid-cols-2 border border-rule" role="tablist" aria-label="What to examine">
          {(["ticker", "draft"] as const).map((m) => (
            <button key={m} role="tab" aria-selected={mode === m}
              onClick={() => { if (m !== mode) { setMode(m); setError(""); setRes(null); } }}
              className={`caps py-2.5 text-[0.75rem] transition-colors ${mode === m ? "bg-ink text-bg" : "text-muted hover:text-ink"}`}>
              {m === "ticker" ? "Company ticker" : "Paste a draft"}
            </button>
          ))}
        </div>

        {mode === "ticker" ? (
          <div className="mt-4">
            <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); examineTicker(ticker); }}>
              <label htmlFor="ticker" className="sr-only">Ticker</label>
              <input id="ticker" className="field num flex-1 text-lg uppercase" placeholder="e.g. TSLA" value={ticker}
                autoComplete="off" onChange={(e) => setTicker(e.target.value.toUpperCase())} />
              <button className="btn" disabled={busy || outOfQuota || !ticker.trim()}>{busy ? "Working" : "Examine"}</button>
            </form>
            <div className="mt-3 flex flex-wrap gap-1.5 text-[13px]">
              {EXAMPLES.map((t) => (
                <button key={t} disabled={busy || outOfQuota} onClick={() => examineTicker(t)}
                  className="num border border-line px-2 py-0.5 hover:border-accent hover:text-accent disabled:opacity-40">{t}</button>
              ))}
            </div>
          </div>
        ) : (
          <form className="mt-4" onSubmit={(e) => { e.preventDefault(); if (draft.trim()) run(() => api.examineDraft({ text: draft, sic })); }}>
            <label htmlFor="draft" className="sr-only">Draft filing text</label>
            <textarea id="draft" className="field h-56 w-full text-[14px] leading-relaxed"
              placeholder="Paste MD&A, notes to the financial statements, or a whole draft 10-K"
              value={draft} onChange={(e) => setDraft(e.target.value)} />
            <div className="mt-2 flex items-center justify-between text-[13px]">
              <button type="button" className="underline hover:text-accent" onClick={() => setDraft(SAMPLE_DRAFT)}>Use a sample</button>
              <span className="num text-muted">{draft.trim() ? draft.trim().split(/\s+/).length.toLocaleString() : 0} words</span>
            </div>
            <div className="mt-3 flex gap-2">
              <label htmlFor="sic" className="sr-only">Industry SIC code, optional</label>
              <input id="sic" className="field num w-36" placeholder="SIC (optional)" inputMode="numeric" value={sic}
                onChange={(e) => setSic(e.target.value.replace(/\D/g, "").slice(0, 4))} />
              <button className="btn flex-1" disabled={busy || outOfQuota || !draft.trim()}>{busy ? "Working" : "Examine draft"}</button>
            </div>
            <p className="mt-3 flex items-start gap-2 text-[13px] text-muted">
              <Lock className="mt-0.5 shrink-0" /> Read in memory only. Never stored, logged or used for training.
            </p>
          </form>
        )}

        {quota?.limited && (
          <div className={`mt-6 border-t border-rule pt-3 text-[14px] ${outOfQuota ? "text-warn" : "text-muted"}`}>
            <div className="flex items-baseline justify-between">
              <span className="caps">Free examinations today</span>
              <span className="num text-[1.1rem] font-bold text-ink">{quota.remaining} / {quota.limit}</span>
            </div>
            <div className="mt-2 flex gap-1" aria-hidden>
              {Array.from({ length: quota.limit }, (_, i) => (
                <span key={i} className={`h-1.5 flex-1 ${i < (quota.remaining ?? 0) ? "bg-accent" : "bg-chip"}`} />
              ))}
            </div>
            <p className="mt-2">
              {outOfQuota ? "You have used today's free examinations. " : ""}Resets at {quota.resets}.{" "}
              <a className="underline hover:text-ink" href={REPO} target="_blank" rel="noreferrer">Run it locally</a> for unlimited use.
            </p>
          </div>
        )}
      </aside>

      <div ref={resultRef} className="min-w-0 scroll-mt-4">
        {error && (
          <div role="alert" className="mb-6 border-2 border-stamp px-4 py-3 text-[15px]">
            <span className="caps mr-2 text-stamp">Could not examine</span>{error}
            {outOfQuota && (
              <a href={REPO} className="mt-2 flex items-center gap-1.5 font-semibold underline" target="_blank" rel="noreferrer">
                Run it on your machine <ArrowRight />
              </a>
            )}
          </div>
        )}
        {busy && <Working mode={mode} />}
        {res && !busy && <Ruling r={res} />}
        {!res && !busy && !error && <Empty />}
      </div>
    </div>
  );
}
