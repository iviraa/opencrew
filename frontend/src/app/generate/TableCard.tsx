import { ArrowDown, ArrowUp, FileSpreadsheet } from "lucide-react";
import { useMemo, useState } from "react";
import { download, fmt, toCsv, type Table } from "./types";

// a data hand-over in the chat: sortable, scrollable, with the filters that made it and a csv download
export default function TableCard({ table }: { table: Table }) {
  const [sort, setSort] = useState<{ col: string; dir: 1 | -1 } | null>(null);
  const rows = useMemo(() => {
    if (!sort) return table.rows;
    const { col, dir } = sort;
    return [...table.rows].sort((a, b) => {
      const x = a[col], y = b[col];
      if (typeof x === "number" && typeof y === "number") return (x - y) * dir;
      return String(x ?? "").localeCompare(String(y ?? "")) * dir;
    });
  }, [table.rows, sort]);
  const money = (c: string) => /usd|savings|cost/.test(c);
  const chips = Object.entries(table.filters ?? {}).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(" to ") : String(v)}`);

  return (
    <div className="pop-in rounded-2xl border-2 border-pen bg-white p-2">
      <div className="flex items-center gap-2 px-1">
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold capitalize leading-snug">{table.dataset.replace(/_/g, " ")} · {table.count} row{table.count === 1 ? "" : "s"}</div>
          {chips.length > 0 && <div className="mt-0.5 flex flex-wrap gap-1">{chips.map((c) => <span key={c} className="rounded-full bg-soft px-2 py-0.5 text-[11px] text-muted">{c}</span>)}</div>}
        </div>
        <button onClick={() => download(`${table.dataset}.csv`, toCsv(table.columns, table.rows), "text/csv")} aria-label="Download CSV" title="Download CSV" className="grid h-7 w-7 shrink-0 place-items-center rounded-full border-2 border-line hover:border-pen"><FileSpreadsheet size={13} /></button>
      </div>
      <div className="thin-scroll mt-1.5 max-h-64 overflow-auto rounded-xl border-2 border-line">
        <table className="w-full text-[11px]">
          <thead className="sticky top-0 bg-soft">
            <tr>{table.columns.map((c) => (
              <th key={c} className="cursor-pointer whitespace-nowrap px-2 py-1 text-left font-semibold" onClick={() => setSort((s) => ({ col: c, dir: s?.col === c && s.dir === 1 ? -1 : 1 }))}>
                <span className="inline-flex items-center gap-0.5">{c.replace(/_/g, " ")}{sort?.col === c && (sort.dir === 1 ? <ArrowUp size={10} /> : <ArrowDown size={10} />)}</span>
              </th>
            ))}</tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-t border-line">
                {table.columns.map((c) => {
                  const v = r[c];
                  const s = typeof v === "string" && v.startsWith("http") ? <a href={v} target="_blank" rel="noreferrer" className="text-grape underline">link</a> : fmt(v, money(c) ? "USD" : undefined);
                  return <td key={c} className="max-w-[180px] truncate px-2 py-1" title={String(v ?? "")}>{s}</td>;
                })}
              </tr>
            ))}
            {!rows.length && <tr><td className="px-2 py-3 text-muted" colSpan={Math.max(table.columns.length, 1)}>No rows match.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
