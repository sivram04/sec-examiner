import type { RiskChange } from "@/lib/api";

export default function RiskDiff({ data }: { data: RiskChange }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div>
        <h3 className="mb-2 font-semibold">Added</h3>
        {data.added.length === 0 && <p className="text-sm text-muted">None</p>}
        {data.added.map((x) => (
          <div key={x.risk} className="card border-l-4 border-l-bad">
            <strong className="text-[14.5px]">{x.risk}</strong>
            <div className="text-[12.5px] text-muted">first in {x.filing} · {x.since}</div>
          </div>
        ))}
      </div>
      <div>
        <h3 className="mb-2 font-semibold">Removed</h3>
        {data.removed.length === 0 && <p className="text-sm text-muted">None</p>}
        {data.removed.map((x) => (
          <div key={x.risk} className="card border-l-4 border-l-good">
            <strong className="text-[14.5px]">{x.risk}</strong>
            <div className="text-[12.5px] text-muted">absent from {x.filing} · {x.until}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
