/**
 * NÖBET — Hesabım: kullanıcının kendi parolasını değiştirmesi (v1.7)
 *
 * Bu sayfa gelmeden önce parolayı **yalnızca yönetici** sıfırlayabiliyordu;
 * yani herkesin parolasını en az bir kişi daha biliyordu.
 */
import { useState, type FormEvent } from "react";
import { api, setTokens } from "../api";
import { ROLE_LABEL, useAuth } from "../auth";
import { ErrorBox } from "../ui";

const MIN_PW = 12;

export default function Account() {
  const { user, signOut } = useAuth();
  const [cur, setCur] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMsg(null);
    if (pw !== pw2) { setError(new Error("Yeni parolalar eşleşmiyor.")); return; }
    setBusy(true);
    try {
      // Parola değişince o andan öncesine ait TÜM token'lar geçersizleşiyor
      // (denetim Y-1) — bu sekmedeki token da dahil. Sunucu taze bir çift
      // döndürüyor; saklamazsak kullanıcı kendi parolasını değiştirdiği anda
      // sistemden atılır.
      const res = await api.post<{ access_token: string }>(
        "/auth/change-password",
        { current_password: cur, new_password: pw },
      );
      // Refresh çerezini sunucu tazeledi; burada yalnızca access token.
      setTokens(res.access_token);
      setCur(""); setPw(""); setPw2("");
      setMsg("Parolanız değiştirildi. Diğer cihazlardaki oturumlarınız kapatıldı.");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-head"><h1>Hesabım</h1></div>

      <div className="card" style={{ marginBottom: "1rem" }}>
        <h2>Bilgiler</h2>
        <div className="grid cols-2">
          <div>
            <div className="muted" style={{ fontSize: ".8rem" }}>E-posta</div>
            <div>{user?.email}</div>
          </div>
          <div>
            <div className="muted" style={{ fontSize: ".8rem" }}>Rol</div>
            <div>{user ? ROLE_LABEL[user.role] : "—"}</div>
          </div>
        </div>
      </div>

      <div className="card">
        <h2>Parolayı değiştir</h2>
        <ErrorBox error={error} />
        {msg && <div className="alert ok">{msg}</div>}
        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="cp">Mevcut parola</label>
            <input id="cp" type="password" required autoComplete="current-password"
                   value={cur} onChange={(e) => setCur(e.target.value)} />
            <span className="muted" style={{ fontSize: ".8rem" }}>
              Açık bırakılmış bir tarayıcının hesabı devralmasını engellemek için
              sorulur.
            </span>
          </div>
          <div className="field">
            <label htmlFor="ap">Yeni parola</label>
            <input id="ap" type="password" required minLength={MIN_PW}
                   autoComplete="new-password" value={pw}
                   onChange={(e) => setPw(e.target.value)} />
            <span className="muted" style={{ fontSize: ".8rem" }}>
              En az {MIN_PW} karakter.
            </span>
          </div>
          <div className="field">
            <label htmlFor="ap2">Yeni parola (tekrar)</label>
            <input id="ap2" type="password" required minLength={MIN_PW}
                   autoComplete="new-password" value={pw2}
                   onChange={(e) => setPw2(e.target.value)} />
          </div>
          <div className="row">
            <button type="submit" disabled={busy}>
              {busy ? "Kaydediliyor…" : "Parolayı değiştir"}
            </button>
            <button type="button" className="ghost" onClick={signOut}>
              Çıkış yap
            </button>
          </div>
        </form>
      </div>
    </>
  );
}
