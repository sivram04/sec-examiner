"use client";

import { useEffect, useState } from "react";
import Note from "@/components/Note";
import { api, type ReportRow } from "@/lib/api";

export default function Reports() {
  const [rows, setRows] = useState<ReportRow[] | null>(null);
  const [open, setOpen] = useState<Record<number, string>>({});
  const [error, setError] = useState("");

  useEffect(() => {
    api.reports().then(setRows).catch((e: Error) => setError(e.message));
  }, []);

  async function toggle(id: number) {
    if (open[id]) {
      return setOpen((o) => Object.fromEntries(Object.entries(o).filter(([k]) => Number(k) !== id)));
    }
    const r = await api.report(id);
    setOpen((o) => ({ ...o, [id]: r.report }));
  }

  if (error) return <p className="text-sm text-bad">Error: {error}</p>;
  if (!rows) return <p className="text-sm text-muted">Loading…</p>;
  if (!rows.length) return <p className="text-sm text-muted">No reports yet. Run the desk from the Research tab.</p>;
  return (
    <section>
      {rows.map((r) => (
        <div key={r.id} className="card">
          <button className="text-left text-accent" onClick={() => toggle(r.id)}>
            <strong>{r.ticker}</strong>: {r.question}
          </button>
          <div className="text-[12.5px] text-muted">
            as of {r.as_of} · {new Date(r.created * 1000).toLocaleString()}
          </div>
          {open[r.id] && <div className="mt-3"><Note markdown={open[r.id]} /></div>}
        </div>
      ))}
    </section>
  );
}
