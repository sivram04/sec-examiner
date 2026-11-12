"use client";

import { useEffect, useState } from "react";
import { api, type LoopStatus } from "@/lib/api";

const BASELINE_NAMES: Record<string, string> = {
  base_rate: "Market base rate", recent_base_rate: "Recent market rate",
  industry_rate: "Industry rate", company_history: "Company history",
};

function Score({ title, note, w }: { title: string; note: string; w: LoopStatus["holdout"] }) {
  const best = Math.max(...Object.values(w.baselines));
  return (
    <div className="card">
      <div className="text-[12.5px] text-muted">{title}</div>
      <div className="text-2xl font-semibold">{w.f1?.toFixed(3) ?? "–"}</div>
      <div className="text-[12.5px] text-muted">
        F1@5 on {w.n} filings · best baseline {best.toFixed(3)}
        {w.f1 != null && <span className="text-good"> (+{(w.f1 - best).toFixed(3)})</span>}
      </div>
      <p className="mt-1 text-[12.5px] text-muted">{note}</p>
      <ul className="mt-2 text-[12.5px]">
        {Object.entries(w.baselines).map(([k, v]) => (
          <li key={k} className="flex justify-between"><span>{BASELINE_NAMES[k] ?? k}</span>
            <span className="font-mono text-muted">{v.toFixed(3)}</span></li>
        ))}
      </ul>
    </div>
  );
}

export default function Loop() {
  const [s, setS] = useState<LoopStatus | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.loopStatus().then(setS).catch((e: Error) => setError(e.message)); }, []);

  if (error) return <p className="text-sm text-bad">Error: {error}</p>;
  if (!s) return <p className="text-sm text-muted">Loading…</p>;
  return (
    <section>
      <p className="mb-4 text-[14px] text-muted">
        The Examiner improves itself without anyone writing code: it diagnoses its weak spots,
        proposes a change (Gemini or fixed rules), retrains, and ships the new version only if a
        sealed judge passes it on real SEC letters and it beats the champion. Rejected versions are
        kept in the audit log.
      </p>
      <div className="mb-2 flex flex-wrap gap-2 text-[12.5px]">
        <span className="rounded bg-chip px-2 py-1">champion <strong>{s.champion ?? "none"}</strong></span>
        <span className={`rounded bg-chip px-2 py-1 ${s.judge_sealed ? "text-good" : "text-bad"}`}>
          judge {s.judge_sealed ? "sealed ✓" : "TAMPERED"}
        </span>
        {s.train_window && (
          <span className="rounded bg-chip px-2 py-1">
            trained on {s.trained_on} filings, {s.train_window[0]} to {s.train_window[1]}
          </span>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <Score title="Selection (2024 filings)" w={s.selection}
          note="Used to decide whether a new version is better." />
        <Score title="Holdout (2025-26 filings)" w={s.holdout}
          note="A later year, never used to choose anything: the honest number." />
      </div>

      <h3 className="mt-5 mb-2 text-sm font-semibold">Attempts</h3>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-[13px]">
          <thead>
            <tr className="text-left text-muted">
              <th className="border-b border-line py-1.5 pr-3">Version</th>
              <th className="border-b border-line py-1.5 pr-3">Change</th>
              <th className="border-b border-line py-1.5 pr-3 text-right">Selection</th>
              <th className="border-b border-line py-1.5 pr-3 text-right">Holdout</th>
              <th className="border-b border-line py-1.5">Decision</th>
            </tr>
          </thead>
          <tbody>
            {s.attempts.map((a) => (
              <tr key={a.version} className="align-top">
                <td className="border-b border-line py-1.5 pr-3 font-mono">
                  {a.version}{a.parent ? <span className="text-muted"> ← {a.parent}</span> : ""}
                </td>
                <td className="border-b border-line py-1.5 pr-3">
                  <code className="text-[12px]">{Object.keys(a.changes).length ? JSON.stringify(a.changes) : "bootstrap"}</code>
                  <div className="text-[12px] text-muted">{a.rationale}</div>
                </td>
                <td className="border-b border-line py-1.5 pr-3 text-right font-mono">{a.selection_f1?.toFixed(3)}</td>
                <td className="border-b border-line py-1.5 pr-3 text-right font-mono">{a.holdout_f1?.toFixed(3)}</td>
                <td className={`border-b border-line py-1.5 ${a.decision === "promote" ? "text-good" : "text-bad"}`}>
                  {a.decision}<div className="text-[12px] text-muted">{a.reason}</div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="mt-5 mb-2 text-sm font-semibold">
        Champion recall by topic (holdout): when the SEC raised it, how often we flagged it
      </h3>
      <ul className="grid gap-x-6 gap-y-1 text-[13px] sm:grid-cols-2">
        {s.topic_recall.map((t) => (
          <li key={t.topic} className="flex items-center gap-2">
            <span className="w-52 shrink-0 truncate">{t.label}</span>
            <span className="h-2 flex-1 overflow-hidden rounded bg-chip">
              <span className={`block h-2 ${t.recall >= 0.5 ? "bg-good" : "bg-bad"}`} style={{ width: `${t.recall * 100}%` }} />
            </span>
            <span className="w-24 shrink-0 text-right font-mono text-muted">{t.recall.toFixed(2)} (n={t.n})</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
