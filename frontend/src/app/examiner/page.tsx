"use client";

import { useState } from "react";
import { api, type ExamResult, type Prediction } from "@/lib/api";

function Bar({ p }: { p: Prediction }) {
  // stacked: how much of the score came from the filing's text vs. the SEC's past letters
  return (
    <div className="flex h-2 w-full overflow-hidden rounded bg-chip" aria-hidden>
      <div className="bg-accent" style={{ width: `${p.from_filing * 100}%` }} />
      <div className="bg-muted/60" style={{ width: `${p.from_history * 100}%` }} />
    </div>
  );
}

function Result({ r }: { r: ExamResult }) {
  return (
    <section>
      <div className="card">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="font-semibold">
            {r.filing.company} · {r.filing.form}
            {r.filing.period ? ` for ${r.filing.period}` : ""}
          </h2>
          <span className="text-[12.5px] text-muted">
            model {r.model} · {r.secs}s · filed {r.filing.filed}
            {r.filing.url && (
              <> · <a className="text-accent" href={r.filing.url} target="_blank" rel="noreferrer">filing</a></>
            )}
          </span>
        </div>
        <p className="mt-1 text-[12.5px] text-muted">
          Read: items {r.sections_read.join(", ")}. Bars show how much of each score came from{" "}
          <span className="text-accent">the filing&apos;s text</span> vs. the SEC&apos;s past letters to this
          company, its industry and the market.
        </p>
      </div>

      <h3 className="mt-5 mb-2 text-sm font-semibold">Most likely SEC comment topics</h3>
      <ol>
        {r.predictions.map((p, i) => (
          <li key={p.topic} className="card">
            <div className="flex items-baseline justify-between gap-3">
              <strong>{i + 1}. {p.label}</strong>
              <span className="font-mono text-[12.5px] text-muted">{p.score.toFixed(2)}</span>
            </div>
            <div className="my-2"><Bar p={p} /></div>
            {p.about && <p className="text-[13px] text-muted">{p.about}</p>}
            {p.missing.length > 0 && (
              <div className="mt-2 text-[13px]">
                <span className="font-semibold">Disclosures we could not find:</span>
                <ul className="mt-1 list-disc pl-5">
                  {p.missing.map((m) => <li key={m}>{m}</li>)}
                </ul>
              </div>
            )}
          </li>
        ))}
      </ol>

      {r.past_letters.length > 0 && (
        <div className="card">
          <h3 className="mb-1 text-sm font-semibold">Past SEC letters to this company</h3>
          <ul className="text-[13px]">
            {r.past_letters.map((L) => (
              <li key={L.date + L.comments}>
                {L.date}: {L.comments} comment{L.comments === 1 ? "" : "s"}
                {L.topics.length ? ` on ${L.topics.join(", ").replaceAll("_", " ")}` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}

      <details className="card text-[13px]">
        <summary className="cursor-pointer">Other topics ({r.others.length})</summary>
        <ul className="mt-2 grid grid-cols-1 gap-x-6 sm:grid-cols-2">
          {r.others.map((o) => (
            <li key={o.topic} className="flex justify-between">
              <span>{o.label}</span><span className="font-mono text-muted">{o.score.toFixed(2)}</span>
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}

export default function ExaminerPage() {
  const [mode, setMode] = useState<"ticker" | "draft">("ticker");
  const [ticker, setTicker] = useState("TSLA");
  const [draft, setDraft] = useState("");
  const [sic, setSic] = useState("");
  const [res, setRes] = useState<ExamResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function run(p: Promise<ExamResult>) {
    setBusy(true);
    setError("");
    setRes(null);
    try {
      setRes(await p);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <div className="mb-3 flex gap-2 text-sm" role="tablist">
        {(["ticker", "draft"] as const).map((m) => (
          <button key={m} role="tab" aria-selected={mode === m} onClick={() => setMode(m)}
            className={`rounded-md border px-3 py-1.5 ${mode === m ? "border-accent text-ink" : "border-line text-muted"}`}>
            {m === "ticker" ? "Latest filing by ticker" : "Paste a draft"}
          </button>
        ))}
      </div>

      {mode === "ticker" ? (
        <form className="mb-4 flex gap-2" onSubmit={(e) => { e.preventDefault(); run(api.examineTicker(ticker)); }}>
          <input className="field w-32" aria-label="Ticker" value={ticker} required
            onChange={(e) => setTicker(e.target.value.toUpperCase())} />
          <button className="btn" disabled={busy}>{busy ? "Examining…" : "Examine"}</button>
        </form>
      ) : (
        <form className="mb-4" onSubmit={(e) => { e.preventDefault(); run(api.examineDraft({ text: draft, sic })); }}>
          <textarea className="field h-48 w-full font-mono text-[13px]" aria-label="Draft filing text"
            placeholder="Paste MD&A, notes or a whole draft 10-K…" value={draft} required
            onChange={(e) => setDraft(e.target.value)} />
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <input className="field w-40" aria-label="SIC code (optional)" placeholder="SIC code (optional)"
              value={sic} onChange={(e) => setSic(e.target.value.replace(/\D/g, ""))} />
            <button className="btn" disabled={busy}>{busy ? "Examining…" : "Examine draft"}</button>
            <span className="text-[12.5px] text-muted">
              Read in memory only. Drafts are never stored or used for training.
            </span>
          </div>
        </form>
      )}

      {busy && mode === "ticker" && (
        <p className="text-sm text-muted">Fetching the latest report from EDGAR and examining it…</p>
      )}
      {error && <p className="text-sm text-bad">Error: {error}</p>}
      {res && <Result r={res} />}
    </section>
  );
}
