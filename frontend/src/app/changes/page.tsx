"use client";

import { useState } from "react";
import RiskDiff from "@/components/RiskDiff";
import { api, today, yearAgo, type RiskChange } from "@/lib/api";

export default function Changes() {
  const [form, setForm] = useState({ ticker: "MSFT", start: yearAgo(), end: today() });
  const [data, setData] = useState<RiskChange | null>(null);
  const [status, setStatus] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    try {
      const r = await api.risks(form.ticker, form.start, form.end);
      setData(r);
      setStatus(`${r.added.length} risk factors added, ${r.removed.length} removed between ${form.start} and ${form.end} (10-K Item 1A)`);
    } catch (err) {
      setStatus(`Error: ${(err as Error).message}`);
    }
  }

  return (
    <section>
      <form className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-[110px_160px_160px_auto]" onSubmit={submit}>
        <input className="field" aria-label="Ticker" required value={form.ticker}
          onChange={(e) => setForm({ ...form, ticker: e.target.value.toUpperCase() })} />
        <input className="field" type="date" aria-label="From" value={form.start}
          onChange={(e) => setForm({ ...form, start: e.target.value })} />
        <input className="field" type="date" aria-label="To" value={form.end}
          onChange={(e) => setForm({ ...form, end: e.target.value })} />
        <button className="btn">Compare</button>
      </form>
      <p className={`mb-3 min-h-5 text-sm ${status.startsWith("Error") ? "text-bad" : "text-muted"}`}>{status}</p>
      {data && <RiskDiff data={data} />}
    </section>
  );
}
