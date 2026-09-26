import { Download, Printer } from "lucide-react";
import { marked } from "marked";
import { Button } from "./ui";
import { Modal } from "./ui-extra";

export default function BriefModal({ markdown, source, onClose }: { markdown: string; source: string; onClose: () => void }) {
  const html = marked.parse(markdown) as string;

  const download = () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([markdown], { type: "text/markdown" }));
    a.download = "coordination-brief.md";
    a.click();
  };

  const print = () => {
    const w = window.open("", "_blank");
    if (!w) return;
    w.document.write(`<html><head><title>Coordination brief</title><style>body{font:14px system-ui;max-width:800px;margin:40px auto;color:#1b2447}
      table{border-collapse:collapse;width:100%;font-size:12px}td,th{border:1px solid #dfe6f2;padding:4px 6px;text-align:left}</style></head><body>${html}</body></html>`);
    w.document.close();
    w.print();
  };

  return (
    <Modal title="Coordination brief" width={860} onClose={onClose}
      subtitle={source === "gemini" ? "Summary written by Gemini. Every number comes from OpenCrew's data." : "Every number comes from OpenCrew's data."}
      actions={<>
        <Button className="!px-3 !py-1.5 !text-[13px]" onClick={download}><Download size={15} />Markdown</Button>
        <Button className="!px-3 !py-1.5 !text-[13px]" onClick={print}><Printer size={15} />Print or PDF</Button>
      </>}>
      <article className="brief text-[14px]" dangerouslySetInnerHTML={{ __html: html }} />
    </Modal>
  );
}
