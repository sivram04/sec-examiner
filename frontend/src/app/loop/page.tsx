"use client";

import { useEffect, useState } from "react";
import { api, type Attempt, type LoopStatus } from "@/lib/api";

const BASELINE_NAMES: Record<string, string> = {
  base_rate: "Market base rate", recent_base_rate: "Recent market rate",
  industry_rate: "Industry rate", company_history: "Company's own history",
};

const CHANGE_NAMES: Record<string, string> = {
  ngram_max: "phrase length", min_df: "min. word frequency", max_features: "vocabulary size",
  val_fraction: "validation share", prior_company: "company-history weight",
  prior_industry: "industry weight", prior_recent: "recent-trend weight", embed_grid: "meaning embeddings",
  gaps: "disclosure-gap checks", plugin: "generated feature code", c_grid: "regularisation", weight_grid: "text vs. history weights",
  sections: "sections read", max_chars: "text length", class_weight: "class balancing",
  recent_days: "recent window",
};

function describe(changes: Record<string, unknown>): string[] {
  const keys = Object.keys(changes);
  if (!keys.length) return ["Starting recipe"];
  return keys.map((k) => {
    const v = changes[k];
    const val = Array.isArray(v) ? (k === "embed_grid" ? "on" : v.join(", ")) : v === true ? "on" : String(v);
    return `${CHANGE_NAMES[k] ?? k}: ${val}`;
  });
}

