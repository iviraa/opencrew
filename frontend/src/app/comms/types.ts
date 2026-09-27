// an email crewly drafted: the person edits it, then copies it or confirms a send
export type DraftRecipient = { company_id: string | null; name: string; email: string | null; role?: string; is_demo?: boolean };
export type DraftAttachment = { name: string; content_type: string; size: number };
export type Draft = {
  id: number; kind: "email"; recipient: DraftRecipient; subject: string; body: string; attachments: DraftAttachment[];
  about: Record<string, unknown>; status: "draft" | "sent" | "copied"; sent_at: string | null; created_at?: string;
};
export type SendResult = { sent: boolean; note: string; draft?: Draft };
