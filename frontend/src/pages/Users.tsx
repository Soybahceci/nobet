/**
 * NÖBET — Kullanıcı hesapları (kontrat §3.1, §1.3)
 *
 * "Sıfır CLI" kuralının karşılığı: kurum yeni personel işe aldığında hesabı
 * buradan açar. Bu sayfa gelmeden önce hesap açmanın tek yolu terminaldi.
 */
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, type AppUserRow, type Paged, type Person, type Role } from "../api";
import { ROLE_LABEL, useAuth } from "../auth";
import { Empty, ErrorBox, Loading, formatDateTime, relativeFromNow } from "../ui";

const MIN_PW = 12;

/** Koç rolü kişi bağı olmadan işe yaramaz — §1.3 görünürlük buna dayanıyor. */
const ROLE_NEEDS_PERSON: Record<string, boolean> = { coach: true };

const ROLE_HINT: Record<Role, string> = {
  super_admin: "Tüm kurumlar üzerinde tam yetki. Yalnızca sistem sorumlusu.",
  kurum_admin: "Kurum içinde tam yetki: ayarlar, donanım, kullanıcılar.",
  operator: "Günlük işler: kişi kaydı, kart atama, yoklama. Ayarlara giremez.",
  coach: "Yalnızca kendisine atanmış öğrencileri görür. Kişi bağı zorunlu.",
};

function RoleBadge({ role }: { role: Role }) {
  const cls = role === "coach" ? "muted" : role === "operator" ? "ok" : "warn";
  return <span className={`badge ${cls}`}>{ROLE_LABEL[role]}</span>;
}

/** Hesap açma / düzenleme formu. `edit` verilirse düzenleme kipinde çalışır. */
function UserForm({
  edit, people, onDone, onCancel, onError,
}: {
  edit?: AppUserRow;
  people: Person[];
  onDone: () => void;
  onCancel: () => void;
  onError: (e: unknown) => void;
}) {
  const { user: me } = useAuth();
  const isEdit = edit !== undefined;

  const [email, setEmail] = useState(edit?.email ?? "");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>(edit?.role ?? "operator");
  const [personId, setPersonId] = useState(edit?.person_id ?? "");
  const [busy, setBusy] = useState(false);
  // Varsayılan: davet. Yöneticinin parola uydurup düz metin iletmesi
  // (WhatsApp'tan, sözlü) en zayıf halka — kullanıcı kendi belirlesin.
  const [byInvite, setByInvite] = useState(true);

  const needsPerson = ROLE_NEEDS_PERSON[role] === true;
  const isSelf = isEdit && edit.id === me?.id;
  // super_admin rolüne yalnızca super_admin dokunabilir (API de 403 döner)
  const canUseSuper = me?.role === "super_admin";

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (needsPerson && !personId) {
      onError(new Error("Koç hesabı bir kişiye bağlanmalı — yoksa hiçbir öğrenci göremez."));
      return;
    }
    setBusy(true);
    try {
      if (isEdit) {
        await api.patch(`/users/${edit.id}`, {
          email: email.trim().toLowerCase(),
          role,
          person_id: personId || null,
        });
      } else {
        const created = await api.post<AppUserRow>("/users", {
          email: email.trim().toLowerCase(),
          // null → davet e-postası gider, parola atanmaz
          password: byInvite ? null : password,
          role,
          person_id: personId || null,
        });
        // Hesap açıldı ama davet gitmediyse bunu SÖYLEMEK zorundayız; yoksa
        // yönetici işin bittiğini sanır, kullanıcı e-posta bekler.
        if (created.invite_error) onError(new Error(created.invite_error));
      }
      onDone();
    } catch (err) {
      onError(err);
      setBusy(false);
    }
  }

  return (
    <div className="card" style={{ marginBottom: "1rem" }}>
      <h2>{isEdit ? "Hesabı düzenle" : "Yeni hesap"}</h2>
      <form onSubmit={submit}>
        <div className="field">
          <label htmlFor="ue">E-posta</label>
          <input id="ue" type="email" required autoFocus value={email}
                 onChange={(e) => setEmail(e.target.value)} />
        </div>

        {!isEdit && (
          <>
            <div className="field">
              <label>
                <input type="checkbox" checked={byInvite}
                       style={{ width: "auto", marginRight: ".4rem" }}
                       onChange={(e) => setByInvite(e.target.checked)} />
                Parolasını kendisi belirlesin (davet e-postası gönder)
              </label>
              <span className="muted" style={{ fontSize: ".8rem" }}>
                {byInvite
                  ? "Kullanıcıya bağlantı gider, parolayı yalnızca o bilir. SMTP ayarlarının yapılmış olması gerekir."
                  : "Parolayı siz belirlersiniz ve kullanıcıya iletmeniz gerekir — parolayı iki kişi bilir."}
              </span>
            </div>
            {!byInvite && (
              <div className="field">
                <label htmlFor="up">Parola</label>
                <input id="up" type="password" required minLength={MIN_PW}
                       value={password} onChange={(e) => setPassword(e.target.value)} />
                <span className="muted" style={{ fontSize: ".8rem" }}>
                  En az {MIN_PW} karakter.
                </span>
              </div>
            )}
          </>
        )}

        <div className="field">
          <label htmlFor="ur">Rol</label>
          <select id="ur" value={role} onChange={(e) => setRole(e.target.value as Role)}
                  disabled={isSelf}>
            {canUseSuper && <option value="super_admin">Sistem Yöneticisi</option>}
            <option value="kurum_admin">Kurum Yöneticisi</option>
            <option value="operator">Operatör</option>
            <option value="coach">Koç</option>
          </select>
          <span className="muted" style={{ fontSize: ".8rem" }}>{ROLE_HINT[role]}</span>
          {isSelf && (
            <span className="muted" style={{ fontSize: ".8rem" }}>
              Kendi rolünüzü değiştiremezsiniz.
            </span>
          )}
        </div>

        <div className="field">
          <label htmlFor="upi">
            Bağlı kişi {needsPerson ? "(zorunlu)" : "(isteğe bağlı)"}
          </label>
          <select id="upi" value={personId} onChange={(e) => setPersonId(e.target.value)}>
            <option value="">— bağlı değil —</option>
            {people.map((p) => (
              <option key={p.id} value={p.id}>{p.full_name}</option>
            ))}
          </select>
          {needsPerson ? (
            <span className="muted" style={{ fontSize: ".8rem" }}>
              Koçun göreceği öğrenciler bu kişi üzerinden bulunuyor. Öğrenci
              ataması kişinin kendi sayfasından yapılır.
            </span>
          ) : (
            <span className="muted" style={{ fontSize: ".8rem" }}>
              Hesabı bir personel kaydına bağlar. Yetkilendirmeyi etkilemez.
            </span>
          )}
        </div>

        <div className="row">
          <button type="submit" disabled={busy}>
            {busy ? "Kaydediliyor…" : isEdit ? "Kaydet" : "Hesabı aç"}
          </button>
          <button type="button" className="ghost" onClick={onCancel} disabled={busy}>
            Vazgeç
          </button>
        </div>
      </form>
    </div>
  );
}

