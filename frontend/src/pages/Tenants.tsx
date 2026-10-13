/**
 * NÖBET — İşletmeci Konsolu (Faz 13b)
 *
 * Kurumlar, abonelik kademeleri, kota. Yalnızca `super_admin`.
 *
 * ⭐ Ekranın taşıması gereken en önemli mesaj mimari §5.1: **kademe
 * düşürmek veriyi durdurmaz.** İşletmeci "askıya al" derken ne olduğunu
 * tam olarak bilmeli — yoksa bir kurumun kaydını sildiğini sanıp
 * kullanmaktan çekinir ya da tersine, kaydın da durduğunu sanıp yanlış
 * söz verir. Bu yüzden her kademenin ne yaptığı ekranda yazılı.
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { ErrorBox, Empty, Loading, formatDateTime } from "../ui";

interface TenantRow {
  id: string;
  slug: string;
  name: string;
  timezone: string;
  created_at: string;
  status: string;
  period_start: string | null;
  period_end: string | null;
  sms_quota: number;
  sms_used: number;
  suspended_at: string | null;
  note: string | null;
  person_count: number;
  user_count: number;
  edge_count: number;
}

interface Created {
  tenant: TenantRow;
  admin_email: string;
  invite_sent: boolean | null;
  invite_error: string | null;
}

const KADEMELER = [
  { key: "active", ad: "Etkin", renk: "ok",
    ne: "Her şey açık." },
  { key: "warning", ad: "Ödeme gecikti", renk: "warn",
    ne: "Her şey açık, panelde uyarı bandrolü görünür." },
  { key: "restricted", ad: "Kısıtlı", renk: "warn",
    ne: "Panel salt okunur. Veli erişimi ve SMS kapalı. Kayıt tutulmaya devam eder." },
  { key: "suspended", ad: "Askıda", renk: "danger",
    ne: "Panel kapalı. Kenar cihazı kayıt tutmayı SÜRDÜRÜR; ödeme gelince kuyruk aktarılır." },
] as const;

function kademeBilgi(key: string) {
  return KADEMELER.find((k) => k.key === key) ?? KADEMELER[0];
}

export default function Tenants() {
  const [rows, setRows] = useState<TenantRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [acilan, setAcilan] = useState<Created | null>(null);
  const [formAcik, setFormAcik] = useState(false);
  const [f, setF] = useState({ slug: "", name: "", admin_email: "", admin_password: "" });

  const load = useCallback(async () => {
    try {
      setRows(await api.get<TenantRow[]>("/admin/tenants"));
      setError(null);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function kademeDegistir(t: TenantRow, status: string) {
    if (status === t.status) return;
    const bilgi = kademeBilgi(status);
    if (!window.confirm(
      `${t.name} → ${bilgi.ad}\n\n${bilgi.ne}\n\n` +
      "Kurumun kayıtları hiçbir kademede silinmez.",
    )) return;
    setBusy(t.id);
    try {
      await api.patch(`/admin/tenants/${t.id}/subscription`, { status });
      await load();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  }

  async function kotaDegistir(t: TenantRow) {
    const v = window.prompt(
      `${t.name} için aylık SMS kotası (0 = sınırsız):`, String(t.sms_quota),
    );
    if (v === null) return;
    const n = Number(v);
    if (!Number.isInteger(n) || n < 0) { setError(new Error("Kota tam sayı olmalı.")); return; }
    setBusy(t.id);
    try {
      await api.patch(`/admin/tenants/${t.id}/subscription`,
                      { sms_quota: n, reset_sms_used: true });
      await load();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  }

  async function kurumAc(e: React.FormEvent) {
    e.preventDefault();
    setBusy("yeni");
    setError(null);
    try {
      const r = await api.post<Created>("/admin/tenants", {
        slug: f.slug.trim().toLowerCase(),
        name: f.name.trim(),
        admin_email: f.admin_email.trim(),
        // Boş bırakılırsa davet e-postası gider ve parolayı kullanıcı belirler.
        admin_password: f.admin_password.trim() || null,
      });
      setAcilan(r);
      setFormAcik(false);
      setF({ slug: "", name: "", admin_email: "", admin_password: "" });
      await load();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(null);
    }
  }

  if (loading) return <Loading />;

  return (
    <>
      <div className="page-head">
        <h1>Kurumlar</h1>
        <button onClick={() => setFormAcik((v) => !v)}>
          {formAcik ? "Vazgeç" : "Yeni kurum"}
        </button>
      </div>

      <ErrorBox error={error} />

      {acilan && (
        <div className="alert ok">
          <strong>{acilan.tenant.name}</strong> açıldı.
          Yönetici: <strong>{acilan.admin_email}</strong>
          {acilan.invite_sent === true && " — davet e-postası gönderildi."}
          {acilan.invite_error && (
            <div style={{ marginTop: ".4rem" }}>{acilan.invite_error}</div>
          )}
        </div>
      )}

      {formAcik && (
        <div className="card" style={{ marginBottom: "1rem" }}>
          <h2>Yeni kurum</h2>
          <form onSubmit={kurumAc}>
            <div className="field">
              <label htmlFor="ad">Kurum adı</label>
              <input id="ad" required value={f.name}
                     onChange={(e) => setF({ ...f, name: e.target.value })} />
            </div>
            <div className="field">
              <label htmlFor="kod">Kurum kodu</label>
              <input id="kod" required placeholder="ornek-dershane" value={f.slug}
                     onChange={(e) => setF({ ...f, slug: e.target.value })} />
              <div className="muted" style={{ fontSize: ".88rem", marginTop: ".3rem" }}>
                Küçük harf, rakam ve tire. Sonradan değiştirilemez.
              </div>
            </div>
            <div className="field">
              <label htmlFor="eposta">İlk yöneticinin e-postası</label>
              <input id="eposta" type="email" required value={f.admin_email}
                     onChange={(e) => setF({ ...f, admin_email: e.target.value })} />
              <div className="muted" style={{ fontSize: ".88rem", marginTop: ".3rem" }}>
                Kurum bu hesapla açılır. Yöneticisi olmayan kuruma kimse giremez.
              </div>
            </div>
            <div className="field">
              <label htmlFor="parola">Parola <span className="muted">(boş bırakılırsa davet gönderilir)</span></label>
              <input id="parola" type="password" autoComplete="new-password"
                     value={f.admin_password}
                     onChange={(e) => setF({ ...f, admin_password: e.target.value })} />
              <div className="muted" style={{ fontSize: ".88rem", marginTop: ".3rem" }}>
                Davet için SMTP ayarlı olmalı; değilse parolayı buradan verin.
              </div>
            </div>
            <button type="submit" disabled={busy === "yeni"}>
              {busy === "yeni" ? "Açılıyor…" : "Kurumu aç"}
            </button>
          </form>
        </div>
      )}

      {rows.length === 0 ? (
        <Empty>Henüz kurum yok.</Empty>
      ) : (
        rows.map((t) => {
          const bilgi = kademeBilgi(t.status);
          const kotaAsildi = t.sms_quota > 0 && t.sms_used >= t.sms_quota;
          return (
            <div className="card" key={t.id} style={{ marginBottom: "1rem" }}>
              <div className="page-head" style={{ marginBottom: ".5rem" }}>
                <h2 style={{ margin: 0 }}>
                  {t.name} <span className="muted" style={{ fontWeight: 400 }}>· {t.slug}</span>
                </h2>
                <span className={`badge ${bilgi.renk}`}>{bilgi.ad}</span>
              </div>

              <div className="muted" style={{ marginBottom: ".6rem" }}>
                {t.person_count} kişi · {t.user_count} kullanıcı · {t.edge_count} kenar cihazı
                {t.suspended_at && ` · ${formatDateTime(t.suspended_at)} tarihinden beri askıda`}
              </div>

              <table>
                <tbody>
                  <tr>
                    <td style={{ width: "12rem" }}>Kademe</td>
                    <td>
                      <select
                        value={t.status}
                        disabled={busy === t.id}
                        onChange={(e) => void kademeDegistir(t, e.target.value)}
                      >
                        {KADEMELER.map((k) => (
                          <option key={k.key} value={k.key}>{k.ad}</option>
                        ))}
                      </select>
                      <div className="muted" style={{ fontSize: ".88rem", marginTop: ".3rem" }}>
                        {bilgi.ne}
                      </div>
                    </td>
                  </tr>
                  <tr>
                    <td>SMS kotası</td>
                    <td>
                      {t.sms_quota === 0
                        ? <span className="muted">sınırsız</span>
                        : <span style={kotaAsildi ? { color: "var(--danger)", fontWeight: 600 } : undefined}>
                            {t.sms_used} / {t.sms_quota}
                            {kotaAsildi && " — DOLDU, bildirim durdu"}
                          </span>}
                      {" "}
                      <button className="ghost" disabled={busy === t.id}
                              onClick={() => void kotaDegistir(t)}
                              style={{ padding: ".25rem .6rem", marginLeft: ".5rem" }}>
                        Değiştir
                      </button>
                    </td>
                  </tr>
                  {t.note && (
                    <tr><td>Not</td><td className="muted">{t.note}</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          );
        })
      )}

      <div className="card">
        <h2>Kademeler ne yapar</h2>
        <table>
          <thead>
            <tr><th>Kademe</th><th>Panel</th><th>SMS</th><th>Kenar cihazı</th></tr>
          </thead>
          <tbody>
            <tr><td>Etkin</td><td>açık</td><td>açık</td><td>çalışır</td></tr>
            <tr><td>Ödeme gecikti</td><td>açık + bandrol</td><td>açık</td><td>çalışır</td></tr>
            <tr><td>Kısıtlı</td><td><strong>salt okunur</strong></td><td>kapalı</td><td>çalışır</td></tr>
            <tr><td>Askıda</td><td>kapalı</td><td>kapalı</td><td><strong>kayıt tutmaya devam eder</strong></td></tr>
          </tbody>
        </table>
        <div className="muted" style={{ marginTop: ".6rem" }}>
          <strong>Hiçbir kademede kurumun kaydı durdurulmaz veya silinmez.</strong>{" "}
          Devam kayıtları hukuken kuruma aittir; kesilen şey hizmettir, veri değil.
          Askıdaki kurumda okuyucular çalışmaya devam eder, olaylar kenar
          cihazında birikir ve ödeme gelince aktarılır.
        </div>
      </div>
    </>
  );
}
