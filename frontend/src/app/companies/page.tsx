"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type Company } from "@/lib/api";

export default function Companies() {
  const [rows, setRows] = useState<Company[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.companies().then(setRows).catch((e: Error) => setError(e.message));
  }, []);

  if (error) return <p className="text-sm text-bad">Error: {error}</p>;
  if (!rows) return <p className="text-sm text-muted">Loading…</p>;
  return (
    <section>
      <p className="mb-3 text-sm text-muted">{rows.length} companies in the corpus</p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
        {rows.map((c) => (
          <Link key={c.ticker} href={`/companies/${c.ticker}`} className="card mb-0 hover:border-accent">
            <div className="font-mono font-semibold">{c.ticker}</div>
            <div className="text-[12.5px] text-muted">{c.documents} filings · latest {c.latest_filing}</div>
          </Link>
        ))}
      </div>
    </section>
  );
}