function Score({ title, note, w }: { title: string; note: string; w: LoopStatus["holdout"] }) {
  const entries = Object.entries(w.baselines);
  const best = Math.max(...entries.map(([, v]) => v));
  const max = Math.max(best, w.f1 ?? 0) || 1;
  return (
    <div className="rounded-xl border border-line bg-panel p-4">
      <div className="text-[12.5px] text-muted">{title}</div>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="text-3xl font-semibold tracking-tight">{w.f1?.toFixed(3) ?? "–"}</span>
        {w.f1 != null && (
          <span className="rounded-full bg-good/15 px-2 py-0.5 text-[12px] font-medium text-good">
            +{(w.f1 - best).toFixed(3)} vs. best baseline
          </span>
        )}
      </div>
      <p className="text-[12.5px] text-muted">F1@5 on {w.n} filings. {note}</p>
      <ul className="mt-3 space-y-1.5 text-[12.5px]">
        <li className="flex items-center gap-2">
          <span className="w-40 shrink-0 font-medium">Examiner</span>
          <span className="h-2 flex-1 rounded-full bg-chip"><span className="block h-2 rounded-full bg-accent" style={{ width: `${((w.f1 ?? 0) / max) * 100}%` }} /></span>
          <span className="w-12 text-right font-mono">{w.f1?.toFixed(3)}</span>
        </li>
        {entries.map(([k, v]) => (
          <li key={k} className="flex items-center gap-2 text-muted">
            <span className="w-40 shrink-0">{BASELINE_NAMES[k] ?? k}</span>
            <span className="h-2 flex-1 rounded-full bg-chip"><span className="block h-2 rounded-full bg-muted/50" style={{ width: `${(v / max) * 100}%` }} /></span>
            <span className="w-12 text-right font-mono">{v.toFixed(3)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function AttemptRow({ a, champion }: { a: Attempt; champion: string | null }) {
  const promoted = a.decision === "promote";
  const source = a.rationale.startsWith("llm-code:") ? "Gemini (wrote code)" : a.rationale.startsWith("llm:") ? "Gemini" : a.rationale.startsWith("rule:") ? "Rule" : "Bootstrap";
  const RULE_WHY: Record<string, string> = {
    weak_topic: "Targets topics the champion often misses",
    validation_overstates: "Validation looked better than real results",
    signal_unused: "Puts more weight on an under-used signal",
    slow: "Makes predictions faster", slow_training: "Makes training faster",
    gate_fail: "Champion failed a judge check",
  };
  const raw = a.rationale.replace(/^(llm-code|llm|rule|bootstrap):\s*/, "");
  const why = source === "Rule"
    ? RULE_WHY[raw.replace(/^address\s+/, "")] ?? raw.replaceAll("_", " ")
    : source === "Bootstrap" ? "First version on the 2021–2026 dataset, using the best earlier recipe" : raw;
  return (
    <li className="rounded-xl border border-line bg-panel p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-mono font-semibold">{a.version}</span>
          {a.version === champion && <span className="rounded-full bg-accent px-2 py-0.5 text-[11px] font-medium text-accent-ink">champion</span>}
          {a.parent && <span className="text-[12px] text-muted">built from {a.parent}</span>}
          <span className="rounded bg-chip px-1.5 py-0.5 text-[11px] text-muted">proposed by {source}</span>
        </div>
        <span className={`rounded-full px-2.5 py-0.5 text-[12px] font-medium ${promoted ? "bg-good/15 text-good" : "bg-bad/10 text-bad"}`}>
          {promoted ? "✓ Shipped" : "✕ Rejected"}
        </span>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {describe(a.changes).map((c) => <span key={c} className="rounded-md border border-line px-2 py-0.5 text-[12px]">{c}</span>)}
      </div>
      {why && <p className="mt-2 line-clamp-2 text-[12.5px] text-muted" title={why}>{why}</p>}
      <div className="mt-2 flex flex-wrap gap-x-5 text-[12.5px]">
        <span>Selection <span className="font-mono">{a.selection_f1?.toFixed(3) ?? "–"}</span></span>
        <span>Holdout <span className="font-mono">{a.holdout_f1?.toFixed(3) ?? "–"}</span></span>
        <span className="text-muted">{a.reason}</span>
      </div>
    </li>
  );
}

export default function Loop() {
  const [s, setS] = useState<LoopStatus | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.loopStatus().then(setS).catch((e: Error) =>
      setError(e.message === "Failed to fetch" ? "Cannot reach the Examiner API. Is the backend running?" : e.message));
  }, []);

  if (error) return <div role="alert" className="rounded-xl border border-bad/40 bg-bad/10 px-4 py-3 text-bad">{error}</div>;
  if (!s) return <div className="space-y-3">{[0, 1].map((i) => <div key={i} className="h-40 animate-pulse rounded-xl bg-chip" />)}</div>;
  const shipped = s.attempts.filter((a) => a.decision === "promote").length;
  return (
    <div className="space-y-6">
      <section>
        <h1 className="text-2xl font-semibold tracking-tight">How the Examiner improves itself</h1>
        <p className="mt-1 max-w-3xl text-[14.5px] text-muted">
          No one writes code for an update. The system finds its weak topics, proposes a change,
          retrains, and ships the new version only if a sealed judge passes it on real SEC letters
          and it beats the current champion.
        </p>
      </section>

      <ol className="grid gap-2 text-[13px] sm:grid-cols-4">
        {["Diagnose weak topics", "Propose a change", "Retrain and grade", "Ship only if better"].map((t, i) => (
          <li key={t} className="flex items-center gap-2 rounded-lg border border-line bg-panel px-3 py-2">
            <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-accent text-[11px] font-semibold text-accent-ink">{i + 1}</span>{t}
          </li>
        ))}
      </ol>

      <div className="flex flex-wrap gap-2 text-[12.5px]">
        <span className="rounded-full bg-chip px-3 py-1">Champion <strong>{s.champion ?? "none"}</strong></span>
        <span className="rounded-full bg-chip px-3 py-1">{s.attempts.length} versions tried · {shipped} shipped</span>
        <span className={`rounded-full px-3 py-1 ${s.judge_sealed ? "bg-good/15 text-good" : "bg-bad/15 text-bad"}`}>
          {s.judge_sealed ? "✓ Judge sealed (untampered)" : "✕ Judge files changed"}
        </span>
        {s.train_window && (
          <span className="rounded-full bg-chip px-3 py-1">Trained on {s.trained_on?.toLocaleString()} filings, {s.train_window[0].slice(0, 4)}–{s.train_window[1].slice(0, 4)}</span>
        )}
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <Score title="Selection · 2024 filings" w={s.selection} note="Used to decide whether a version ships." />
        <Score title="Holdout · 2025–26 filings" w={s.holdout} note="A later year, never used to choose. The honest number." />
      </div>

      <section>
        <h2 className="mb-2 text-sm font-semibold">Every version tried, newest first</h2>
        <ol className="space-y-3">{s.attempts.map((a) => <AttemptRow key={a.version} a={a} champion={s.champion} />)}</ol>
      </section>

      <section className="rounded-xl border border-line bg-panel p-4">
        <h2 className="text-sm font-semibold">Where the champion is strong and weak</h2>
        <p className="mb-3 text-[12.5px] text-muted">Holdout recall: when the SEC raised a topic, how often it was in our top 5.</p>
        <ul className="grid gap-x-8 gap-y-1.5 text-[13px] md:grid-cols-2">
          {s.topic_recall.map((t) => (
            <li key={t.topic} className="flex items-center gap-2">
              <span className="w-44 shrink-0 truncate" title={t.label}>{t.label}</span>
              <span className="h-2 flex-1 overflow-hidden rounded-full bg-chip">
                <span className={`block h-2 rounded-full ${t.recall >= 0.6 ? "bg-good" : t.recall >= 0.3 ? "bg-warn" : "bg-bad"}`} style={{ width: `${Math.max(t.recall * 100, 2)}%` }} />
              </span>
              <span className="w-10 shrink-0 text-right font-mono">{Math.round(t.recall * 100)}%</span>
              <span className="w-12 shrink-0 text-right text-[11.5px] text-muted">n={t.n}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
