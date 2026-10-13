/**
 * NÖBET — Jetonla parola belirleme (kontrat §3.1, v1.7)
 *
 * E-postadaki bağlantı buraya düşer. **Oturum gerektirmez** — kullanıcı
 * zaten giriş yapamadığı için buradadır.
 */
import { useEffect, useState, type FormEvent } from "react";
import { publicGet, publicPost } from "../api";
import { Loading } from "../ui";

const MIN_PW = 12;

interface Check {
  valid: boolean;
  email: string | null;
  purpose: "reset" | "invite" | null;
}

export default function SetPassword() {
  const token = new URLSearchParams(window.location.search).get("token") ?? "";

  const [check, setCheck] = useState<Check | null>(null);
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  // Jetonu ÖNDEN doğrula: kullanıcı uzun bir parola yazdıktan sonra
  // "bağlantı geçersiz" duvarına toslamasın.
  useEffect(() => {
    if (!token) { setCheck({ valid: false, email: null, purpose: null }); return; }
    publicGet<Check>(`/auth/reset/${encodeURIComponent(token)}`)
      .then(setCheck)
      .catch(() => setCheck({ valid: false, email: null, purpose: null }));
  }, [token]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (pw !== pw2) { setError("Parolalar eşleşmiyor."); return; }
    setBusy(true);
    try {
      await publicPost("/auth/reset", { token, password: pw });
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Parola belirlenemedi");
      setBusy(false);
    }
  }

  const goLogin = () => { window.location.href = "/"; };

  return (
    <div className="login-wrap">
      <div className="card login-card">
        <div className="brand">NÖBET</div>

        {check === null ? (
          <Loading what="Bağlantı doğrulanıyor" />
        ) : done ? (
          <>
            <div className="alert ok">
              Parolanız belirlendi. Artık giriş yapabilirsiniz.
            </div>
            <button onClick={goLogin} style={{ width: "100%" }}>Girişe git</button>
          </>
        ) : !check.valid ? (
          <>
            <div className="alert error">
              <strong>Bağlantı geçersiz ya da süresi dolmuş.</strong>
            </div>
            <p className="muted" style={{ marginTop: 0 }}>
              Sıfırlama bağlantıları tek kullanımlıktır ve süreleri vardır
              (sıfırlama 1 saat, davet 72 saat). Giriş ekranındaki
              <strong> "Parolamı unuttum"</strong> ile yenisini isteyin.
            </p>
            <button onClick={goLogin} style={{ width: "100%" }}>Girişe dön</button>
          </>
        ) : (
          <>
            <p className="muted" style={{ marginTop: 0 }}>
              {check.purpose === "invite"
                ? "Hesabınız açıldı. Kullanacağınız parolayı belirleyin."
                : "Yeni parolanızı belirleyin."}
              <br />
              <strong>{check.email}</strong>
            </p>
            {error && <div className="alert error">{error}</div>}
            <form onSubmit={submit}>
              <div className="field">
                <label htmlFor="np">Yeni parola</label>
                <input id="np" type="password" required autoFocus minLength={MIN_PW}
                       autoComplete="new-password" value={pw}
                       onChange={(e) => setPw(e.target.value)} />
                <span className="muted" style={{ fontSize: ".8rem" }}>
                  En az {MIN_PW} karakter.
                </span>
              </div>
              <div className="field">
                <label htmlFor="np2">Yeni parola (tekrar)</label>
                <input id="np2" type="password" required minLength={MIN_PW}
                       autoComplete="new-password" value={pw2}
                       onChange={(e) => setPw2(e.target.value)} />
              </div>
              <button type="submit" disabled={busy} style={{ width: "100%" }}>
                {busy ? "Kaydediliyor…" : "Parolayı belirle"}
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
