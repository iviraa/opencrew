import { ExternalLink, MapPin, Newspaper } from "lucide-react";
import type { NewsPin } from "../api";
import { NEWS_TOPIC } from "../format";
import { CloseButton, Sheet } from "./ui";

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }) : "");

export default function NewsCard({ pin, onClose }: { pin: NewsPin; onClose: () => void }) {
  return (
    <Sheet>
      <div className="flex items-start justify-between gap-3 px-5 pb-2 pt-4">
        <div className="flex items-center gap-2">
          <span className="grid h-9 w-9 place-items-center rounded-full bg-soft" style={{ boxShadow: `0 0 0 3px ${NEWS_TOPIC[pin.topic].color}` }}><Newspaper size={17} /></span>
          <div>
            <div className="display text-[18px] font-semibold leading-tight">News near this site</div>
            <div className="text-[13px] text-muted">{pin.count} {pin.count === 1 ? "story" : "stories"}</div>
          </div>
        </div>
        <CloseButton onClick={onClose} />
      </div>
      <div className="px-5">
        <div className="flex flex-wrap items-center gap-2 text-[13px]">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-soft px-3 py-1 font-semibold"><MapPin size={14} /> Near {pin.near_name}, {pin.near_mi} mi</span>
          <span className={`rounded-full px-3 py-1 font-semibold ${pin.verified ? "bg-save-soft text-save" : "bg-warn-soft text-warn"}`}>
            {pin.verified ? "Confirmed by an official report" : "Not confirmed yet"}
          </span>
        </div>
      </div>
      <ul className="thin-scroll mt-3 min-h-0 flex-1 space-y-3 overflow-y-auto px-5 pb-5">
        {pin.articles.map((a) => (
          <li key={a.url} className="rounded-2xl bg-soft p-4">
            <span className="inline-flex items-center gap-1.5 text-[12px] font-semibold" style={{ color: NEWS_TOPIC[a.topic].color }}>
              <span className="h-2 w-2 rounded-full" style={{ background: NEWS_TOPIC[a.topic].color }} /> {NEWS_TOPIC[a.topic].label}
            </span>
            <div className="mt-1 text-[15px] font-semibold leading-snug">{a.title}</div>
            {a.quote && <p className="mt-1.5 line-clamp-2 text-[13px] text-muted">{a.quote}</p>}
            <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[12px] text-faint">
              <span>{a.source}{a.published ? `, ${when(a.published)}` : ""}{a.copies > 1 ? `, also in ${a.copies - 1} other ${a.copies === 2 ? "outlet" : "outlets"}` : ""}</span>
              <a href={a.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-semibold text-desc hover:underline">
                Read the story <ExternalLink size={13} />
              </a>
            </div>
          </li>
        ))}
      </ul>
    </Sheet>
  );
}
