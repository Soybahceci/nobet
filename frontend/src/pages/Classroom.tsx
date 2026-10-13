/**
 * NÖBET — Derslik yoklaması (Faz 10)
 *
 * Sınıf listesi `person.grade` alanından gelir; ayrı şube tablosu yok.
 * "Geldi" sayılma kuralı: öğrencinin bu derslikteki oturumu verilen zaman
 * aralığıyla kesişiyorsa.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ADMIN_ROLES, useAuth } from "../auth";
import { Empty, ErrorBox, Loading, Stat, formatTime } from "../ui";

interface Zone { id: string; name: string; kind: string }

interface Lesson {
  id: string;
  zone_id: string;
  zone_name: string | null;
  grade: string;
  weekday: number;
  starts_at: string;
  ends_at: string;
  name: string;
  is_active: boolean;
}

interface LessonToday extends Lesson {
  starts_at_utc: string;
  ends_at_utc: string;
  is_current: boolean;
}

export const WEEKDAYS = [
  "", "Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar",
];

/** "09:00:00" → "09:00" */
function hhmm(t: string): string {
  return t.slice(0, 5);
}

interface RosterRow {
  person_id: string;
  full_name: string;
  external_ref: string | null;
  present: boolean;
  entered_at: string | null;
  still_inside: boolean;
}

interface Attendance {
  zone_name: string;
  grade: string;
  total: number;
  present: number;
  absent: number;
  rows: RosterRow[];
}

