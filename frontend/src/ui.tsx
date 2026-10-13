/** NÖBET — Paylaşılan küçük bileşenler ve biçimlendiriciler */
import type { ReactNode } from "react";
import type { Decision } from "./api";

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: string }) {
  return (
    <div className="card stat">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="alert error">{error instanceof Error ? error.message : String(error)}</div>;
}

export function Loading({ what = "Yükleniyor" }: { what?: string }) {
  return <p className="muted">{what}…</p>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="muted" style={{ padding: "1rem 0" }}>{children}</p>;
}

const DECISION_LABEL: Record<Decision, { text: string; cls: string }> = {
  granted: { text: "Kabul", cls: "ok" },
  unknown_credential: { text: "Kayıtsız kart", cls: "warn" },
  revoked: { text: "İptal edilmiş", cls: "danger" },
  duplicate: { text: "Tekrar", cls: "muted" },
  disabled_node: { text: "Okuyucu kapalı", cls: "danger" },
};

export function DecisionBadge({ decision }: { decision: Decision }) {
  const d = DECISION_LABEL[decision] ?? { text: decision, cls: "muted" };
  return <span className={`badge ${d.cls}`}>{d.text}</span>;
}

export const PERSON_TYPE_LABEL: Record<string, string> = {
  student: "Öğrenci",
  staff: "Personel",
  coach: "Koç",
};

/** Sunucu UTC gönderiyor; kurum saatiyle gösterilir. */
export function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("tr-TR", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

export function formatTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("tr-TR", {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

export function relativeFromNow(iso: string | null): string {
  if (!iso) return "hiç";
  const secs = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 60) return `${secs} sn önce`;
  if (secs < 3600) return `${Math.floor(secs / 60)} dk önce`;
  if (secs < 86400) return `${Math.floor(secs / 3600)} sa önce`;
  return `${Math.floor(secs / 86400)} gün önce`;
}