function PasswordForm({
  target, onDone, onCancel, onError,
}: {
  target: AppUserRow;
  onDone: () => void;
  onCancel: () => void;
  onError: (e: unknown) => void;
}) {
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post(`/users/${target.id}/password`, { password: pw });
      onDone();
    } catch (err) {
      onError(err);
      setBusy(false);
    }
  }

  return (
    <div className="card" style={{ marginBottom: "1rem" }}>
      <h2>Parola sıfırla — {target.email}</h2>
      <div className="alert info">
        Eski parola sorulmaz; zaten bilinmeyen odur. Yeni parolayı kullanıcıya
        <strong> siz iletin</strong> ve ilk girişte değiştirmesini söyleyin.
      </div>
      <form onSubmit={submit}>
        <div className="field">
          <label htmlFor="npw">Yeni parola</label>
          <input id="npw" type="password" required autoFocus minLength={MIN_PW}
                 value={pw} onChange={(e) => setPw(e.target.value)} />
          <span className="muted" style={{ fontSize: ".8rem" }}>
            En az {MIN_PW} karakter.
          </span>
        </div>
        <div className="row">
          <button type="submit" disabled={busy}>
            {busy ? "Kaydediliyor…" : "Parolayı değiştir"}
          </button>
          <button type="button" className="ghost" onClick={onCancel} disabled={busy}>
            Vazgeç
          </button>
        </div>
      </form>
    </div>
  );
}

