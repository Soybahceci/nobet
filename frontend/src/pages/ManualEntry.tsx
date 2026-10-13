/**
 * NÖBET — Elle Giriş/Çıkış (Faz 13a-5)
 * =====================================
 * Kapıdaki görevli için. Öğrenci kartını unutur, kart bozulur ya da okuyucu
 * arıza yaparsa kayıt yine tutulabilsin diye.
 *
 * Tasarım kapıya göre yapıldı, masaya göre değil:
 *
 *   · **Mekân hatırlanır** (localStorage). Kapıdaki kişi her seferinde aynı
 *     kapıyı seçmek zorunda kalmasın.
 *   · **Tek tıklama.** Kişiye basmak işlemi yapar; ayrıca "kaydet" yok.
 *   · **Yön sorulmaz.** Okuyucularla aynı toggle mantığı — açık oturum varsa
 *     çıkış, yoksa giriş. Görevlinin düşünmesi gereken bir şey azalır.
 *   · **Büyük geri bildirim.** Sıra bekleyen öğrenci varken küçük yazı
 *     okunmaz; sonuç bir bant hâlinde görünür ve kendiliğinden kaybolur.
 *   · **İçeride kim var** hep ekranda. Görevli yaptığı işin etkisini görür.
 *
 * ⚠️ Bu ekran `event` üretmez. Kart okunmadı; ham olay akışı insan eliyle
 * kirletilmez (kontrat §0, v2.0). Kayıt türetilmiş oturum katmanında durur
 * ve kimin açtığı `created_by` ile saklanır.
 */
import { useCallback, useEffect, useState } from "react";
import { api, type Paged, type Person } from "../api";
import { Empty, ErrorBox, formatTime, PERSON_TYPE_LABEL } from "../ui";

interface Zone { id: string; name: string; kind: string }

interface InsideRow {
  person_id: string;
  full_name: string;
  zone_id: string;
  zone_name: string;
  entered_at: string;
  elapsed_seconds: number;
}

interface ManualResult {
  id: string;
  person_name: string | null;
  direction: string;
  entered_at: string;
  exited_at: string | null;
}

const ZONE_KEY = "nobet.manual.zone";
const BANNER_MS = 6000;

function elapsed(secs: number): string {
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  return h > 0 ? `${h} sa ${m} dk` : `${m} dk`;
}

