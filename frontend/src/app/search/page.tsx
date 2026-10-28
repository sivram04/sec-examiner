"use client";

import { useState } from "react";
import { api, today, type Hit } from "@/lib/api";

export default function Search() {
  const [form, setForm] = useState({ ticker: "", q: "", as_of: today() });
  const [hits, setHits] = useState<Hit[]>([]);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setStatus("Searching…");
    setHits([]);
    try {
      const params = Object.fromEntries(Object.entries(form).filter(([, v]) => v));
      const r = await api.search(params);
      setHits(r.hits);
      setStatus(`${r.hits.length} passages in ${r.ms} ms · BM25 + dense, reranked · filed on or before ${form.as_of}`);
    } catch (err) {
      setStatus(`Error: ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <form className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-[110px_1fr_160px_auto]" onSubmit={submit}>
        <input className="field" aria-label="Ticker" placeholder="Ticker" value={form.ticker}
          onChange={(e) => setForm({ ...form, ticker: e.target.value.toUpperCase() })} />
        <input className="field col-span-2 sm:col-span-1" aria-label="Query" placeholder="Search query" required
          value={form.q} onChange={(e) => setForm({ ...form, q: e.target.value })} />
        <input className="field" type="date" aria-label="As of" value={form.as_of}
          onChange={(e) => setForm({ ...form, as_of: e.target.value })} />
        <button className="btn" disabled={busy}>Search</button>
      </form>
      <p className={`mb-3 min-h-5 text-sm ${status.startsWith("Error") ? "text-bad" : "text-muted"}`}>{status}</p>
      {hits.map((h) => (
        <div key={h.id} className="card">
          <div className="flex flex-wrap gap-3 text-[12.5px] text-muted">
            <span className="rounded bg-chip px-1.5 font-mono">{h.ticker}</span>
            <span>{h.form} filed {h.filed}</span>
            <span>Item {h.section} · {h.section_title}</span>
            <a className="text-accent" href={h.url} target="_blank" rel="noopener noreferrer">filing</a>
          </div>
          <p className="mt-2 whitespace-pre-wrap text-[14.5px]">
            {h.text.length > 900 ? `${h.text.slice(0, 900)}…` : h.text}
          </p>
        </div>
      ))}
    </section>
  );
}