export default function Users() {
  const { user: me } = useAuth();
  const [rows, setRows] = useState<AppUserRow[] | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<AppUserRow | null>(null);
  const [pwTarget, setPwTarget] = useState<AppUserRow | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    api.get<AppUserRow[]>("/users")
      .then((d) => { setRows(d); setError(null); })
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  // Hesaba bağlanabilecek kişiler: personel ve koçlar (öğrenci giriş yapmaz)
  useEffect(() => {
    Promise.all([
      api.get<Paged<Person>>("/persons?type=coach&size=200"),
      api.get<Paged<Person>>("/persons?type=staff&size=200"),
    ])
      .then(([c, s]) => setPeople(
        [...c.items, ...s.items].sort((a, b) => a.full_name.localeCompare(b.full_name, "tr"))
      ))
      .catch(() => {});
  }, []);

  async function toggleActive(u: AppUserRow) {
    setError(null);
    try {
      if (u.is_active) await api.del(`/users/${u.id}`);
      else await api.patch(`/users/${u.id}`, { is_active: true });
      load();
    } catch (e) { setError(e); }
  }

  async function sendResetLink(u: AppUserRow) {
    setError(null);
    setNotice(null);
    try {
      const r = await api.post<{ detail: string }>(`/users/${u.id}/invite`);
      setNotice(r.detail);
    } catch (e) { setError(e); }
  }

  function closeAll() {
    setCreating(false);
    setEditing(null);
    setPwTarget(null);
  }

  const activeAdmins = (rows ?? []).filter(
    (u) => u.is_active && (u.role === "super_admin" || u.role === "kurum_admin")
  ).length;

  const coachesWithoutPerson = (rows ?? []).filter(
    (u) => u.is_active && u.role === "coach" && !u.person_id
  );

  return (
    <>
      <div className="page-head">
        <h1>Kullanıcılar</h1>
        <button onClick={() => { closeAll(); setCreating(true); }}>Yeni hesap</button>
      </div>

      <ErrorBox error={error} />
      {notice && <div className="alert ok">{notice}</div>}

      {activeAdmins === 1 && (
        <div className="alert info">
          Kurumda <strong>tek etkin yönetici</strong> var. O hesabın parolası
          unutulursa sisteme girmenin arayüzden bir yolu kalmaz. İkinci bir
          yönetici hesabı açmanız önerilir.
        </div>
      )}

      {coachesWithoutPerson.length > 0 && (
        <div className="alert error">
          <strong>{coachesWithoutPerson.length} koç hesabı bir kişiye bağlı değil</strong>{" "}
          ({coachesWithoutPerson.map((u) => u.email).join(", ")}). Bu hesaplar
          giriş yapabilir ama <strong>hiçbir öğrenci göremez</strong>. Düzenleyip
          kişi bağlayın.
        </div>
      )}

      {creating && (
        <UserForm people={people} onDone={() => { closeAll(); load(); }}
                  onCancel={closeAll} onError={setError} />
      )}
      {editing && (
        <UserForm edit={editing} people={people}
                  onDone={() => { closeAll(); load(); }}
                  onCancel={closeAll} onError={setError} />
      )}
      {pwTarget && (
        <PasswordForm target={pwTarget} onDone={closeAll}
                      onCancel={closeAll} onError={setError} />
      )}

      <div className="card">
        {loading ? (
          <Loading />
        ) : !rows || rows.length === 0 ? (
          <Empty>Hesap yok.</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>E-posta</th>
                <th>Rol</th>
                <th>Bağlı kişi</th>
                <th>Son giriş</th>
                <th>Durum</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((u) => {
                const isSelf = u.id === me?.id;
                return (
                  <tr key={u.id} style={u.is_active ? undefined : { opacity: 0.55 }}>
                    <td>
                      {u.email}
                      {isSelf && (
                        <span className="badge muted" style={{ marginLeft: ".4rem" }}>
                          siz
                        </span>
                      )}
                    </td>
                    <td><RoleBadge role={u.role} /></td>
                    <td>
                      {u.person_name ?? (
                        u.role === "coach"
                          ? <span className="badge danger">bağlı değil</span>
                          : <span className="muted">—</span>
                      )}
                    </td>
                    <td className="muted" title={formatDateTime(u.last_login_at)}>
                      {relativeFromNow(u.last_login_at)}
                    </td>
                    <td>
                      <span className={`badge ${u.is_active ? "ok" : "muted"}`}>
                        {u.is_active ? "Aktif" : "Pasif"}
                      </span>
                    </td>
                    <td className="right">
                      <button className="ghost" onClick={() => {
                        closeAll(); setEditing(u);
                      }}>Düzenle</button>{" "}
                      <button className="ghost" onClick={() => {
                        closeAll(); setPwTarget(u);
                      }}>Parola</button>{" "}
                      {u.is_active && (
                        <button className="ghost" onClick={() => sendResetLink(u)}
                                title="Kullanıcıya parola belirleme bağlantısı gönderir">
                          Bağlantı gönder
                        </button>
                      )}{" "}
                      {!isSelf && (
                        <button className="ghost" onClick={() => toggleActive(u)}>
                          {u.is_active ? "Pasife al" : "Aktif et"}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
