import { Fragment, type ReactNode } from "react";

// Renders the Markdown subset the writer agent produces: headings, bullets, tables,
// emphasis and footnote citations. Citations link to the numbered source list.
function inline(s: string, key: string): ReactNode[] {
  return s.split(/(\[\^\d+\]|\*[^*]+\*)/g).filter(Boolean).map((part, i) => {
    const fn = part.match(/^\[\^(\d+)\]$/);
    if (fn) return <sup key={`${key}-${i}`}><a href={`#fn${fn[1]}`}>[{fn[1]}]</a></sup>;
    if (/^\*[^*]+\*$/.test(part)) return <em key={`${key}-${i}`}>{part.slice(1, -1)}</em>;
    return <Fragment key={`${key}-${i}`}>{part}</Fragment>;
  });
}

function linkify(s: string): ReactNode[] {
  return s.split(/(https?:\/\/\S+)/g).map((p, i) =>
    /^https?:\/\//.test(p) ? <a key={i} href={p} target="_blank" rel="noopener noreferrer" className="text-accent break-all">{p}</a> : p,
  );
}

export default function Note({ markdown }: { markdown: string }) {
  const notes: [string, string][] = [];
  const body = markdown.replace(/^\[\^(\d+)\]: (.*)$/gm, (_, n, t) => { notes.push([n, t]); return ""; });
  const out: ReactNode[] = [];
  let list: ReactNode[] = [];
  let table: string[][] = [];
  const flush = (k: number) => {
    if (list.length) { out.push(<ul key={`ul${k}`}>{list}</ul>); list = []; }
    if (table.length) {
      const [head, ...rows] = table;
      out.push(
        <table key={`t${k}`}>
          <thead><tr>{head.map((c, i) => <th key={i}>{inline(c, `h${k}${i}`)}</th>)}</tr></thead>
          <tbody>{rows.map((r, j) => <tr key={j}>{r.map((c, i) => <td key={i}>{inline(c, `c${k}${j}${i}`)}</td>)}</tr>)}</tbody>
        </table>,
      );
      table = [];
    }
  };
  body.split("\n").forEach((line, k) => {
    if (line.startsWith("|")) {
      if (!/^\|[-| ]+\|$/.test(line.trim())) table.push(line.trim().slice(1, -1).split("|").map((c) => c.trim()));
      return;
    }
    if (line.startsWith("- ")) { if (table.length) flush(k); list.push(<li key={k}>{inline(line.slice(2), `l${k}`)}</li>); return; }
    flush(k);
    if (line.startsWith("## ")) out.push(<h2 key={k}>{inline(line.slice(3), `h${k}`)}</h2>);
    else if (line.startsWith("# ")) out.push(<h1 key={k}>{inline(line.slice(2), `h${k}`)}</h1>);
    else if (line.trim()) out.push(<p key={k} className="my-2">{inline(line, `p${k}`)}</p>);
  });
  flush(-1);
  return (
    <article className="note">
      {out}
      {notes.length > 0 && (
        <div className="mt-4 space-y-1 text-[13px] text-muted">
          {notes.map(([n, t]) => <div key={n} id={`fn${n}`}>[{n}] {linkify(t)}</div>)}
        </div>
      )}
    </article>
  );
}
