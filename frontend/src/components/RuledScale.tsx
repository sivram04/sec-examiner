// Every number is drawn on a ruled scale next to what it must beat, never as a lone stat.
type Mark = { label: string; value: number; ours?: boolean };

export default function RuledScale({ title, note, marks, min = 0.26, max = 0.38 }:
  { title: string; note: string; marks: Mark[]; min?: number; max?: number }) {
  const pos = (v: number) => `${((v - min) / (max - min)) * 100}%`;
  const ticks = Array.from({ length: Math.round((max - min) / 0.01) + 1 }, (_, i) => +(min + i * 0.01).toFixed(2));
  const sorted = [...marks].sort((a, b) => b.value - a.value);
  return (
    <figure className="py-5">
      <figcaption className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="head text-lg font-bold">{title}</span>
        <span className="text-[13px] text-muted">{note}</span>
      </figcaption>
      <div className="relative mt-4 h-14" role="img"
        aria-label={`${title}: ${sorted.map((m) => `${m.label} ${m.value.toFixed(3)}`).join(", ")}`}>
        <div className="absolute inset-x-0 top-7 border-t border-rule" />
        {ticks.map((t, i) => (
          <div key={t} className="absolute top-7" style={{ left: pos(t) }}>
            <div className={`-translate-x-1/2 border-l border-rule ${i % 2 === 0 ? "h-2.5" : "h-1.5"}`} />
            {i % 2 === 0 && <div className="num -translate-x-1/2 pt-0.5 text-[12px] text-muted">{t.toFixed(2)}</div>}
          </div>
        ))}
        {marks.filter((m) => !m.ours).map((m) => (
          <div key={m.label} className="absolute top-3.5 h-3.5 w-px -translate-x-1/2 bg-muted" style={{ left: pos(m.value) }} title={`${m.label} ${m.value.toFixed(3)}`} />
        ))}
        {marks.filter((m) => m.ours).map((m) => (
          <div key={m.label} className="absolute top-0 -translate-x-1/2 text-center" style={{ left: pos(m.value) }}>
            <div className="num whitespace-nowrap text-[12px] font-bold text-accent">{m.value.toFixed(3)}</div>
            <div className="mx-auto h-4 w-[3px] bg-accent" />
          </div>
        ))}
      </div>
      <ul className="mt-2 grid grid-cols-1 gap-x-6 gap-y-0.5 text-[13px] sm:grid-cols-2">
        {sorted.map((m) => (
          <li key={m.label} className={`flex justify-between gap-3 border-b border-dotted border-line py-0.5 ${m.ours ? "font-semibold text-accent" : "text-muted"}`}>
            <span>{m.label}</span><span className="num">{m.value.toFixed(3)}</span>
          </li>
        ))}
      </ul>
    </figure>
  );
}
