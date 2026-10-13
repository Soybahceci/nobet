/**
 * NÖBET — WhatsApp sohbet ekranı
 *
 * Veli mesaj yazdığında sistem önce otomatik yanıt dener; anlamadığında
 * konuşmayı "ilgi bekliyor" işaretler ve yönetici buradan devralır.
 * Otomatik yanıtlar ayırt edilebilir görünür — hangi bilginin makine
 * tarafından verildiği görünmeli.
 */
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../api";
import { Empty, ErrorBox, Loading, formatDateTime, relativeFromNow } from "../ui";

interface Thread {
  id: string;
  phone: string;
  display_name: string | null;
  guardian_id: string | null;
  guardian_name: string | null;
  needs_attention: boolean;
  unread_count: number;
  last_message_at: string | null;
}

interface Message {
  id: string;
  direction: "in" | "out";
  body: string;
  is_auto: boolean;
  error: string | null;
  created_at: string;
}

export default function Chat() {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const endRef = useRef<HTMLDivElement | null>(null);

  const loadThreads = useCallback(() => {
    api.get<Thread[]>("/wa/threads")
      .then((d) => { setThreads(d); setError(null); })
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadThreads();
    const t = setInterval(loadThreads, 10_000);
    return () => clearInterval(t);
  }, [loadThreads]);

  const loadMessages = useCallback((id: string) => {
    api.get<Message[]>(`/wa/threads/${id}/messages`)
      .then(setMessages)
      .catch(setError);
  }, []);

  useEffect(() => {
    if (!active) return;
    loadMessages(active);
    const t = setInterval(() => loadMessages(active), 5_000);
    return () => clearInterval(t);
  }, [active, loadMessages]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!active || !text.trim()) return;
    setSending(true);
    setError(null);
    try {
      await api.post(`/wa/threads/${active}/reply`, { text: text.trim() });
      setText("");
      loadMessages(active);
      loadThreads();
    } catch (err) {
      setError(err);
      loadMessages(active);   // kaydedildi ama gönderilemedi olabilir
    } finally {
      setSending(false);
    }
  }

  async function resolve() {
    if (!active) return;
    try {
      await api.post(`/wa/threads/${active}/resolve`);
      loadThreads();
    } catch (err) { setError(err); }
  }

  if (loading) return <Loading />;

  const current = threads.find((t) => t.id === active) ?? null;

  return (
    <>
      <div className="page-head">
        <h1>WhatsApp</h1>
        <span className="muted">
          {threads.filter((t) => t.needs_attention).length} konuşma ilgi bekliyor
        </span>
      </div>

      <ErrorBox error={error} />

      <div className="chat-layout">
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          {threads.length === 0 ? (
            <Empty>Henüz mesaj yok.</Empty>
          ) : (
            threads.map((t) => (
              <button
                key={t.id}
                onClick={() => setActive(t.id)}
                className={`thread-item${t.id === active ? " active" : ""}`}
              >
                <div className="row" style={{ gap: ".4rem" }}>
                  <strong>{t.guardian_name ?? t.display_name ?? t.phone}</strong>
                  {t.needs_attention && <span className="badge warn">ilgi</span>}
                  {t.unread_count > 0 && (
                    <span className="badge ok">{t.unread_count}</span>
                  )}
                </div>
                <div className="mono muted" style={{ fontSize: ".78rem" }}>
                  {t.phone}
                  {!t.guardian_id && " · tanınmayan numara"}
                </div>
                <div className="muted" style={{ fontSize: ".75rem" }}>
                  {relativeFromNow(t.last_message_at)}
                </div>
              </button>
            ))
          )}
        </div>

        <div className="card" style={{ display: "flex", flexDirection: "column" }}>
          {!current ? (
            <Empty>Soldan bir konuşma seçin.</Empty>
          ) : (
            <>
              <div className="row" style={{ borderBottom: "1px solid var(--border)", paddingBottom: ".75rem" }}>
                <div>
                  <strong>{current.guardian_name ?? current.display_name ?? current.phone}</strong>
                  <div className="mono muted" style={{ fontSize: ".8rem" }}>
                    {current.phone}
                  </div>
                </div>
                <div className="spacer" />
                {current.needs_attention && (
                  <button className="ghost" onClick={resolve}>İlgilenildi</button>
                )}
              </div>

              {!current.guardian_id && (
                <div className="alert error" style={{ margin: ".75rem 0 0" }}>
                  Bu numara <strong>kayıtlı bir veliye ait değil</strong>. Sistem
                  otomatik bilgi vermedi — öğrenci bilgisi paylaşmadan önce
                  kimliğini doğrulayın.
                </div>
              )}

              <div className="chat-messages">
                {messages.map((m) => (
                  <div key={m.id}
                       className={`bubble ${m.direction === "in" ? "in" : "out"}`}>
                    <div style={{ whiteSpace: "pre-wrap" }}>{m.body}</div>
                    <div className="bubble-meta">
                      {formatDateTime(m.created_at)}
                      {m.is_auto && " · otomatik yanıt"}
                      {m.error && " · GÖNDERİLEMEDİ"}
                    </div>
                  </div>
                ))}
                <div ref={endRef} />
              </div>

              <form onSubmit={send} className="row" style={{ marginTop: ".75rem" }}>
                <input
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder="Yanıt yazın…"
                  aria-label="Yanıt"
                />
                <button type="submit" disabled={sending || !text.trim()}>
                  {sending ? "Gönderiliyor…" : "Gönder"}
                </button>
              </form>
            </>
          )}
        </div>
      </div>
    </>
  );
}
