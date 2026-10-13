/** NÖBET — Oturumlar (kontrat §3.6, §4.1) */
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, type Paged } from "../api";
import { ADMIN_ROLES, useAuth } from "../auth";
import { Empty, ErrorBox, Loading, formatDateTime } from "../ui";

interface SessionRow {
  id: string;
  person_id: string;
  person_name: string | null;
  zone_id: string;
  zone_name: string | null;
  entered_at: string;
  exited_at: string | null;
  duration_seconds: number | null;
  state: "open" | "closed" | "auto_closed" | "corrected";
  note: string | null;
}

const STATE: Record<string, { text: string; cls: string }> = {
  open: { text: "İçeride", cls: "ok" },
  closed: { text: "Tamamlandı", cls: "muted" },
  auto_closed: { text: "Eksik çıkış", cls: "warn" },
  corrected: { text: "Düzeltildi", cls: "ok" },
};

/** Süreyi insan okusun diye: 2 sa 14 dk */
function humanDuration(secs: number | null): string {
  if (secs === null) return "—";
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  if (h === 0 && m === 0) return `${secs} sn`;
  return h > 0 ? `${h} sa ${m} dk` : `${m} dk`;
}

const SIZE = 30;

export default function Sessions() {
  const { can } = useAuth();
  const isAdmin = can(...ADMIN_ROLES);

  const [data, setData] = useState<Paged<SessionRow> | null>(null);
  const [state, setState] = useState("");
  const [page, setPage] = useState(1);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<SessionRow | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    const params = new URLSearchParams({ page: String(page), size: String(SIZE) });
    if (state) params.set("state", state);
    api.get<Paged<SessionRow>>(`/sessions?${params}`)
      .then((d) => { setData(d); setError(null); })
      .catch(setError)
      .finally(() => setLoading(false));
  }, [state, page]);

  useEffect(load, [load]);

  const totalPages = data ? Math.max(1, Math.ceil(data.total / SIZE)) : 1;

  return (
    <>
      <div className="page-head">
        <h1>Oturumlar</h1>
        <span className="muted">{data?.total ?? 0} kayıt</span>
      </div>

      <ErrorBox error={error} />

      {editing && isAdmin && (
        <CorrectSession
          session={editing}
          onDone={() => { setEditing(null); load(); }}
          onCancel={() => setEditing(null)}
        />
      )}

      <div className="card">
        <div className="row" style={{ marginBottom: "1rem" }}>
          <select
            value={state}
            onChange={(e) => { setPage(1); setState(e.target.value); }}
            style={{ maxWidth: 200 }}
            aria-label="Durum"
          >
            <option value="">Tüm durumlar</option>
            <option value="open">İçeride</option>
            <option value="closed">Tamamlandı</option>
            <option value="auto_closed">Eksik çıkış</option>
            <option value="corrected">Düzeltildi</option>
          </select>
        </div>

        {loading ? (
          <Loading />
        ) : !data || data.items.length === 0 ? (
          <Empty>Kayıt yok. Bir kart okutulunca oturum açılır.</Empty>
        ) : (
          <>
            <table>
              <thead>
                <tr>
                  <th>Kişi</th>
                  <th>Mekân</th>
                  <th>Giriş</th>
                  <th>Çıkış</th>
                  <th>Süre</th>
                  <th>Durum</th>
                  {isAdmin && <th />}
                </tr>
              </thead>
              <tbody>
                {data.items.map((s) => {
                  const st = STATE[s.state] ?? { text: s.state, cls: "muted" };
                  return (
                    <tr key={s.id}>
                      <td><strong>{s.person_name ?? "—"}</strong></td>
                      <td className="muted">{s.zone_name ?? "—"}</td>
                      <td>{formatDateTime(s.entered_at)}</td>
                      <td>{s.exited_at ? formatDateTime(s.exited_at) : "—"}</td>
                      <td>{humanDuration(s.duration_seconds)}</td>
                      <td>
                        <span className={`badge ${st.cls}`}>{st.text}</span>
                        {s.state === "auto_closed" && (
                          <div className="muted" style={{ fontSize: ".78rem" }}>
                            süreye sayılmadı
                          </div>
                        )}
                      </td>
                      {isAdmin && (
                        <td className="right">
                          {s.state !== "open" && (
                            <button className="ghost" onClick={() => setEditing(s)}>
                              Düzelt
                            </button>
                          )}
                        </td>
                      )}
                    </tr>
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

function CorrectSession({
  session, onDone, onCancel,
}: { session: SessionRow; onDone: () => void; onCancel: () => void }) {
  // datetime-local yerel saat bekler; ISO'dan dönüştür
  const initial = session.exited_at
    ? new Date(session.exited_at)
    : new Date(session.entered_at);
  const pad = (n: number) => String(n).padStart(2, "0");
  const asLocal = (d: Date) =>
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;

  const [exitedAt, setExitedAt] = useState(asLocal(initial));
  const [note, setNote] = useState(session.note ?? "");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.patch(`/sessions/${session.id}`, {
        exited_at: new Date(exitedAt).toISOString(),
        note: note.trim() || null,
      });
      onDone();
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <div className="card" style={{ marginBottom: "1rem" }}>
      <h2>Çıkış saatini düzelt</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        <strong>{session.person_name}</strong> · giriş{" "}
        {formatDateTime(session.entered_at)}
      </p>
      <div className="alert info">
        Düzeltme yalnızca oturumu değiştirir. <strong>Ham kart okuma kayıtları
        korunur</strong> — denetim izi bozulmaz, kimin düzelttiği saklanır.
      </div>

      <ErrorBox error={error} />

      <form onSubmit={submit}>
        <div className="grid cols-2">
          <div className="field">
            <label htmlFor="ex">Çıkış saati</label>
            <input id="ex" type="datetime-local" required value={exitedAt}
                   onChange={(e) => setExitedAt(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="nt">Not</label>
            <input id="nt" value={note} onChange={(e) => setNote(e.target.value)}
                   placeholder="Örn. çıkış okutmayı unutmuş" />
          </div>
        </div>
        <div className="row">
          <button type="submit" disabled={busy}>
            {busy ? "Kaydediliyor…" : "Kaydet"}
          </button>
          <button type="button" className="ghost" onClick={onCancel} disabled={busy}>
            Vazgeç
          </button>
        </div>
      </form>
    </div>
  );
}
