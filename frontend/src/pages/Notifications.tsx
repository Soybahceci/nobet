/** NÖBET — Veli bildirimleri (Faz 8) */
import { Fragment, useCallback, useEffect, useState } from "react";
import { api, fetchBlob, type Paged } from "../api";
import { ADMIN_ROLES, useAuth } from "../auth";
import { Empty, ErrorBox, Loading, formatDateTime } from "../ui";

interface NotificationRow {
  id: string;
  event_id: number;
  person_name: string | null;
  guardian_name: string | null;
  channel: string;
  recipient: string;
  body: string;
  status: "pending" | "sent" | "failed" | "skipped";
  attempts: number;
  last_error: string | null;
  sent_at: string | null;
  created_at: string;
}

interface ChannelStatus { channel: string; healthy: boolean; detail: string }

const STATUS: Record<string, { text: string; cls: string }> = {
  pending: { text: "Bekliyor", cls: "warn" },
  sent: { text: "Gönderildi", cls: "ok" },
  failed: { text: "Başarısız", cls: "danger" },
  skipped: { text: "Atlandı", cls: "muted" },
};

const SIZE = 30;

/**
 * WhatsApp eşleştirme kutusu.
 * Bağlantı düştüğünde QR doğrudan panelde çıkar — sunucuya SSH gerekmez
 * ("sıfır CLI" kuralı). Yalnızca yöneticiye gösterilir: bu QR'ı okutan kişi
 * KENDİ hesabını bağlar ve kurumun bildirimleri onun hattından gider.
 */
function WhatsAppPairing() {
  const [src, setSrc] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let url: string | null = null;
    let alive = true;

    fetchBlob("/notifications/channel/qr")
      .then((b) => {
        if (!alive) return;
        url = URL.createObjectURL(b);
        setSrc(url);
        setMsg(null);
      })
      .catch((e) => {
        if (!alive) return;
        setSrc(null);
        setMsg(e instanceof Error ? e.message : "QR alınamadı");
      });

    return () => {
      alive = false;
      if (url) URL.revokeObjectURL(url);   // bellek sızıntısını önle
    };
  }, [tick]);

  // WhatsApp QR'ı ~20 saniyede bir yeniler; geçmiş kod okutulamaz
  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), 20_000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="card" style={{ marginBottom: "1rem" }}>
      <h2>WhatsApp bağlantısını kurun</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        Telefonda <strong>WhatsApp → Ayarlar → Bağlı Cihazlar → Cihaz Bağla</strong>,
        sonra aşağıdaki kodu okutun.
      </p>

      <div className="waiting" style={{ background: "#fff" }}>
        {src ? (
          <>
            <img src={src} alt="WhatsApp eşleştirme kodu" width={280} height={280} />
            <p className="muted" style={{ marginBottom: 0 }}>
              Kod 20 saniyede bir yenilenir — süresi dolarsa kendiliğinden
              yenisi gelir.
            </p>
          </>
        ) : (
          <p className="muted" style={{ margin: 0 }}>{msg ?? "Kod alınıyor…"}</p>
        )}
      </div>

      <div className="row" style={{ marginTop: "1rem" }}>
        <button className="ghost" onClick={() => setTick((n) => n + 1)}>
          Kodu yenile
        </button>
      </div>

      <div className="alert error" style={{ marginTop: "1rem", marginBottom: 0 }}>
        Bu kodu <strong>yalnızca kurumun bildirim hattı</strong> okutmalı.
        Okutan hesap sisteme bağlanır ve tüm veli bildirimleri o numaradan gider.
      </div>
    </div>
  );
}

