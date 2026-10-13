/**
 * NÖBET — Kart Atama (kontrat §3.4)
 * ==================================
 * "Sıfır CLI" kuralının merkezi. Operatör teknik bilgi olmadan kart kaydeder:
 *
 *   1. Öğrenciyi seç
 *   2. "Kartı okutun" ekranı — sistem kayıtsız okumaları yoklar
 *   3. Kart okutulunca UID ekranda belirir
 *   4. Onayla -> credential oluşur
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Paged, type PendingRead, type Person } from "../api";
import { ErrorBox, Empty, PERSON_TYPE_LABEL, relativeFromNow } from "../ui";

type Step = "person" | "waiting" | "confirm" | "done";

const POLL_MS = 1500;
const WINDOW_S = 120;

export default function Enroll() {
  const [step, setStep] = useState<Step>("person");
  const [person, setPerson] = useState<Person | null>(null);
  const [read, setRead] = useState<PendingRead | null>(null);
  const [label, setLabel] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const reset = useCallback(() => {
    setStep("person");
    setPerson(null);
    setRead(null);
    setLabel("");
    setError(null);
  }, []);

  async function confirm() {
    if (!person || !read) return;
    setBusy(true);
    setError(null);
    try {
      await api.post("/enroll/claim", {
        event_id: read.event_id,
        person_id: person.id,
        label: label.trim() || null,
      });
      setStep("done");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <h1>Kart Ata</h1>
        {step !== "person" && (
          <button className="ghost" onClick={reset}>Baştan başla</button>
        )}
      </div>

      <ErrorBox error={error} />

      {step === "person" && (
        <PersonPicker
          onPick={(p) => { setPerson(p); setStep("waiting"); }}
        />
      )}

      {step === "waiting" && person && (
        <WaitForCard
          person={person}
          onRead={(r) => { setRead(r); setStep("confirm"); }}
          onError={setError}
        />
      )}

      {step === "confirm" && person && read && (
        <div className="card">
          <h2>Kartı onaylayın</h2>
          <p className="muted" style={{ marginTop: 0 }}>
            <strong>{read.node_name}</strong> okuyucusunda,{" "}
            {relativeFromNow(read.seen_at)} okundu.
          </p>

          <div className="waiting" style={{ borderStyle: "solid", background: "#fff" }}>
            <div className="uid-big">{read.cred_identifier}</div>
            <p className="muted" style={{ marginBottom: 0 }}>
              Bu kart <strong>{person.full_name}</strong> kişisine atanacak.
            </p>
          </div>

          <div className="field" style={{ marginTop: "1rem", maxWidth: 340 }}>
            <label htmlFor="lbl">Etiket (isteğe bağlı)</label>
            <input
              id="lbl"
              placeholder="Örn. Mavi kart"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
            />
          </div>

          <div className="row">
            <button onClick={confirm} disabled={busy}>
              {busy ? "Kaydediliyor…" : "Onayla ve kaydet"}
            </button>
            <button className="ghost" onClick={() => { setRead(null); setStep("waiting"); }}
                    disabled={busy}>
              Başka kart okut
            </button>
          </div>
        </div>
      )}

      {step === "done" && person && read && (
        <div className="card">
          <div className="alert ok">
            <strong>{read.cred_identifier}</strong> kartı{" "}
            <strong>{person.full_name}</strong> kişisine atandı.
          </div>
          <p className="muted">
            Kart artık okutulduğunda tanınacak. Denemek için okuyucuya okutun.
          </p>
          <button onClick={reset}>Yeni kart ata</button>
        </div>
      )}
    </>
  );
}

/** Adım 1 — kişi seçimi */
function PersonPicker({ onPick }: { onPick: (p: Person) => void }) {
  const [q, setQ] = useState("");
  const [items, setItems] = useState<Person[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);

    // Yazarken hemen sorgu atma; kullanıcı durakladığında ara
    const t = setTimeout(() => {
      const params = new URLSearchParams({ size: "20", status: "active" });
      if (q.trim()) params.set("q", q.trim());

      api.get<Paged<Person>>(`/persons?${params}`)
        .then((d) => { if (alive) { setItems(d.items); setError(null); } })
        .catch((e) => alive && setError(e))
        .finally(() => alive && setLoading(false));
    }, 250);

    return () => { alive = false; clearTimeout(t); };
  }, [q]);

  return (
    <div className="card">
      <h2>1. Kişiyi seçin</h2>
      <div className="field" style={{ maxWidth: 380 }}>
        <input
          autoFocus
          placeholder="İsim veya öğrenci no ara…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label="Kişi ara"
        />
      </div>

      <ErrorBox error={error} />

      {loading ? (
        <p className="muted">Aranıyor…</p>
      ) : items.length === 0 ? (
        <Empty>Kişi bulunamadı. Önce Kişiler sayfasından ekleyin.</Empty>
      ) : (
        <table>
          <tbody>
            {items.map((p) => (
              <tr key={p.id}>
                <td>
                  <strong>{p.full_name}</strong>
                  {p.is_minor && (
                    <span className="badge warn" style={{ marginLeft: ".5rem" }}>
                      18 yaş altı
                    </span>
                  )}
                </td>
                <td className="muted">{PERSON_TYPE_LABEL[p.person_type]}</td>
                <td className="mono muted">{p.external_ref ?? ""}</td>
                <td className="right">
                  <button className="ghost" onClick={() => onPick(p)}>Seç</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/** Adım 2 — kart okutulmasını bekle */
function WaitForCard({
  person, onRead, onError,
}: {
  person: Person;
  onRead: (r: PendingRead) => void;
  onError: (e: unknown) => void;
}) {
  const [seconds, setSeconds] = useState(0);
  // Ekran açıldıktan SONRA okunan kartı almak için başlangıç anını sabitliyoruz.
  // Aksi halde saatler önceki kayıtsız okumalar da eşleşirdi.
  const startedAt = useRef(Date.now());

  useEffect(() => {
    let alive = true;

    async function poll() {
      try {
        const rows = await api.get<PendingRead[]>(
          `/enroll/pending?window=${WINDOW_S}`,
        );
        if (!alive) return;

        const fresh = rows
          .filter((r) => new Date(r.seen_at).getTime() >= startedAt.current)
          .sort((a, b) => +new Date(b.seen_at) - +new Date(a.seen_at))[0];

        if (fresh) onRead(fresh);
      } catch (e) {
        if (alive) onError(e);
      }
    }

    const pollTimer = setInterval(poll, POLL_MS);
    const tick = setInterval(() => setSeconds((s) => s + 1), 1000);
    poll();

    return () => { alive = false; clearInterval(pollTimer); clearInterval(tick); };
  }, [onRead, onError]);

  return (
    <div className="card">
      <h2>2. Kartı okutun</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        <strong>{person.full_name}</strong> için kart bekleniyor.
      </p>

      <div className="waiting">
        <div className="pulse" />
        <h2 style={{ margin: 0 }}>Kartı okuyucuya okutun</h2>
        <p className="muted">
          Kart okunduğunda numarası burada belirecek. ({seconds} sn)
        </p>
      </div>

      <div className="alert info" style={{ marginTop: "1rem", marginBottom: 0 }}>
        Zaten kayıtlı bir kart okutursanız burada görünmez — sistem onu
        tanıdığı için kayıtsız okuma listesine düşmez.
      </div>
    </div>
  );
}
