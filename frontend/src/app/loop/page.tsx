"use client";

import { useEffect, useState } from "react";
import { Check } from "@/components/Icons";
import RuledScale from "@/components/RuledScale";
import { api, type Attempt, type LoopStatus } from "@/lib/api";

const BASELINE_NAMES: Record<string, string> = {
  base_rate: "Market base rate", recent_base_rate: "Recent market rate",
  industry_rate: "Industry rate", company_history: "Company's own history",
};

const CHANGE_NAMES: Record<string, string> = {
  ngram_max: "phrase length", min_df: "min. word frequency", max_features: "vocabulary size",
  val_fraction: "validation share", prior_company: "company-history weight",
  prior_industry: "industry weight", prior_recent: "recent-trend weight", embed_grid: "meaning embeddings",
  gaps: "disclosure-gap checks", plugin: "generated feature code", c_grid: "regularisation",
  weight_grid: "text vs. history weights", sections: "sections read", max_chars: "text length",
  class_weight: "class balancing", recent_days: "recent window",
};

const RULE_WHY: Record<string, string> = {
  weak_topic: "Targets topics the champion often misses",
  validation_overstates: "Validation looked better than real results",
  signal_unused: "Puts more weight on an under-used signal",
  slow: "Makes predictions faster", slow_training: "Makes training faster",
  gate_fail: "Champion failed a judge check",
};

function describe(changes: Record<string, unknown>): string[] {
  const keys = Object.keys(changes);
  if (!keys.length) return ["starting recipe"];
  return keys.map((k) => {
    const v = changes[k];
    const val = k === "plugin" ? String(v) : Array.isArray(v) ? (k === "embed_grid" ? "on" : v.join(", ")) : v === true ? "on" : String(v);
    return `${CHANGE_NAMES[k] ?? k}: ${val}`;
  });
}

function source(a: Attempt) {
  if (a.rationale.startsWith("llm-code:")) return "Gemini wrote code";
  if (a.rationale.startsWith("llm:")) return "Gemini";
  if (a.rationale.startsWith("rule:")) return "Fixed rule";
  return "Starting recipe";
}

function why(a: Attempt) {
  const raw = a.rationale.replace(/^(llm-code|llm|rule|bootstrap):\s*/, "");
  if (a.rationale.startsWith("rule:")) return RULE_WHY[raw.replace(/^address\s+/, "")] ?? raw.replaceAll("_", " ");
  if (a.rationale.startsWith("bootstrap")) return "First version on the 2021–2026 data, using the best earlier recipe";
  return raw;
}

const STEPS = [
  ["Diagnose", "Finds topics the champion misses, overfitting, and slow steps."],
  ["Propose", "Gemini or a fixed rule suggests a settings change, or Gemini writes new feature code."],
  ["Check and sandbox", "Code is statically checked and run in an isolated interpreter with a time limit."],
  ["Judge", "The sealed judge grades it on real SEC letters. It ships only if it passes and beats the champion."],
];

