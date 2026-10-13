/**
 * NÖBET — Bildirim ayarları
 *
 * Kanal ve SMS sağlayıcı ARAYÜZDEN değişir. `.env` düzenleyip konteyner
 * yeniden başlatmak kurum personelinin yapabileceği bir iş değil
 * ("sıfır CLI" kuralı).
 */
import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { ErrorBox, Loading } from "../ui";

interface Preset {
  label: string;
  method: string;
  url: string;
  content_type: string;
  body: Record<string, unknown>;
  success_contains: string;
  notes: string;
}

interface Config {
  channel: string;
  sms_provider: string | null;
  sms_config: Record<string, unknown>;
  has_secret: boolean;
  updated_at: string | null;
  presets: Record<string, Preset>;
  secret_storage_ready: boolean;
  // SMTP (v1.7) — sır ASLA dönmez, yalnızca tanımlı olup olmadığı
  smtp_host: string | null;
  smtp_port: number | null;
  smtp_security: string | null;
  smtp_from: string | null;
  smtp_user: string | null;
  has_smtp_secret: boolean;
}

export default function Settings() {
  const [cfg, setCfg] = useState<Config | null>(null);
  const [channel, setChannel] = useState("dryrun");
  const [provider, setProvider] = useState("netgsm");
  const [sender, setSender] = useState("");
  const [url, setUrl] = useState("");
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [testTo, setTestTo] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get<Config>("/settings/notify")
      .then((d) => {
        setCfg(d);
        setChannel(d.channel);
        setProvider(d.sms_provider ?? "netgsm");
        setSender(String(d.sms_config?.sender ?? ""));
        setUrl(String(d.sms_config?.url ?? ""));
      })
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  // Sağlayıcı değişince ön ayarı yükle — ama alanlar düzenlenebilir kalır
  function pickProvider(p: string) {
    setProvider(p);
    const preset = cfg?.presets?.[p];
    if (preset) setUrl(preset.url);
  }

  // SMS'e ilk geçişte adres boşsa ön ayardan doldur. Aksi halde kullanıcı
  // boş bir adres görüp elle yazmak zorunda kalıyordu.
  useEffect(() => {
    if (channel !== "sms" || url.trim()) return;
    const preset = cfg?.presets?.[provider];
    if (preset?.url) setUrl(preset.url);
  }, [channel, provider, url, cfg]);

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const preset = cfg?.presets?.[provider];
      const body = {
        channel,
        sms_provider: channel === "sms" ? provider : null,
        sms_config: channel === "sms" ? {
          ...(preset ?? {}),
          provider,
          url: url.trim(),
          sender: sender.trim(),
        } : {},
        // Boş bırakılırsa mevcut sır korunur
        sms_user: user || null,
        sms_password: password || null,
      };
      const d = await api.patch<Config>("/settings/notify", body);
      setCfg((c) => (c ? { ...c, ...d } : c));
      setUser(""); setPassword("");
      setMsg("Ayarlar kaydedildi.");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    if (!testTo.trim()) return;
    setBusy(true); setError(null); setMsg(null);
    try {
      const r = await api.post<{ ok: boolean; channel: string; detail: string }>(
        "/settings/notify/test", { to: testTo.trim() },
      );
      setMsg(r.ok
        ? `Test mesajı gönderildi (${r.channel}).`
        : `Gönderilemedi (${r.channel}): ${r.detail}`);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <Loading />;
  if (!cfg) return <ErrorBox error={error} />;

  const preset = cfg.presets?.[provider];

  return (
    <>
      <div className="page-head"><h1>Bildirim ayarları</h1></div>

      <ErrorBox error={error} />
      {msg && <div className="alert ok">{msg}</div>}

      {!cfg.secret_storage_ready && (
        <div className="alert error">
          <strong>Şifreleme anahtarı tanımlı değil.</strong> Sağlayıcı kimlik
          bilgileri kaydedilemez — düz metin saklamak yerine reddediliyor.
          Sunucuda <code>SETTINGS_KEY</code> tanımlanmalı.
        </div>
      )}

      <form onSubmit={save} className="card">
        <div className="field" style={{ maxWidth: 320 }}>
          <label htmlFor="ch">Bildirim kanalı</label>
          <select id="ch" value={channel} onChange={(e) => setChannel(e.target.value)}>
            <option value="dryrun">Kuru çalışma (gönderme, sadece kaydet)</option>
            <option value="whatsapp">WhatsApp</option>
            <option value="sms">SMS</option>
            <option value="email">E-posta</option>
          </select>
        </div>

        {channel === "email" && (
          <div className="alert info">
            E-posta kanalı, aşağıdaki <strong>SMTP</strong> ayarlarını kullanır.
            Velilerin e-posta adresi kayıtlı değilse bildirim gönderilemez —
            WhatsApp/SMS'in aksine e-posta kişi kartında <strong>zorunlu alan
            değil.</strong>
          </div>
        )}

        {channel === "sms" && (
          <>
            <div className="alert info">
              Türkiye'de SMS göndermek için sağlayıcıda <strong>onaylı gönderici
              başlığı</strong> ve İYS kaydı gerekir. Bunlar evrak süreçleridir,
              teknik ayar değil.
            </div>

            <div className="alert info">
              <strong>Kurumda K12NET (ya da başka bir okul sistemi) varsa:</strong>{" "}
              o sistem kendi SMS altyapısını sunmaz — okulun ayrıca anlaştığı bir
              toplu SMS firması üzerinden gönderir. NÖBET için de{" "}
              <strong>aynı firmanın hesabı</strong> kullanılabilir; onaylı başlık
              ve İYS kaydı zaten hazırdır, yeniden alınmaz.
              <br />
              Firmayı bilmiyorsanız SMS faturasına ya da okul sisteminin SMS
              ayarları ekranına bakın. Listede yoksa{" "}
              <strong>"Diğer (elle yapılandır)"</strong> ile herhangi bir HTTP
              API'si tanımlanabilir — sağlayıcıdan <em>gönderim adresi, metot ve
              parametre adlarını</em> isteyin.
            </div>

            <div className="grid cols-2">
              <div className="field">
                <label htmlFor="pv">Sağlayıcı</label>
                <select id="pv" value={provider}
                        onChange={(e) => pickProvider(e.target.value)}>
                  {Object.entries(cfg.presets ?? {}).map(([k, v]) => (
                    <option key={k} value={k}>{v.label}</option>
                  ))}
                </select>
                {preset?.notes && (
                  <span className="muted" style={{ fontSize: ".82rem" }}>
                    {preset.notes}
                  </span>
                )}
              </div>
              <div className="field">
                <label htmlFor="sn">Gönderici başlığı</label>
                <input id="sn" value={sender} placeholder="Onaylı başlık"
                       onChange={(e) => setSender(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="ur">API adresi</label>
                <input id="ur" value={url} className="mono"
                       onChange={(e) => setUrl(e.target.value)} />
                <span className="muted" style={{ fontSize: ".82rem" }}>
                  Ön ayardan gelir, gerekirse düzenleyin.
                </span>
              </div>
              <div className="field">
                <label htmlFor="us">Kullanıcı / API kimliği</label>
                <input id="us" value={user} autoComplete="off"
                       placeholder={cfg.has_secret ? "(kayıtlı — değiştirmek için yazın)" : ""}
                       onChange={(e) => setUser(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="pw">Parola / API anahtarı</label>
                <input id="pw" type="password" value={password} autoComplete="off"
                       placeholder={cfg.has_secret ? "(kayıtlı — değiştirmek için yazın)" : ""}
                       onChange={(e) => setPassword(e.target.value)} />
              </div>
            </div>

            <div className="alert info" style={{ marginBottom: 0 }}>
              Sağlayıcı ön ayarları <strong>başlangıç noktasıdır</strong>. Alan
              adları hesap tipine göre değişebilir — kaydettikten sonra mutlaka
              aşağıdan test mesajı gönderin.
            </div>
          </>
        )}

        <div className="row" style={{ marginTop: "1rem" }}>
          <button type="submit" disabled={busy}>
            {busy ? "Kaydediliyor…" : "Kaydet"}
          </button>
          {cfg.updated_at && (
            <span className="muted">
              Son güncelleme: {new Date(cfg.updated_at).toLocaleString("tr-TR")}
            </span>
          )}
        </div>
      </form>

      <div className="card" style={{ marginTop: "1rem" }}>
        <h2>Test mesajı</h2>
        <p className="muted" style={{ marginTop: 0 }}>
          Ayarların gerçekten çalıştığını doğrular. Bu adım atlanırsa yanlış
          yapılandırma ancak gerçek bir veli bildirimi kaybolduğunda fark edilir.
        </p>
        <div className="row">
          <input value={testTo} onChange={(e) => setTestTo(e.target.value)}
                 placeholder="+90 5.. ... .. .." style={{ maxWidth: 260 }}
                 aria-label="Test numarası" />
          <button className="ghost" onClick={test} disabled={busy || !testTo.trim()}>
            Test gönder
          </button>
        </div>
      </div>

      <SmtpBox cfg={cfg} onSaved={(d) => setCfg({ ...cfg, ...d })} />
    </>
  );
}

/**
 * SMTP ayarları (v1.7).
 *
 * Parola sıfırlama ve davet e-postaları buradan çıkar; bildirim kanalı
 * "E-posta" seçilirse veli bildirimleri de.
 */
function SmtpBox({
  cfg, onSaved,
}: { cfg: Config; onSaved: (d: Partial<Config>) => void }) {
  const [host, setHost] = useState(cfg.smtp_host ?? "");
  const [port, setPort] = useState(String(cfg.smtp_port ?? 587));
  const [security, setSecurity] = useState(cfg.smtp_security ?? "starttls");
  const [from, setFrom] = useState(cfg.smtp_from ?? "");
  const [user, setUser] = useState(cfg.smtp_user ?? "");
  const [password, setPassword] = useState("");
  const [testTo, setTestTo] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null); setMsg(null);
    try {
      const d = await api.put<Config>("/settings/smtp", {
        host: host.trim(), port: Number(port), security,
        from_addr: from.trim(), user: user.trim() || null,
        // Boş bırakılırsa sunucu kayıtlı parolayı KORUR
        password: password || null,
      });
      setPassword("");
      onSaved(d);
      setMsg("SMTP ayarları kaydedildi.");
    } catch (e2) { setErr(e2); } finally { setBusy(false); }
  }

  async function check() {
    setBusy(true); setErr(null); setMsg(null);
    try {
      const r = await api.get<{ ok: boolean; detail: string }>("/settings/smtp/check");
      setMsg(r.ok ? `Bağlantı başarılı: ${r.detail}` : `Bağlanılamadı: ${r.detail}`);
    } catch (e2) { setErr(e2); } finally { setBusy(false); }
  }

  async function sendTest() {
    setBusy(true); setErr(null); setMsg(null);
    try {
      const r = await api.post<{ ok: boolean; detail: string }>(
        "/settings/smtp/test", { to: testTo.trim() });
      setMsg(r.ok ? `Test e-postası gönderildi: ${r.detail}`
                  : `Gönderilemedi: ${r.detail}`);
    } catch (e2) { setErr(e2); } finally { setBusy(false); }
  }

  return (
    <div className="card" style={{ marginTop: "1rem" }}>
      <h2>E-posta (SMTP)</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        Parola sıfırlama ve hesap davet e-postaları buradan gönderilir.
      </p>

      <div className="alert info">
        <strong>Ev bağlantısından doğrudan e-posta göndermek çalışmaz.</strong>{" "}
        Gmail, Outlook ve Yandex konut IP'lerinden gelen postayı reddeder ya da
        spam'e atar (PTR kaydı yok, engel listelerinde). Kendi alan adınızın
        posta sunucusunu ya da bir gönderim servisini <em>kimlik doğrulamalı
        röle</em> olarak kullanın. "Bağlantıyı sına" yalnızca bağlantıyı
        doğrular; <strong>teslimatı doğrulamaz</strong> — onun için test
        e-postası gönderip gerçekten geldiğine bakın.
      </div>

      <ErrorBox error={err} />
      {msg && <div className="alert ok">{msg}</div>}

      <form onSubmit={save}>
        <div className="grid cols-2">
          <div className="field">
            <label htmlFor="sh">Sunucu</label>
            <input id="sh" required value={host} placeholder="mail.ornek.com"
                   onChange={(e) => setHost(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="sp">Port</label>
            <input id="sp" type="number" required value={port}
                   onChange={(e) => setPort(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="ss">Güvenlik</label>
            <select id="ss" value={security} onChange={(e) => setSecurity(e.target.value)}>
              <option value="starttls">STARTTLS (genelde 587)</option>
              <option value="ssl">SSL/TLS (genelde 465)</option>
              <option value="none">Yok (yalnızca yerel röle)</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="sf">Gönderen adresi</label>
            <input id="sf" type="email" required value={from}
                   placeholder="nobet@ornek.com"
                   onChange={(e) => setFrom(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="su">Kullanıcı adı</label>
            <input id="su" value={user} onChange={(e) => setUser(e.target.value)} />
            <span className="muted" style={{ fontSize: ".8rem" }}>
              Boşsa kimlik doğrulama yapılmaz.
            </span>
          </div>
          <div className="field">
            <label htmlFor="sw">Parola</label>
            <input id="sw" type="password" value={password}
                   autoComplete="new-password"
                   placeholder={cfg.has_smtp_secret ? "(kayıtlı — değiştirmek için yazın)" : ""}
                   onChange={(e) => setPassword(e.target.value)} />
            <span className="muted" style={{ fontSize: ".8rem" }}>
              Boş bırakılırsa kayıtlı parola korunur.
            </span>
          </div>
        </div>

        <div className="row">
          <button type="submit" disabled={busy}>
            {busy ? "Kaydediliyor…" : "Kaydet"}
          </button>
          <button type="button" className="ghost" onClick={check} disabled={busy}>
            Bağlantıyı sına
          </button>
        </div>
      </form>

      <div className="row" style={{ marginTop: "1rem" }}>
        <input value={testTo} onChange={(e) => setTestTo(e.target.value)}
               placeholder="test@ornek.com" style={{ maxWidth: 260 }}
               aria-label="Test e-posta adresi" />
        <button className="ghost" onClick={sendTest} disabled={busy || !testTo.trim()}>
          Test e-postası gönder
        </button>
      </div>
    </div>
  );
}
