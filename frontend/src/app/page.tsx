"use client";

import { useState } from "react";
import Note from "@/components/Note";
import { api, today, type DeskResponse, type Trace } from "@/lib/api";

function TraceView({ trace }: { trace: Trace[] }) {
  if (!trace.length) return null;
  return (
    <div className="card font-mono text-[12.5px] text-muted">
      {trace.map(({ agent, secs, ...rest }, i) => (
        <div key={i} className="flex gap-3">
          <span className="w-28 shrink-0 text-ink">{agent}</span>
          <span className="w-14 shrink-0 text-right">{secs}s</span>
          <span className="truncate">{JSON.stringify(rest)}</span>
        </div>
      ))}
    </div>
  );
}

export default function Research() {
  const [form, setForm] = useState({ ticker: "AAPL", question: "", as_of: today() });
  const [res, setRes] = useState<DeskResponse | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");

  async function run(p: Promise<DeskResponse>, msg: string) {
    setBusy(true);
    setStatus(msg);
    try {
      const r = await p;
      setRes(r);
      if (r.status === "needs_input") {
        setDraft(JSON.stringify(r.interrupt.plan ?? r.interrupt.flagged, null, 2));
        setStatus("");
      } else {
        const rejected = r.verdicts.filter((v) => !v.ok).length;
        setStatus(`Done. ${r.verdicts.length - rejected} claims verified, ${rejected} rejected by the critic.`);
      }
    } catch (e) {
      setStatus(`Error: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  function resume() {
    if (!res || res.status !== "needs_input") return;
    let answer: Record<string, unknown> = { approve: true };
    if (res.interrupt.type === "approve_plan") {
      try {
        answer = { approve: true, plan: JSON.parse(draft) };
      } catch {
        setStatus("Error: the plan is not valid JSON.");
        return;
      }
    }
    run(api.resume(res.thread, answer), "Running specialists, quant, debate and verification…");
  }

  return (
    <section>
      <form
        className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-[110px_1fr_160px_auto]"
        onSubmit={(e) => {
          e.preventDefault();
          setRes(null);
          run(api.research(form), "Planning…");
        }}
      >
        <input className="field" aria-label="Ticker" value={form.ticker} required
          onChange={(e) => setForm({ ...form, ticker: e.target.value.toUpperCase() })} />
        <input className="field col-span-2 sm:col-span-1" aria-label="Question" required
          placeholder="e.g. Is gross margin at risk from tariffs?" value={form.question}
          onChange={(e) => setForm({ ...form, question: e.target.value })} />
        <input className="field" type="date" aria-label="As of" value={form.as_of}
          onChange={(e) => setForm({ ...form, as_of: e.target.value })} />
        <button className="btn" disabled={busy}>Run desk</button>
      </form>
      <p className={`mb-3 min-h-5 text-sm ${status.startsWith("Error") ? "text-bad" : "text-muted"}`}>{status}</p>

      {res?.status === "needs_input" && (
        <div className="card">
          <strong>
            {res.interrupt.type === "approve_plan"
              ? "Approve or edit the plan before the expensive steps"
              : "Review claims the verifier flagged"}
          </strong>
          <textarea className="field mt-2 w-full font-mono text-[12.5px]" rows={10} value={draft}
            onChange={(e) => setDraft(e.target.value)} />
          <button className="btn mt-2" onClick={resume} disabled={busy}>Continue</button>
        </div>
      )}
      {res && <TraceView trace={res.trace} />}
      {res?.status === "done" && <div className="card"><Note markdown={res.report} /></div>}
    </section>
  );
}