export default function ManualEntry() {
  const [zones, setZones] = useState<Zone[]>([]);
  const [zoneId, setZoneId] = useState<string>(() => localStorage.getItem(ZONE_KEY) ?? "");
  const [q, setQ] = useState("");
  const [people, setPeople] = useState<Person[]>([]);
  const [inside, setInside] = useState<InsideRow[]>([]);
  const [note, setNote] = useState("");
  const [result, setResult] = useState<ManualResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  // --- mekânlar ---
  useEffect(() => {
    let alive = true;
    api.get<Zone[]>("/zones")
      .then((d) => {
        if (!alive) return;
        setZones(d);
        // Kayıtlı mekân silinmişse ilkine düş
        setZoneId((cur) => (cur && d.some((z) => z.id === cur) ? cur : d[0]?.id ?? ""));
      })
      .catch((e) => alive && setError(e));
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (zoneId) localStorage.setItem(ZONE_KEY, zoneId);
  }, [zoneId]);

  // --- içeride kim var ---
  const loadInside = useCallback(async () => {
    try {
      setInside(await api.get<InsideRow[]>("/sessions/open"));
    } catch (e) {
      setError(e);
    }
  }, []);

  useEffect(() => { void loadInside(); }, [loadInside]);

  // --- kişi arama ---
  useEffect(() => {
    let alive = true;
    const t = setTimeout(() => {
      const params = new URLSearchParams({ size: "15", status: "active" });
      if (q.trim()) params.set("q", q.trim());
      api.get<Paged<Person>>(`/persons?${params}`)
        .then((d) => alive && setPeople(d.items))
        .catch((e) => alive && setError(e));
    }, 250);
    return () => { alive = false; clearTimeout(t); };
  }, [q]);

  // Sonuç bandı kendiliğinden kaybolsun — görevli kapatmakla uğraşmasın
  useEffect(() => {
    if (!result) return;
    const t = setTimeout(() => setResult(null), BANNER_MS);
    return () => clearTimeout(t);
  }, [result]);

  const insideHere = inside.filter((r) => r.zone_id === zoneId);
  const insideIds = new Set(insideHere.map((r) => r.person_id));

  async function toggle(p: Person) {
    if (!zoneId) { setError(new Error("Önce mekân seçin.")); return; }
    setBusyId(p.id);
    setError(null);
    try {
      const r = await api.post<ManualResult>("/sessions/manual", {
        person_id: p.id,
        zone_id: zoneId,
        note: note.trim() || null,
      });
      setResult(r);
      setNote("");
      setQ("");           // sıradaki kişi için kutu temiz
      await loadInside();
    } catch (e) {
      setError(e);
    } finally {
      setBusyId(null);
    }
  }

  const zoneName = zones.find((z) => z.id === zoneId)?.name ?? "";

  return (
    <>
      <div className="page-head">
        <h1>Elle Giriş / Çıkış</h1>
        <span className="muted">Kart okunamadığında kullanın</span>
      </div>

      {result && (
        <div className={`alert ${result.direction === "GİRİŞ" ? "ok" : "info"}`}
             style={{ fontSize: "1.15rem" }}>
          <strong>{result.person_name}</strong> — {result.direction} kaydedildi
          {" · "}
          {formatTime(result.direction === "GİRİŞ" ? result.entered_at : result.exited_at)}
        </div>
      )}

      <ErrorBox error={error} />

      <div className="card" style={{ marginBottom: "1rem" }}>
        <div className="field" style={{ maxWidth: 340 }}>
          <label htmlFor="zone">Mekân</label>
          <select id="zone" value={zoneId} onChange={(e) => setZoneId(e.target.value)}>
            {zones.length === 0 && <option value="">— mekân tanımlı değil —</option>}
            {zones.map((z) => (
              <option key={z.id} value={z.id}>{z.name}</option>
            ))}
          </select>
        </div>
        <div className="field" style={{ maxWidth: 420 }}>
          <label htmlFor="note">Not <span className="muted">(isteğe bağlı)</span></label>
          <input
            id="note"
            placeholder="ör. kartını evde unuttu"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            maxLength={500}
          />
        </div>
      </div>

      <div className="card" style={{ marginBottom: "1rem" }}>
        <h2>Kişi seçin</h2>
        <div className="field" style={{ maxWidth: 380 }}>
          <input
            autoFocus
            placeholder="İsim veya öğrenci no ara…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            aria-label="Kişi ara"
          />
        </div>

        {people.length === 0 ? (
          <Empty>Kişi bulunamadı.</Empty>
        ) : (
          <table>
            <tbody>
              {people.map((p) => {
                const within = insideIds.has(p.id);
                return (
                  <tr key={p.id}>
                    <td>
                      <strong>{p.full_name}</strong>
                      <div className="muted" style={{ fontSize: ".85rem" }}>
                        {PERSON_TYPE_LABEL[p.person_type] ?? p.person_type}
                        {p.grade ? ` · ${p.grade}` : ""}
                        {p.external_ref ? ` · ${p.external_ref}` : ""}
                      </div>
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {/* Ne olacağını ÖNCEDEN yaz — görevli yanlışlıkla
                          çıkış vermesin diye. */}
                      <button
                        className={within ? "ghost" : ""}
                        disabled={busyId === p.id || !zoneId}
                        onClick={() => toggle(p)}
                      >
                        {busyId === p.id
                          ? "…"
                          : within ? "ÇIKIŞ ver" : "GİRİŞ ver"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h2>{zoneName ? `${zoneName} — şu an içeride` : "Şu an içeride"}</h2>
        {insideHere.length === 0 ? (
          <Empty>Bu mekânda kimse yok.</Empty>
        ) : (
          <table>
            <thead>
              <tr><th>Kişi</th><th>Giriş</th><th>Süre</th></tr>
            </thead>
            <tbody>
              {insideHere.map((r) => (
                <tr key={r.person_id}>
                  <td><strong>{r.full_name}</strong></td>
                  <td>{formatTime(r.entered_at)}</td>
                  <td>{elapsed(r.elapsed_seconds)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="muted" style={{ marginTop: ".75rem", fontSize: ".85rem" }}>
          Elle açılan kayıtlar raporlarda ve yoklamada görünür, ham okuma
          listesinde görünmez — kart okunmadığı için.
        </p>
      </div>
    </>
  );
}
