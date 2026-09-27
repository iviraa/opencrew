import { ArrowDown, ArrowUp, ChevronDown, FileSpreadsheet, Table2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Card, Chip, Note, Pill, Row, capital, plural } from "../ui";
import { download, fmt, toCsv, type Table } from "./types";

const PREVIEW = 5;

// a data hand-over in the chat: the first rows in view, the rest behind "show all", sortable, with a csv download
export default function TableCard({ table }: { table: Table }) {
  const [sort, setSort] = useState<{ col: string; dir: 1 | -1 } | null>(null);
  const [all, setAll] = useState(table.rows.length <= PREVIEW + 1);
  const rows = useMemo(() => {
    if (!sort) return table.rows;
    const { col, dir } = sort;
    return [...table.rows].sort((a, b) => {
      const x = a[col], y = b[col];
      if (typeof x === "number" && typeof y === "number") return (x - y) * dir;
      return String(x ?? "").localeCompare(String(y ?? "")) * dir;
    });
  }, [table.rows, sort]);
  const shown = all ? rows : rows.slice(0, PREVIEW);
  const money = (c: string) => /usd|savings|cost/.test(c);
  const chips = Object.entries(table.filters ?? {}).map(([k, v]) => `${k.replace(/_/g, " ")}: ${Array.isArray(v) ? v.join(" to ") : String(v)}`);

  return (
    <Card icon={<Table2 size={15} />} title={`${capital(table.dataset.replace(/_/g, " "))}`} sub={<>{plural(table.count, "row")}{chips.length > 0 && <span> · filtered</span>}</>}
      right={<Pill onClick={() => download(`${table.dataset}.csv`, toCsv(table.columns, table.rows), "text/csv")} title="Download as CSV" icon={<FileSpreadsheet size={13} />} />}>
      {chips.length > 0 && <Row>{chips.map((c) => <Chip key={c}>{c}</Chip>)}</Row>}
      <div className={`thin-scroll overflow-auto rounded-xl border-2 border-line ${all ? "max-h-72" : ""}`}>
        <table className="w-full text-[11px]">
          <thead className="sticky top-0 bg-soft">
            <tr>{table.columns.map((c) => (
              <th key={c} className="cursor-pointer whitespace-nowrap px-2 py-1 text-left font-semibold" onClick={() => setSort((s) => ({ col: c, dir: s?.col === c && s.dir === 1 ? -1 : 1 }))}>
                <span className="inline-flex items-center gap-0.5">{c.replace(/_/g, " ")}{sort?.col === c && (sort.dir === 1 ? <ArrowUp size={10} /> : <ArrowDown size={10} />)}</span>
              </th>
            ))}</tr>
          </thead>
          <tbody>
            {shown.map((r, i) => (
              <tr key={i} className="border-t border-line">
                {table.columns.map((c) => {
                  const v = r[c];
                  const s = typeof v === "string" && v.startsWith("http") ? <a href={v} target="_blank" rel="noreferrer" className="text-grape underline">link</a> : fmt(v, money(c) ? "USD" : undefined);
                  return <td key={c} className={`max-w-[180px] truncate px-2 py-1 ${typeof v === "number" ? "text-right tabular-nums" : ""}`} title={String(v ?? "")}>{s}</td>;
                })}
              </tr>
            ))}
            {!rows.length && <tr><td className="px-2 py-3 text-muted" colSpan={Math.max(table.columns.length, 1)}>No rows match.</td></tr>}
          </tbody>
        </table>
      </div>
      {rows.length > PREVIEW + 1 && (
        <button type="button" onClick={() => setAll(!all)} aria-expanded={all} className="flex items-center justify-center gap-1 rounded-full py-0.5 text-[11px] font-semibold text-grape hover:bg-grape-soft">
          <ChevronDown size={13} className={`transition-transform ${all ? "rotate-180" : ""}`} /> {all ? "Show fewer" : `Show all ${rows.length} rows`}
        </button>
      )}
      {table.count > table.rows.length && <Note>Showing the first {table.rows.length} of {table.count}; the CSV has every row.</Note>}
    </Card>
  );
}
