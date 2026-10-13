/** NÖBET — Panel (kontrat §3.7) */
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  api, streamEvents, type DashboardSummary, type EventRow, type Paged,
} from "../api";
import { STAFF_ROLES, useAuth } from "../auth";
import { DecisionBadge, ErrorBox, Empty, Loading, Stat, formatTime } from "../ui";

const MAX_ROWS = 20;

interface InsideRow {
  person_id: string;
  full_name: string;
  person_type: string;
  zone_id: string;
  zone_name: string;
  entered_at: string;
  elapsed_seconds: number;
}

function elapsed(secs: number): string {
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  return h > 0 ? `${h} sa ${m} dk` : `${m} dk`;
}

/**
 * Bildirim kanalı bozuksa panelde uyar.
 * RC522'nin sessiz arızasında öğrendiğimiz ders: arıza görünmüyorsa yok
 * sayılır. Veli bildirimi durduğunda kurum bunu haftalar sonra fark etmemeli.
 */
function ChannelWarning() {
  const [ch, setCh] = useState<{ channel: string; healthy: boolean; detail: string } | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api.get<{ channel: string; healthy: boolean; detail: string }>("/notifications/channel")
        .then((d) => alive && setCh(d))
        .catch(() => {});
    load();
    const t = setInterval(load, 30_000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  if (!ch || ch.healthy || ch.channel === "dryrun") return null;

  return (
    <div className="alert error">
      <strong>Veli bildirimleri gönderilemiyor.</strong> {ch.detail}
      {" — "}
      <Link to="/bildirimler">Bildirimler sayfasından bağlantıyı kurun</Link>.
      <div style={{ marginTop: ".35rem" }}>
        Mesajlar kuyrukta bekliyor, bağlantı kurulunca gönderilecek. Kayıp yok.
      </div>
    </div>
  );
}

/** §3.6 — şu an içeride olanlar. Yeni okuma geldikçe tazelenir. */
function InsideNow({ refreshKey }: { refreshKey: number }) {
  const [rows, setRows] = useState<InsideRow[]>([]);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let alive = true;
    api.get<InsideRow[]>("/sessions/open")
      .then((d) => alive && setRows(d))
      .catch((e) => alive && setError(e));
    return () => { alive = false; };
  }, [refreshKey]);

  if (error) return <ErrorBox error={error} />;

  return (
    <div className="card" style={{ marginBottom: "1rem" }}>
      <h2>Şu an içeride</h2>
      {rows.length === 0 ? (
        <Empty>Şu an içeride kimse yok.</Empty>
      ) : (
        <table>
          <thead>
            <tr><th>Kişi</th><th>Mekân</th><th>Giriş</th><th>Süre</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.person_id + r.zone_id}>
                <td><strong>{r.full_name}</strong></td>
                <td className="muted">{r.zone_name}</td>
                <td>{formatTime(r.entered_at)}</td>
                <td>{elapsed(r.elapsed_seconds)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default function Dashboard() {
  /**
   * ⚠️ Bu sayfa HER role açık, ama içindeki verilerin bir kısmı değil.
   * `/events`, `/events/stream` ve `/notifications/channel` uçları
   * `StaffUser` istiyor; koç bunlara 403 alır.
   *
   * Eskiden çağrılar koşulsuz yapılıyordu ve koçta şu tuhaflık oluyordu:
   * ilk yüklemedeki `Promise.all` 403 yüzünden tümden reddediliyor, BAŞARILI
   * olan özet de çöpe gidiyor ve "yetkiniz yok" beliriyordu; sonra arka
   * plandaki periyodik `loadSummary` başarılı olup hatayı temizliyor ve
   * içerik geliyordu. Yani ekran, hangi isteğin önce döndüğüne göre bazen
   * hata bazen içerik gösteriyordu.
   *
   * Çözüm: yetkisi olmayan uca hiç çağrı yapma. Yetki kapısı sunucuda
   * kalır (orası tek doğruluk kaynağı), arayüz yalnızca boşuna kapıyı
   * çalmayı bırakır.
   */
  const { can } = useAuth();
  const isStaff = can(...STAFF_ROLES);

  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [events, setEvents] = useState<EventRow[]>([]);
  const [live, setLive] = useState(false);
  const [flashId, setFlashId] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  const loadSummary = useCallback(async () => {
    try {
      setSummary(await api.get<DashboardSummary>("/dashboard/summary"));
      setError(null);
    } catch (err) {
      setError(err);
    }
  }, []);

  // İlk yükleme. Koç için hiçbir şey istenmez: olay listesi zaten yasak,
  // özet ise kurum geneli sayı döndürüyor (koçun öğrencileriyle sınırlı
  // değil) — üstte "12 içeride" yazarken listede 2 kişi görünmesi
  // yanıltıcı olurdu. Koç kendi verisini InsideNow ve Öğrencilerim'den alır.
  useEffect(() => {
    let alive = true;
    if (!isStaff) { setLoading(false); return; }
    Promise.all([
      api.get<DashboardSummary>("/dashboard/summary"),
      api.get<Paged<EventRow>>(`/events?size=${MAX_ROWS}`),
    ])
      .then(([s, e]) => {
        if (!alive) return;
        setSummary(s);
        setEvents(e.items);
        setError(null);
      })
      .catch((err) => alive && setError(err))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [isStaff]);

  // Canlı akış — olay düştüğü anda listeye girer (§3.6)
  const summaryTimer = useRef<number | null>(null);
  useEffect(() => {
    // Akış ucu da personele özel; koç için hiç açılmaz.
    if (!isStaff) return;
    const stop = streamEvents(
      (e) => {
        setEvents((prev) =>
          prev.some((x) => x.id === e.id) ? prev : [e, ...prev].slice(0, MAX_ROWS),
        );
        setFlashId(e.id);

        // Özet sayaçları da değişti; arka arkaya okutmada API'yi yormamak
        // için kısa bir gecikmeyle tek sefer tazelenir.
        if (summaryTimer.current) window.clearTimeout(summaryTimer.current);
        summaryTimer.current = window.setTimeout(loadSummary, 400);
      },
      setLive,
    );
    return () => {
      stop();
      if (summaryTimer.current) window.clearTimeout(summaryTimer.current);
    };
  }, [loadSummary, isStaff]);

  // Akış kopmuşsa özet en azından bayatlamasın
  useEffect(() => {
    if (live || !isStaff) return;
    const t = window.setInterval(loadSummary, 15_000);
    return () => window.clearInterval(t);
  }, [live, loadSummary, isStaff]);

  if (loading) return <Loading />;

  // --- Koç panosu ---------------------------------------------------------
  // Sayaç kutuları (bugünkü okuma, okuyucu durumu, kayıtsız kart) işletme
  // bilgisi; koçun işi değil. Ona kendi öğrencileri gösterilir.
  if (!isStaff) {
    return (
      <>
        <div className="page-head"><h1>Panel</h1></div>
        <InsideNow refreshKey={0} />
        <div className="card">
          <h2>Öğrencileriniz</h2>
          <p className="muted" style={{ marginBottom: ".75rem" }}>
            Size atanmış öğrencilerin haftalık süreleri, eksik çıkışları ve
            şu an içeride olup olmadıkları ayrı sayfada.
          </p>
          <Link className="btn" to="/ogrencilerim">Öğrencilerim</Link>
        </div>
      </>
    );
  }

  const inside = summary?.inside_now ?? {};
  const insideTotal = Object.values(inside).reduce((a, b) => a + b, 0);
  const nodesOnline = summary?.nodes?.online ?? 0;
  const nodesOffline = summary?.nodes?.offline ?? 0;

  return (
    <>
      <div className="page-head">
        <h1>Panel</h1>
        <span className={`badge ${live ? "ok" : "warn"}`}>
          {live ? "● Canlı" : "○ Bağlantı bekleniyor"}
        </span>
      </div>

      <ErrorBox error={error} />

      <div className="grid cols-4" style={{ marginBottom: "1.5rem" }}>
        <Stat
          label="Şu an içeride"
          value={insideTotal}
          sub={`${inside.student ?? 0} öğrenci · ${inside.staff ?? 0} personel`}
        />
        <Stat label="Bugünkü okuma" value={summary?.today_events ?? 0} />
        <Stat
          label="Okuyucular"
          value={`${nodesOnline}/${nodesOnline + nodesOffline}`}
          sub={nodesOffline ? `${nodesOffline} çevrimdışı` : "hepsi çevrimiçi"}
        />
        <Stat
          label="Kayıtsız kart (24s)"
          value={summary?.unknown_reads_24h ?? 0}
          sub={summary?.unknown_reads_24h ? "kart atama bekliyor" : undefined}
        />
      </div>

      <ChannelWarning />
      <InsideNow refreshKey={events.length} />

      <div className="card">
        <h2>Son okumalar</h2>
        {events.length === 0 ? (
          <Empty>Henüz okuma yok. Bir kart okutun, burada anında belirecek.</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Saat</th>
                <th>Kişi</th>
                <th>Sonuç</th>
                <th>Kaynak</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.id} className={e.id === flashId ? "flash" : undefined}>
                  <td>{formatTime(e.effective_ts)}</td>
                  <td title={`Kart: ${e.cred_identifier}`}>
                    {e.person_name ? (
                      // Kart numarası küçük puntoyla altta: personel kimin
                      // geçtiğini isimden okur, gerektiğinde numaraya da bakar
                      <>
                        <strong>{e.person_name}</strong>
                        <div className="mono muted" style={{ fontSize: ".78rem" }}>
                          {e.cred_identifier}
                        </div>
                      </>
                    ) : (
                      <>
                        <span className="mono">{e.cred_identifier}</span>
                        <div className="muted" style={{ fontSize: ".78rem" }}>
                          tanınmayan kart
                        </div>
                      </>
                    )}
                  </td>
                  <td><DecisionBadge decision={e.decision} /></td>
                  <td className="muted">
                    {e.from_buffer ? "çevrimdışı tampon" : "canlı"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
