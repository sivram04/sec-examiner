"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type ExamResult, type LoopStatus, type Prediction } from "@/lib/api";

const EXAMPLES = ["TSLA", "NVDA", "AAPL", "BABA", "COIN", "PLTR"];

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

function likelihood(score: number) {
  if (score >= 0.75) return { text: "High", cls: "bg-bad/15 text-bad" };
  if (score >= 0.5) return { text: "Medium", cls: "bg-warn/20 text-warn" };
  return { text: "Lower", cls: "bg-chip text-muted" };
}

function Split({ p }: { p: Prediction }) {
  const total = p.from_filing + p.from_history || 1;
  const filing = Math.round((p.from_filing / total) * 100);
  return (
    <div className="mt-3">
      <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-chip" aria-hidden>
        <div className="bg-accent" style={{ width: `${filing}%` }} />
        <div className="bg-muted/50" style={{ width: `${100 - filing}%` }} />
      </div>
      <div className="mt-1 flex justify-between text-[11.5px] text-muted">
        <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-accent" />{filing}% from this filing&apos;s text</span>
        <span>{100 - filing}% from past SEC letters<span className="ml-1 inline-block h-2 w-2 rounded-full bg-muted/50" /></span>
      </div>
    </div>
  );
}

function TopicCard({ p, rank }: { p: Prediction; rank: number }) {
  const l = likelihood(p.score);
  return (
    <li className="rounded-xl border border-line bg-panel p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-chip text-[12px] font-semibold">{rank}</span>
          <div>
            <h3 className="font-semibold leading-snug">{p.label}</h3>
            {p.about && <p className="mt-0.5 text-[13px] text-muted">{p.about}</p>}
          </div>
        </div>
        <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-[12px] font-medium ${l.cls}`}>{l.text}</span>
      </div>
      <Split p={p} />
      {p.missing.length > 0 && (
        <div className="mt-3 rounded-lg bg-chip/60 px-3 py-2">
          <div className="text-[12.5px] font-medium">Not found in the filing</div>
          <ul className="mt-1 space-y-0.5 text-[13px]">
            {p.missing.map((m) => (
              <li key={m} className="flex gap-2"><span className="text-bad" aria-hidden>✕</span>{m}</li>
            ))}
          </ul>
        </div>
      )}
    </li>
  );
}

function Result({ r }: { r: ExamResult }) {
  const sections = [...new Set(r.sections_read.map((s) => SECTION_NAMES[s] ?? s))];
  return (
    <section className="space-y-4">
      <div className="rounded-xl border border-line bg-panel p-4">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <div className="text-[12px] uppercase tracking-wide text-muted">Examined</div>
            <h2 className="text-lg font-semibold">{r.filing.company}</h2>
            <div className="text-[13px] text-muted">
              {r.filing.form}{r.filing.period ? ` for period ending ${r.filing.period}` : ""}
              {r.filing.filed && r.filing.url ? ` · filed ${r.filing.filed}` : ""}
            </div>
          </div>
          {r.filing.url && (
            <a className="rounded-md border border-line px-3 py-1.5 text-[13px] text-accent hover:bg-chip"
              href={r.filing.url} target="_blank" rel="noreferrer">Open filing ↗</a>
          )}
        </div>
        <p className="mt-3 text-[14px]">
          SEC staff are most likely to comment on{" "}
          <strong>{r.predictions.slice(0, 3).map((p) => p.label).join(", ")}</strong>.
        </p>
        {r.note && (
          <p className="mt-3 rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-[13px] text-warn">{r.note}</p>
        )}
        <div className="mt-2 text-[12px] text-muted">
          Sections read: {sections.join(", ")} · {r.words.toLocaleString()} words · model {r.model} · {r.cached ? "cached, " : ""}{r.secs}s
        </div>
      </div>

      <div>
        <h2 className="mb-2 text-sm font-semibold">Top 5 likely comment topics</h2>
        <ol className="space-y-3">
          {r.predictions.map((p, i) => <TopicCard key={p.topic} p={p} rank={i + 1} />)}
        </ol>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        {r.filing.url && <div className="rounded-xl border border-line bg-panel p-4">
          <h2 className="mb-2 text-sm font-semibold">Past SEC letters to this company</h2>
          {r.past_letters.length ? (
            <ul className="space-y-1.5 text-[13px]">
              {r.past_letters.map((L) => (
                <li key={L.date + L.comments} className="flex gap-3">
                  <span className="w-24 shrink-0 font-mono text-[12px] text-muted">{L.date}</span>
                  <span>{L.comments} comment{L.comments === 1 ? "" : "s"}
                    {L.topics.length ? `: ${L.topics.join(", ")}` : ""}</span>
                </li>
              ))}
            </ul>
          ) : <p className="text-[13px] text-muted">None in our letter corpus (2021 onward).</p>}
        </div>}
        <div className="rounded-xl border border-line bg-panel p-4">
          <h2 className="mb-2 text-sm font-semibold">Less likely topics</h2>
          <ul className="space-y-1 text-[13px]">
            {r.others.slice(0, 8).map((o) => (
              <li key={o.topic} className="flex items-center gap-2">
                <span className="flex-1 truncate">{o.label}</span>
                <span className="h-1.5 w-20 overflow-hidden rounded-full bg-chip">
                  <span className="block h-1.5 bg-muted/60" style={{ width: `${o.score * 100}%` }} />
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

function Loading({ mode }: { mode: string }) {
  return (
    <div className="space-y-3" aria-live="polite">
      <p className="text-sm text-muted">
        {mode === "ticker" ? "Fetching the latest report from SEC EDGAR and reading it…" : "Reading your draft…"}
      </p>
      {[0, 1, 2].map((i) => <div key={i} className="h-24 animate-pulse rounded-xl bg-chip" />)}
    </div>
  );
}

function Intro({ status }: { status: LoopStatus | null }) {
  const h = status?.holdout;
  const best = h ? Math.max(...Object.values(h.baselines)) : null;
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {[
        ["1", "Reads the report", "Business, risk factors, MD&A and the notes of a 10-K, 10-Q or 20-F."],
        ["2", "Compares to SEC history", "What staff asked this company, its industry and the market before the filing date."],
        ["3", "Flags likely comments", "Top topics, and expected disclosures that appear to be missing."],
      ].map(([n, t, d]) => (
        <div key={n} className="rounded-xl border border-line bg-panel p-4">
          <div className="text-[12px] font-semibold text-accent">Step {n}</div>
          <div className="font-semibold">{t}</div>
          <p className="mt-1 text-[13px] text-muted">{d}</p>
        </div>
      ))}
      {h?.f1 != null && best != null && (
        <div className="rounded-xl border border-line bg-panel p-4 sm:col-span-3">
          <p className="text-[13.5px]">
            Tested on <strong>{h.n} real filings from 2025-26</strong> that the model never saw: F1@5 of{" "}
            <strong>{h.f1.toFixed(3)}</strong> vs. {best.toFixed(3)} for the best simple baseline.{" "}
            <Link href="/loop" className="text-accent">See how it improves itself →</Link>
          </p>
        </div>
      )}
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
  const [status, setStatus] = useState<LoopStatus | null>(null);

  useEffect(() => { api.loopStatus().then(setStatus).catch(() => {}); }, []);

  async function run(p: () => Promise<ExamResult>) {
    setBusy(true);
    setError("");
    setRes(null);
    try {
      setRes(await p());
    } catch (e) {
      const m = (e as Error).message;
      setError(m === "Failed to fetch" ? "Cannot reach the Examiner API. Is the backend running?" : m);
    } finally {
      setBusy(false);
    }
  }

  const examineTicker = (t: string) => {
    const clean = t.trim().toUpperCase();
    if (!clean) return;
    setTicker(clean);
    run(() => api.examineTicker(clean));
  };

  return (
    <div className="space-y-6">
      <section>
        <h1 className="text-2xl font-semibold tracking-tight">What will the SEC ask about?</h1>
        <p className="mt-1 max-w-2xl text-[14.5px] text-muted">
          Examine a public company&apos;s latest report, or a draft before you file it. Predictions are
          trained and graded on real SEC comment letters.
        </p>
      </section>

      <section className="rounded-xl border border-line bg-panel p-4">
        <div className="mb-3 inline-flex rounded-lg bg-chip p-1 text-[13px]" role="tablist">
          {(["ticker", "draft"] as const).map((m) => (
            <button key={m} role="tab" aria-selected={mode === m} onClick={() => { if (m !== mode) { setMode(m); setError(""); setRes(null); } }}
              className={`rounded-md px-3 py-1.5 ${mode === m ? "bg-panel font-medium text-ink shadow-sm" : "text-muted hover:text-ink"}`}>
              {m === "ticker" ? "Company ticker" : "Paste a draft"}
            </button>
          ))}
        </div>

        {mode === "ticker" ? (
          <>
            <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); examineTicker(ticker); }}>
              <input className="field flex-1 sm:max-w-xs" aria-label="Ticker" placeholder="Ticker, e.g. TSLA"
                value={ticker} autoComplete="off" onChange={(e) => setTicker(e.target.value.toUpperCase())} />
              <button className="btn" disabled={busy || !ticker.trim()}>{busy ? "Examining…" : "Examine"}</button>
            </form>
            <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[12.5px]">
              <span className="text-muted">Try:</span>
              {EXAMPLES.map((t) => (
                <button key={t} disabled={busy} onClick={() => examineTicker(t)}
                  className="rounded-full border border-line px-2.5 py-0.5 hover:border-accent hover:text-accent disabled:opacity-50">
                  {t}
                </button>
              ))}
            </div>
          </>
        ) : (
          <form onSubmit={(e) => { e.preventDefault(); if (draft.trim()) run(() => api.examineDraft({ text: draft, sic })); }}>
            <textarea className="field h-44 w-full text-[13.5px]" aria-label="Draft filing text"
              placeholder="Paste MD&A, notes to the financial statements, or a whole draft 10-K…"
              value={draft} onChange={(e) => setDraft(e.target.value)} />
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <input className="field w-44" aria-label="Industry SIC code (optional)" placeholder="SIC code (optional)"
                inputMode="numeric" value={sic} onChange={(e) => setSic(e.target.value.replace(/\D/g, "").slice(0, 4))} />
              <button className="btn" disabled={busy || !draft.trim()}>{busy ? "Examining…" : "Examine draft"}</button>
              <button type="button" className="text-[13px] text-accent" onClick={() => setDraft(SAMPLE_DRAFT)}>
                Use a sample
              </button>
            </div>
            <p className="mt-2 text-[12px] text-muted">
              🔒 Read in memory only. Drafts are never stored, logged or used for training.
            </p>
          </form>
        )}
      </section>

      {error && (
        <div role="alert" className="rounded-xl border border-bad/40 bg-bad/10 px-4 py-3 text-[14px] text-bad">{error}</div>
      )}
      {busy && <Loading mode={mode} />}
      {res && <Result r={res} />}
      {!res && !busy && !error && <Intro status={status} />}
    </div>
  );
}
