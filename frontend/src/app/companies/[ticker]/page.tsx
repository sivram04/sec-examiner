"use client";

import { use, useEffect, useState } from "react";
import RiskDiff from "@/components/RiskDiff";
import { api, today, yearAgo, type FactPoint, type RiskChange } from "@/lib/api";

// filers switch concepts over time (Apple moved from Revenues to the ASC 606 tag in 2018),
// so each row lists concepts in preference order and the first value per year wins
const METRICS: [string, string, string[]][] = [
  ["Revenues", "Revenue", ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"]],
  ["GrossProfit", "Gross profit", ["GrossProfit"]],
  ["OperatingIncomeLoss", "Operating income", ["OperatingIncomeLoss"]],
  ["NetIncomeLoss", "Net income", ["NetIncomeLoss"]],
];

const fmt = (v: number) => `$${(v / 1e9).toLocaleString(undefined, { maximumFractionDigits: 1 })}B`;

export default function Company({ params }: { params: Promise<{ ticker: string }> }) {
  const { ticker } = use(params);
  const [facts, setFacts] = useState<Record<string, FactPoint[]>>({});
  const [risks, setRisks] = useState<RiskChange | null>(null);

  useEffect(() => {
    METRICS.forEach(([key, , concepts]) =>
      Promise.all(concepts.map((c) => api.facts(ticker, c).catch(() => [] as FactPoint[])))
        .then((series) => {
          const byEnd = new Map<string, FactPoint>();
          series.forEach((pts) => pts.forEach((p) => { if (!byEnd.has(p.end)) byEnd.set(p.end, p); }));
          const pts = [...byEnd.values()].sort((a, b) => a.end.localeCompare(b.end)).slice(-5);
          setFacts((f) => ({ ...f, [key]: pts }));
        }));
    api.risks(ticker, yearAgo(), today()).then(setRisks).catch(() => setRisks(null));
  }, [ticker]);

  const years = [...new Set(Object.values(facts).flat().map((p) => p.end))].sort().slice(-5);

  return (
    <section>
      <h2 className="mb-3 font-mono text-xl font-semibold">{ticker}</h2>
      <div className="card overflow-x-auto">
        <h3 className="mb-2 font-semibold">Annual results (XBRL, 10-K)</h3>
        {years.length === 0 ? (
          <p className="text-sm text-muted">No XBRL facts loaded for {ticker}. Run <code>desk facts --tickers {ticker}</code>.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-muted">
                <th className="py-1 pr-4 font-normal">Fiscal year ending</th>
                {years.map((y) => <th key={y} className="py-1 pr-4 text-right font-normal">{y}</th>)}
              </tr>
            </thead>
            <tbody>
              {METRICS.map(([concept, label]) => (
                <tr key={concept} className="border-t border-line">
                  <td className="py-1.5 pr-4">{label}</td>
                  {years.map((y) => {
                    const p = facts[concept]?.find((x) => x.end === y);
                    return <td key={y} className="py-1.5 pr-4 text-right font-mono">{p ? fmt(p.value) : "–"}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <h3 className="mt-6 mb-2 font-semibold">Risk factor changes, last 12 months</h3>
      {risks ? <RiskDiff data={risks} /> : <p className="text-sm text-muted">Loading…</p>}
    </section>
  );
}
