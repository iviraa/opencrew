import { MapPin } from "lucide-react";
import type { ReviewItem } from "../api";
import { monthYear } from "../format";
import { Button, CloseButton, Empty } from "./ui";

type Props = { items: ReviewItem[]; placingId: number | null; onPlace: (id: number | null) => void; onClose: () => void };

const ORG = { desc: { name: "Dominion Energy SC", dot: "bg-desc" }, gpc: { name: "Georgia Power", dot: "bg-gpc" } } as Record<string, { name: string; dot: string }>;

export default function ReviewPanel({ items, placingId, onPlace, onClose }: Props) {
  return (
    <div className="flex h-full flex-col">
      <div className="px-5 pb-3 pt-4">
        <div className="flex items-center justify-between">
          <h2 className="text-[20px] font-semibold">Projects to place</h2>
          <CloseButton onClick={onClose} />
        </div>
        <p className="mt-1 text-[14px] leading-relaxed text-muted">
          We read these from the filings but couldn't match a substation with confidence. Pick one, then click the map where it belongs.
        </p>
        {placingId != null && (
          <div className="mt-3 rounded-2xl bg-crew-soft px-4 py-2.5 text-[14px] font-semibold text-[#9a5b00]">Click the map to drop the project there</div>
        )}
      </div>
      <ul className="thin-scroll flex-1 overflow-y-auto px-3 pb-3">
        {items.length === 0 && <Empty title="All projects are placed">Every project from the filings is on the map.</Empty>}
        {items.map((it) => {
          const org = ORG[it.org_id] ?? { name: it.org_id.toUpperCase(), dot: "bg-faint" };
          const active = placingId === it.id;
          return (
            <li key={it.id} className={`rounded-2xl px-3 py-3 ${active ? "bg-crew-soft" : "hover:bg-soft"}`}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 text-[13px] text-muted"><span className={`h-2 w-2 rounded-full ${org.dot}`} />{org.name}</div>
                  <div className="mt-0.5 text-[14px] font-semibold leading-snug">{it.name}</div>
                  <div className="mt-0.5 text-[13px] text-muted">
                    {it.in_service ? `Finishes ${monthYear(it.in_service)}` : "Finish date unknown"}
                    {it.endpoints?.length ? `, looked for ${it.endpoints.join(" and ")}` : ""}
                  </div>
                </div>
                <Button variant={active ? "primary" : "soft"} className="!px-3 !py-1.5 !text-[13px] shrink-0" onClick={() => onPlace(active ? null : it.id)}>
                  <MapPin size={15} />{active ? "Cancel" : "Place on map"}
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