export default function Loop() {
  const [s, setS] = useState<LoopStatus | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.loopStatus().then(setS).catch((e: Error) =>
      setError(e.message === "Failed to fetch" ? "Cannot reach the Examiner. Check your connection and try again." : e.message));
  }, []);

  const marks = (w: LoopStatus["holdout"]) => [
    { label: "SEC Examiner (champion)", value: w.f1 ?? 0, ours: true },
    ...Object.entries(w.baselines).map(([k, v]) => ({ label: BASELINE_NAMES[k] ?? k, value: v })),
  ];
  const shipped = s?.attempts.filter((a) => a.decision === "promote").length ?? 0;
  const coded = s?.attempts.filter((a) => a.rationale.startsWith("llm-code:")).length ?? 0;

  return (
    <div className="pt-8">
      <h1 className="head max-w-4xl text-[2.9rem] font-black leading-[0.95] text-balance sm:text-[3.8rem]">
        It improves itself. A sealed judge decides what ships.
      </h1>
      <p className="mt-4 max-w-[62ch] text-[17px] leading-relaxed">
        No one writes code for an update. The system finds its weak spots, proposes a change or writes new code,
        retrains, and ships the new version only if the judge passes it on real SEC letters and it beats the
        current champion. Rejected attempts stay on the record below.
      </p>

      <ol className="mt-8 grid border-y border-rule sm:grid-cols-2 lg:grid-cols-4">
        {STEPS.map(([t, d], i) => (
          <li key={t} className={`py-4 sm:px-4 ${i ? "border-t border-line sm:border-t-0 sm:border-l" : ""} ${i === 2 ? "sm:border-l-0 lg:border-l" : ""}`}>
            <div className="flex items-baseline gap-2">
              <span className="head text-[1.8rem] font-black leading-none text-accent">§{i + 1}</span>
              <span className="head text-lg font-bold">{t}</span>
            </div>
            <p className="mt-1.5 text-[14px] leading-relaxed text-muted">{d}</p>
          </li>
        ))}
      </ol>

      {error && <div role="alert" className="mt-8 border-2 border-stamp px-4 py-3"><span className="caps mr-2 text-stamp">Unavailable</span>{error}</div>}
      {!s && !error && <div className="mt-8 space-y-3" aria-hidden>{[0, 1, 2].map((i) => <div key={i} className="h-20 animate-pulse bg-chip/70" />)}</div>}

      {s && (
        <>
          <div className="mt-8 flex flex-wrap gap-x-8 gap-y-2 text-[15px]">
            <span>Champion <strong className="num">{s.champion ?? "none"}</strong></span>
            <span><strong className="num">{s.attempts.length}</strong> versions tried · <strong className="num">{shipped}</strong> shipped · <strong className="num">{coded}</strong> written as code</span>
            <span className={`inline-flex items-center gap-1.5 font-semibold ${s.judge_sealed ? "text-good" : "text-stamp"}`}>
              {s.judge_sealed ? <><Check /> Judge sealed, files unchanged</> : "Judge files changed since sealing"}
            </span>
            {s.train_window && <span className="text-muted">Trained on {s.trained_on?.toLocaleString()} filings, {s.train_window[0].slice(0, 4)}–{s.train_window[1].slice(0, 4)}</span>}
          </div>

          <section aria-labelledby="scores" className="rule-heavy mt-6">
            <h2 id="scores" className="sr-only">Scores against baselines</h2>
            <div className="grid gap-x-12 lg:grid-cols-2">
              <RuledScale title="Holdout: 2025–26 filings" note={`${s.holdout.n} filings, never used to choose`} marks={marks(s.holdout)} />
              <RuledScale title="Selection: 2024 filings" note={`${s.selection.n} filings, decides what ships`} marks={marks(s.selection)} />
            </div>
          </section>

          <section aria-labelledby="attempts" className="rule-heavy mt-10 pt-4">
            <h2 id="attempts" className="head text-[2rem] font-extrabold">Every version tried, newest first</h2>
            <ol className="mt-3">
              {s.attempts.map((a) => {
                const promoted = a.decision === "promote";
                return (
                  <li key={a.version} className="grid gap-x-6 gap-y-2 border-t border-line py-4 md:grid-cols-[7rem_1fr_11rem]">
                    <div>
                      <div className="head text-[1.6rem] font-black leading-none">{a.version}</div>
                      <div className="mt-1 text-[12.5px] text-muted">{a.parent ? `from ${a.parent}` : "first version"}{a.version === s.champion ? " · champion" : ""}</div>
                    </div>
                    <div className="min-w-0">
                      <div className="caps text-accent">{source(a)}</div>
                      <div className="mt-1 flex flex-wrap gap-1.5">
                        {describe(a.changes).map((c) => <span key={c} className="num border border-line px-1.5 py-0.5 text-[12.5px]">{c}</span>)}
                      </div>
                      <p className="mt-1.5 text-[14px] leading-relaxed text-muted [overflow-wrap:anywhere]">{why(a)}</p>
                    </div>
                    <div className="md:text-right">
                      {promoted ? <span className="inline-flex items-center gap-1 font-semibold text-good"><Check /> Shipped</span> : <span className="stamp">Rejected</span>}
                      <div className="num mt-2 text-[13px]">sel {a.selection_f1?.toFixed(3) ?? "–"} · hold {a.holdout_f1?.toFixed(3) ?? "–"}</div>
                      <div className="mt-1 text-[12.5px] text-muted">{a.reason}</div>
                    </div>
                  </li>
                );
              })}
            </ol>
          </section>

          <section aria-labelledby="recall" className="rule-heavy mt-10 pt-4">
            <h2 id="recall" className="head text-[2rem] font-extrabold">Where the champion is strong, and where it is not</h2>
            <p className="mt-1 text-[15px] text-muted">On the holdout: when the SEC raised a topic, how often it was in the top five.</p>
            <ul className="mt-4 grid gap-x-12 md:grid-cols-2">
              {s.topic_recall.map((t) => (
                <li key={t.topic} className="flex items-center gap-3 border-b border-line py-1.5 text-[14px]">
                  <span className="w-48 shrink-0 leading-snug">{t.label}</span>
                  <span className="h-[5px] flex-1 bg-chip" aria-hidden>
                    <span className={`block h-[5px] ${t.recall >= 0.6 ? "bg-accent" : t.recall >= 0.3 ? "bg-muted" : "bg-ink/25"}`} style={{ width: `${Math.max(t.recall * 100, 2)}%` }} />
                  </span>
                  <span className="num w-10 shrink-0 text-right">{Math.round(t.recall * 100)}%</span>
                  <span className="num w-12 shrink-0 text-right text-[12px] text-muted">n={t.n}</span>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  );
}