export default function Notifications() {
  const { can } = useAuth();
  const isAdmin = can(...ADMIN_ROLES);

  const [data, setData] = useState<Paged<NotificationRow> | null>(null);
  const [ch, setCh] = useState<ChannelStatus | null>(null);
  const [state, setState] = useState("");
  const [page, setPage] = useState(1);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState<string | null>(null);

  const load = useCallback(() => {
    const params = new URLSearchParams({ page: String(page), size: String(SIZE) });
    if (state) params.set("status", state);
    Promise.all([
      api.get<Paged<NotificationRow>>(`/notifications?${params}`),
      api.get<ChannelStatus>("/notifications/channel").catch(() => null),
    ])
      .then(([d, c]) => { setData(d); setCh(c); setError(null); })
      .catch(setError)
      .finally(() => setLoading(false));
  }, [state, page]);

  useEffect(() => {
    load();
    const t = setInterval(load, 10_000);
    return () => clearInterval(t);
  }, [load]);

  async function retry(id: string) {
    try {
      await api.post(`/notifications/${id}/retry`);
      load();
    } catch (e) { setError(e); }
  }

  if (loading) return <Loading />;

  const totalPages = data ? Math.max(1, Math.ceil(data.total / SIZE)) : 1;
  const dryRun = ch?.channel === "dryrun";

  return (
    <>
      <div className="page-head">
        <h1>Bildirimler</h1>
        <span className="muted">{data?.total ?? 0} kayıt</span>
      </div>

      <ErrorBox error={error} />

      {ch && (
        <div className={`alert ${dryRun ? "info" : ch.healthy ? "ok" : "error"}`}>
          <strong>Kanal: {ch.channel}</strong> — {ch.detail}
          {dryRun && (
            <div style={{ marginTop: ".35rem" }}>
              Mesajlar üretiliyor ve kaydediliyor ama <strong>gönderilmiyor</strong>.
              Gerçek gönderim için kanal ayarı değiştirilmeli.
            </div>
          )}
          {!dryRun && !ch.healthy && (
            <div style={{ marginTop: ".35rem" }}>
              Bildirimler kuyrukta bekliyor. Bağlantı kurulunca kendiliğinden
              gönderilecek — <strong>kayıp yok</strong>.
            </div>
          )}
        </div>
      )}

      {ch && ch.channel === "whatsapp" && !ch.healthy && isAdmin && <WhatsAppPairing />}

      <div className="card">
        <div className="row" style={{ marginBottom: "1rem" }}>
          <select value={state} onChange={(e) => { setPage(1); setState(e.target.value); }}
                  style={{ maxWidth: 200 }} aria-label="Durum">
            <option value="">Tüm durumlar</option>
            <option value="pending">Bekliyor</option>
            <option value="sent">Gönderildi</option>
            <option value="failed">Başarısız</option>
          </select>
        </div>

        {!data || data.items.length === 0 ? (
          <Empty>
            Bildirim yok. 18 yaş altı bir öğrenci giriş-çıkış yaptığında,
            bildirimi açık velilerine mesaj üretilir.
          </Empty>
        ) : (
          <>
            <table>
              <thead>
                <tr>
                  <th>Zaman</th><th>Öğrenci</th><th>Veli</th>
                  <th>Numara</th><th>Durum</th>{isAdmin && <th />}
                </tr>
              </thead>
              <tbody>
                {data.items.map((n) => {
                  const st = STATUS[n.status] ?? { text: n.status, cls: "muted" };
                  return (
                    <Fragment key={n.id}>
                      <tr onClick={() => setOpen(open === n.id ? null : n.id)}
                          style={{ cursor: "pointer" }}>
                        <td>{formatDateTime(n.created_at)}</td>
                        <td><strong>{n.person_name ?? "—"}</strong></td>
                        <td className="muted">{n.guardian_name ?? "—"}</td>
                        <td className="mono">{n.recipient}</td>
                        <td>
                          <span className={`badge ${st.cls}`}>{st.text}</span>
                          {n.attempts > 0 && n.status !== "sent" && (
                            <div className="muted" style={{ fontSize: ".78rem" }}>
                              {n.attempts} deneme
                            </div>
                          )}
                        </td>
                        {isAdmin && (
                          <td className="right">
                            {n.status === "failed" && (
                              <button className="ghost"
                                      onClick={(e) => { e.stopPropagation(); retry(n.id); }}>
                                Tekrar dene
                              </button>
                            )}
                          </td>
                        )}
                      </tr>
                      {open === n.id && (
                        <tr>
                          <td colSpan={isAdmin ? 6 : 5} style={{ background: "#f8fafc" }}>
                            <div style={{ whiteSpace: "pre-wrap", fontSize: ".9rem" }}>
                              {n.body}
                            </div>
                            {n.last_error && (
                              <div className="alert error" style={{ marginTop: ".6rem", marginBottom: 0 }}>
                                Son hata: {n.last_error}
                              </div>
                            )}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>

            {totalPages > 1 && (
              <div className="row" style={{ marginTop: "1rem" }}>
                <button className="ghost" disabled={page <= 1}
                        onClick={() => setPage((n) => n - 1)}>Önceki</button>
                <span className="muted">{page} / {totalPages}</span>
                <button className="ghost" disabled={page >= totalPages}
                        onClick={() => setPage((n) => n + 1)}>Sonraki</button>
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}