/** datetime-local biçimi (yerel saat) */
function localInput(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

export default function Classroom() {
  const { can } = useAuth();
  const isAdmin = can(...ADMIN_ROLES);
  const [zones, setZones] = useState<Zone[]>([]);
  const [grades, setGrades] = useState<string[]>([]);
  const [zoneId, setZoneId] = useState("");
  const [grade, setGrade] = useState("");
  const [from, setFrom] = useState(() => {
    const d = new Date(); d.setMinutes(d.getMinutes() - 45); return localInput(d);
  });
  const [to, setTo] = useState(() => localInput(new Date()));
  const [live, setLive] = useState(false);
  const [data, setData] = useState<Attendance | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const [todays, setTodays] = useState<LessonToday[]>([]);
  const [lessonId, setLessonId] = useState("");
  const [managing, setManaging] = useState(false);

  /**
   * Bugünün dersleri. Saatler sunucuda kurumun dilimiyle UTC'ye çevrilmiş
   * geliyor — tarayıcının dilimine hiç bakılmıyor.
   */
  const loadToday = useCallback(() => {
    if (!zoneId || !grade) { setTodays([]); return; }
    const p = new URLSearchParams({ zone_id: zoneId, grade });
    api.get<LessonToday[]>(`/lessons/today?${p}`)
      .then((d) => {
        setTodays(d);
        // Süren ders varsa onu seç; operatörün saat yazmasına gerek kalmasın
        const cur = d.find((x) => x.is_current);
        if (cur) applyLesson(cur);
      })
      .catch(() => setTodays([]));
  }, [zoneId, grade]);

  useEffect(loadToday, [loadToday]);

  function applyLesson(l: LessonToday) {
    setLessonId(l.id);
    setFrom(localInput(new Date(l.starts_at_utc)));
    setTo(localInput(new Date(l.ends_at_utc)));
  }

  useEffect(() => {
    Promise.all([
      api.get<Zone[]>("/zones"),
      api.get<string[]>("/reports/grades"),
    ]).then(([z, g]) => {
      const classrooms = z.filter((x) => x.kind === "classroom");
      setZones(classrooms.length ? classrooms : z);
      setGrades(g);
      if (classrooms.length) setZoneId(classrooms[0].id);
      else if (z.length) setZoneId(z[0].id);
      if (g.length) setGrade(g[0]);
    }).catch(setError);
  }, []);

  const load = useCallback(() => {
    if (!zoneId || !grade) return;
    setLoading(true);
    const p = new URLSearchParams({
      zone_id: zoneId, grade,
      from: new Date(from).toISOString(),
      to: new Date(live ? Date.now() : new Date(to).getTime()).toISOString(),
    });
    api.get<Attendance>(`/reports/classroom?${p}`)
      .then((d) => { setData(d); setError(null); })
      .catch((e) => { setError(e); setData(null); })
      .finally(() => setLoading(false));
  }, [zoneId, grade, from, to, live]);

  // Canlı mod: ders sürerken gelenler kendiliğinden görünsün
  useEffect(() => {
    if (!live) return;
    load();
    const t = setInterval(load, 10_000);
    return () => clearInterval(t);
  }, [live, load]);

  return (
    <>
      <div className="page-head">
        <h1>Derslik Yoklaması</h1>
        {data && (
          <span className="muted">
            {data.zone_name} · {data.grade}
          </span>
        )}
      </div>

      <ErrorBox error={error} />

      <div className="card" style={{ marginBottom: "1rem" }}>
        <div className="row" style={{ flexWrap: "wrap", alignItems: "flex-end" }}>
          <div className="field" style={{ margin: 0, minWidth: 170 }}>
            <label htmlFor="cz">Derslik</label>
            <select id="cz" value={zoneId} onChange={(e) => setZoneId(e.target.value)}>
              {zones.map((z) => <option key={z.id} value={z.id}>{z.name}</option>)}
            </select>
          </div>
          <div className="field" style={{ margin: 0, minWidth: 130 }}>
            <label htmlFor="cg">Sınıf</label>
            <select id="cg" value={grade} onChange={(e) => setGrade(e.target.value)}>
              {grades.length === 0 && <option value="">(sınıf yok)</option>}
              {grades.map((g) => <option key={g} value={g}>{g}</option>)}
            </select>
          </div>
          <div className="field" style={{ margin: 0, minWidth: 200 }}>
            <label htmlFor="cl">Ders</label>
            <select id="cl" value={lessonId} onChange={(e) => {
              const l = todays.find((x) => x.id === e.target.value);
              if (l) applyLesson(l); else setLessonId("");
            }}>
              <option value="">Elle saat gir</option>
              {todays.map((l) => (
                <option key={l.id} value={l.id}>
                  {hhmm(l.starts_at)}–{hhmm(l.ends_at)} · {l.name}
                  {l.is_current ? "  (şu an)" : ""}
                </option>
              ))}
            </select>
          </div>
          <div className="field" style={{ margin: 0 }}>
            <label htmlFor="cf">Ders başlangıcı</label>
            <input id="cf" type="datetime-local" value={from}
                   onChange={(e) => setFrom(e.target.value)} />
          </div>
          <div className="field" style={{ margin: 0 }}>
            <label htmlFor="ct">Bitiş</label>
            <input id="ct" type="datetime-local" value={to} disabled={live}
                   onChange={(e) => setTo(e.target.value)} />
          </div>
          <button onClick={load} disabled={!zoneId || !grade || loading}>
            {loading ? "Alınıyor…" : "Yoklama al"}
          </button>
          <label className="row" style={{ gap: ".35rem" }}>
            <input type="checkbox" checked={live} style={{ width: "auto" }}
                   onChange={(e) => setLive(e.target.checked)} />
            Canlı
          </label>
        </div>
        {live && (
          <p className="muted" style={{ marginBottom: 0, fontSize: ".85rem" }}>
            Ders sürerken 10 saniyede bir yenilenir; sonradan gelenler listede belirir.
          </p>
        )}
        {isAdmin && (
          <div className="row" style={{ marginTop: ".5rem" }}>
            <span className="muted" style={{ fontSize: ".85rem" }}>
              {todays.length === 0
                ? "Bugün için tanımlı ders yok — saatleri elle giriyorsunuz."
                : `Bugün ${todays.length} ders tanımlı.`}
            </span>
            <div className="spacer" />
            <button className="ghost" onClick={() => setManaging((v) => !v)}>
              {managing ? "Programı kapat" : "Ders programı"}
            </button>
          </div>
        )}
      </div>

      {isAdmin && managing && (
        <LessonManager zones={zones} grades={grades}
                       zoneId={zoneId} grade={grade}
                       onChanged={loadToday} onError={setError} />
      )}

      {grades.length === 0 && (
        <div className="alert info">
          Hiç sınıf tanımlı değil. Yoklama, kişi kayıtlarındaki <strong>sınıf</strong>{" "}
          alanına göre çalışır — öğrencilere "11-A" gibi bir sınıf girin.
        </div>
      )}

      {data && (
        <>
          <div className="grid cols-4" style={{ marginBottom: "1rem" }}>
            <Stat label="Mevcut" value={data.total} />
            <Stat label="Gelen" value={data.present} />
            <Stat label="Gelmeyen" value={data.absent}
                  sub={data.absent > 0 ? "devamsız" : undefined} />
            <Stat label="Katılım"
                  value={`%${data.total ? Math.round((data.present / data.total) * 100) : 0}`} />
          </div>

          <div className="card">
            {data.rows.length === 0 ? (
              <Empty>Bu sınıfta öğrenci yok.</Empty>
            ) : (
              <table>
                <thead>
                  <tr><th>Öğrenci</th><th>No</th><th>Durum</th><th>Giriş</th></tr>
                </thead>
                <tbody>
                  {data.rows.map((r) => (
                    <tr key={r.person_id}
                        style={!r.present ? { background: "var(--danger-bg)" } : undefined}>
                      <td>
                        <Link to={`/kisiler/${r.person_id}`}>{r.full_name}</Link>
                      </td>
                      <td className="mono muted">{r.external_ref ?? "—"}</td>
                      <td>
                        {r.present
                          ? <span className="badge ok">Geldi</span>
                          : <span className="badge danger">Gelmedi</span>}
                        {r.still_inside && (
                          <span className="badge muted" style={{ marginLeft: ".4rem" }}>
                            içeride
                          </span>
                        )}
                      </td>
                      <td>{r.entered_at ? formatTime(r.entered_at) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </>
  );
}

/**
 * Ders programı yönetimi.
 *
 * Yoklama ekranının içinde duruyor, ayrı bir menü öğesi değil: programı
 * düzenleme ihtiyacı hep yoklama alırken doğuyor ("bu ders neden listede yok").
 */
function LessonManager({
  zones, grades, zoneId, grade, onChanged, onError,
}: {
  zones: Zone[];
  grades: string[];
  zoneId: string;
  grade: string;
  onChanged: () => void;
  onError: (e: unknown) => void;
}) {
  const [rows, setRows] = useState<Lesson[] | null>(null);
  const [z, setZ] = useState(zoneId);
  const [g, setG] = useState(grade);
  const [weekday, setWeekday] = useState(String(new Date().getDay() || 7));
  const [name, setName] = useState("");
  const [starts, setStarts] = useState("09:00");
  const [ends, setEnds] = useState("09:50");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.get<Lesson[]>("/lessons")
      .then(setRows)
      .catch(onError);
  }, [onError]);

  useEffect(load, [load]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post("/lessons", {
        zone_id: z, grade: g, weekday: Number(weekday),
        starts_at: starts, ends_at: ends, name: name.trim(),
      });
      setName("");
      load();
      onChanged();
    } catch (err) { onError(err); } finally { setBusy(false); }
  }

  async function remove(id: string) {
    setBusy(true);
    try {
      await api.del(`/lessons/${id}`);
      load();
      onChanged();
    } catch (err) { onError(err); } finally { setBusy(false); }
  }

  return (
    <div className="card" style={{ marginBottom: "1rem" }}>
      <h2>Ders programı</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        Program tanımlanınca yoklama ekranı ders saatlerini kendisi doldurur ve
        o an süren dersi ön seçili getirir. Aynı derslik, sınıf ve gün için
        saatler çakışamaz — arka arkaya dersler (09:00–09:50, 09:50–10:40)
        çakışma sayılmaz.
      </p>

      <form onSubmit={add} className="row" style={{ flexWrap: "wrap", alignItems: "flex-end" }}>
        <div className="field" style={{ margin: 0, minWidth: 150 }}>
          <label htmlFor="lz">Derslik</label>
          <select id="lz" value={z} onChange={(e) => setZ(e.target.value)}>
            {zones.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
          </select>
        </div>
        <div className="field" style={{ margin: 0, minWidth: 110 }}>
          <label htmlFor="lg">Sınıf</label>
          <select id="lg" value={g} onChange={(e) => setG(e.target.value)}>
            {grades.map((x) => <option key={x} value={x}>{x}</option>)}
          </select>
        </div>
        <div className="field" style={{ margin: 0, minWidth: 130 }}>
          <label htmlFor="lw">Gün</label>
          <select id="lw" value={weekday} onChange={(e) => setWeekday(e.target.value)}>
            {WEEKDAYS.slice(1).map((d, i) => (
              <option key={i + 1} value={i + 1}>{d}</option>
            ))}
          </select>
        </div>
        <div className="field" style={{ margin: 0, maxWidth: 120 }}>
          <label htmlFor="ls">Başlangıç</label>
          <input id="ls" type="time" required value={starts}
                 onChange={(e) => setStarts(e.target.value)} />
        </div>
        <div className="field" style={{ margin: 0, maxWidth: 120 }}>
          <label htmlFor="le">Bitiş</label>
          <input id="le" type="time" required value={ends}
                 onChange={(e) => setEnds(e.target.value)} />
        </div>
        <div className="field" style={{ margin: 0, minWidth: 150 }}>
          <label htmlFor="ln">Ders adı</label>
          <input id="ln" required value={name} placeholder="1. Ders / Matematik"
                 onChange={(e) => setName(e.target.value)} />
        </div>
        <button type="submit" disabled={busy || !z || !g || !name.trim()}>Ekle</button>
      </form>

      {rows === null ? (
        <Loading />
      ) : rows.length === 0 ? (
        <Empty>Hiç ders tanımlanmamış.</Empty>
      ) : (
        <table style={{ marginTop: "1rem" }}>
          <thead>
            <tr><th>Gün</th><th>Saat</th><th>Ders</th><th>Derslik</th><th>Sınıf</th><th /></tr>
          </thead>
          <tbody>
            {rows.map((l) => (
              <tr key={l.id}>
                <td>{WEEKDAYS[l.weekday]}</td>
                <td className="mono">{hhmm(l.starts_at)}–{hhmm(l.ends_at)}</td>
                <td><strong>{l.name}</strong></td>
                <td className="muted">{l.zone_name ?? "—"}</td>
                <td className="muted">{l.grade}</td>
                <td className="right">
                  <button className="ghost" disabled={busy}
                          onClick={() => remove(l.id)}>Sil</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
