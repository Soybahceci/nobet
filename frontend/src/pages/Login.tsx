/** NÖBET — Giriş ekranı (kontrat §3.1) */
import { useState, type FormEvent } from "react";
import { publicPost, type TenantChoice } from "../api";
import { ROLE_LABEL, useAuth } from "../auth";

/**
 * "Parolamı unuttum".
 *
 * ⚠️ Sunucu e-posta kayıtlı olsun olmasın **aynı** cevabı veriyor (204).
 * Arayüz de aynı mesajı göstermeli — "böyle bir kullanıcı yok" demek,
 * kurumun kullanıcı listesini çıkarmak için kapı açar.
 */
function Forgot({ onBack }: { onBack: () => void }) {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await publicPost("/auth/forgot", { email: email.trim() });
    } catch {
      // Hata olsa bile aynı ekranı gösteriyoruz: farklı davranmak
      // e-postanın kayıtlı olup olmadığını ele verir.
    }
    setBusy(false);
    setDone(true);
  }

  if (done) {
    return (
      <>
        <div className="alert info">
          <strong>{email}</strong> adresi sistemde kayıtlıysa parola sıfırlama
          bağlantısı gönderildi. Gelen kutunuzu ve spam klasörünü kontrol edin.
          <br />
          <span className="muted" style={{ fontSize: ".85rem" }}>
            Bağlantı 1 saat geçerlidir ve yalnızca bir kez kullanılabilir.
          </span>
        </div>
        <button className="ghost" onClick={onBack} style={{ width: "100%" }}>
          Girişe dön
        </button>
      </>
    );
  }

  return (
    <form onSubmit={submit}>
      <p className="muted" style={{ marginTop: 0 }}>
        Kayıtlı e-posta adresinizi girin; parola belirleme bağlantısı gönderelim.
      </p>
      <div className="field">
        <label htmlFor="femail">E-posta</label>
        <input id="femail" type="email" required autoFocus value={email}
               onChange={(e) => setEmail(e.target.value)} />
      </div>
      <button type="submit" disabled={busy} style={{ width: "100%" }}>
        {busy ? "Gönderiliyor…" : "Sıfırlama bağlantısı gönder"}
      </button>
      <button type="button" className="ghost" onClick={onBack}
              style={{ width: "100%", marginTop: ".5rem" }}>
        Vazgeç
      </button>
    </form>
  );
}

export default function Login() {
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [forgot, setForgot] = useState(false);
  // Faz 13a-0: kişi birden fazla kuruma üyeyse önce kurum seçilir.
  const [choices, setChoices] = useState<TenantChoice[] | null>(null);

  async function attempt(tenantId?: string) {
    setError(null);
    setBusy(true);
    try {
      const opts = await signIn(email.trim(), password, tenantId);
      // null dönerse oturum açıldı; dizi dönerse kurum seçilmeli.
      setChoices(opts);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Giriş yapılamadı");
      setChoices(null);
    } finally {
      setBusy(false);
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    await attempt();
  }

  return (
    <div className="login-wrap">
      <div className="card login-card">
        <div className="brand">NÖBET</div>
        <p className="muted" style={{ marginTop: 0 }}>
          Giriş-çıkış ve yoklama sistemi
        </p>

        {error && <div className="alert error">{error}</div>}

        {choices ? (
          <div>
            <h2 style={{ marginTop: 0 }}>Hangi kurum?</h2>
            <p className="muted">
              Bu hesap birden fazla kuruma bağlı. Devam etmek istediğinizi seçin.
            </p>
            {choices.map((c) => (
              <button
                key={c.tenant_id}
                className="btn"
                style={{ display: "block", width: "100%", marginBottom: ".5rem" }}
                disabled={busy}
                onClick={() => attempt(c.tenant_id)}
              >
                {c.tenant_name}
                <span className="muted"> — {ROLE_LABEL[c.role]}</span>
              </button>
            ))}
            <button
              className="btn ghost"
              disabled={busy}
              onClick={() => { setChoices(null); setPassword(""); }}
            >
              Vazgeç
            </button>
          </div>
        ) : forgot ? <Forgot onBack={() => setForgot(false)} /> : (
        <form onSubmit={onSubmit}>
          <div className="field">
            <label htmlFor="email">E-posta</label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              required
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="password">Parola</label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <button type="submit" disabled={busy} style={{ width: "100%" }}>
            {busy ? "Giriş yapılıyor…" : "Giriş yap"}
          </button>
          <button type="button" className="ghost"
                  onClick={() => { setError(null); setForgot(true); }}
                  style={{ width: "100%", marginTop: ".5rem" }}>
            Parolamı unuttum
          </button>
        </form>
        )}
      </div>
    </div>
  );
}
