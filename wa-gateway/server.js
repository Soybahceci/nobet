/**
 * NÖBET — WhatsApp Ağ Geçidi (Faz 8)
 * ===================================
 * ⚠️ RESMÎ WhatsApp Business API DEĞİLDİR.
 *
 * Kişisel bir WhatsApp hesabını Baileys ile sürer. Kullanıcı kararıyla
 * prototipte tercih edildi (2026-08-09). Bilinen riskler:
 *   - WhatsApp kullanım şartlarına aykırı; numara banlanabilir
 *   - Oturum düşebilir, yeniden QR okutmak gerekir
 *   - Kuruma teslimde resmî Cloud API'ye geçilmeli
 *
 * Baileys tercih edildi (whatsapp-web.js değil): tarayıcı gerektirmez,
 * Raspberry Pi 5 / arm64'te sorunsuz çalışır.
 *
 * Uçlar:
 *   GET  /status  -> { connected, state, user }
 *   GET  /qr      -> eşleştirme QR kodu (PNG)
 *   POST /send    -> { to, text }
 */
import express from "express";
import pino from "pino";
import qrcode from "qrcode";
import {
  makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
} from "@whiskeysockets/baileys";

const PORT = process.env.PORT || 3000;
const AUTH_DIR = process.env.AUTH_DIR || "/data/auth";
const DEFAULT_CC = process.env.DEFAULT_COUNTRY_CODE || "90";
const WEBHOOK_URL = process.env.WEBHOOK_URL || "";
const WEBHOOK_SECRET = process.env.WEBHOOK_SECRET || "";

const log = pino({ level: process.env.LOG_LEVEL || "info" });

let sock = null;
let state = "baslatiliyor";
let lastQr = null;
let me = null;

/**
 * Telefon numarasını WhatsApp JID'ine çevirir.
 * "+90 555 111 22 33" -> "905551112233@s.whatsapp.net"
 * Başında 0 olan yerel numaralara ülke kodu eklenir.
 */
function toJid(raw) {
  let d = String(raw).replace(/\D/g, "");
  if (!d) throw new Error("gecersiz numara");
  if (d.startsWith("00")) d = d.slice(2);
  else if (d.startsWith("0")) d = DEFAULT_CC + d.slice(1);
  if (d.length < 10) throw new Error(`numara cok kisa: ${raw}`);
  return `${d}@s.whatsapp.net`;
}

async function connect() {
  const { state: auth, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const { version } = await fetchLatestBaileysVersion();

  sock = makeWASocket({
    version,
    auth,
    logger: pino({ level: "silent" }),
    printQRInTerminal: false,
    markOnlineOnConnect: false,   // telefonu "cevrimici" gostermesin
  });

  sock.ev.on("creds.update", saveCreds);

  // --- Gelen mesajlar -> backend webhook ---
  sock.ev.on("messages.upsert", async ({ messages, type }) => {
    if (type !== "notify") return;   // gecmis senkronu degil, canli mesaj

    for (const m of messages) {
      try {
        // Kendi gonderdigimiz mesajlar geri donmesin — sonsuz dongu olur
        if (m.key?.fromMe) continue;
        // Grup ve yayin mesajlarini yok say; yalnizca birebir sohbet
        const jid = m.key?.remoteJid || "";
        if (!jid.endsWith("@s.whatsapp.net")) continue;

        const text =
          m.message?.conversation ??
          m.message?.extendedTextMessage?.text ??
          null;
        if (!text) continue;   // gorsel/ses/konum — otomatik yanit verilmez

        const phone = jid.split("@")[0];
        const name = m.pushName || null;

        if (!WEBHOOK_URL) {
          log.warn({ phone }, "webhook tanimli degil, mesaj islenmedi");
          continue;
        }

        const res = await fetch(WEBHOOK_URL, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Wa-Secret": WEBHOOK_SECRET,
          },
          body: JSON.stringify({ phone, text, name }),
        });

        if (!res.ok) {
          log.error({ status: res.status }, "webhook reddetti");
          continue;
        }

        // Backend otomatik yanit urettiyse gonder
        const data = await res.json().catch(() => ({}));
        if (data?.reply) {
          await sock.sendMessage(jid, { text: data.reply });
          log.info({ phone }, "otomatik yanit gonderildi");
        }
      } catch (err) {
        log.error({ err: String(err) }, "gelen mesaj islenemedi");
      }
    }
  });

  sock.ev.on("connection.update", async (u) => {
    const { connection, lastDisconnect, qr } = u;

    if (qr) {
      lastQr = qr;
      state = "qr bekleniyor";
      log.warn("QR olusturuldu — GET /qr adresinden okutun");
    }

    if (connection === "open") {
      lastQr = null;
      state = "bagli";
      me = sock?.user?.id?.split(":")[0] ?? null;
      log.info({ user: me }, "WhatsApp baglantisi kuruldu");
    }

    if (connection === "close") {
      const code = lastDisconnect?.error?.output?.statusCode;
      const loggedOut = code === DisconnectReason.loggedOut;
      state = loggedOut ? "oturum kapatildi — QR gerekli" : "yeniden baglaniyor";
      me = null;
      log.warn({ code, loggedOut }, "baglanti koptu");

      if (loggedOut) {
        // Kimlik bilgileri geçersiz; yeni QR için durumu temizlemek gerekir.
        // Dosyaları silmiyoruz — operatör bilinçli karar versin.
        log.error("oturum kapatilmis. /data/auth temizlenip yeniden baslatilmali");
        return;
      }
      setTimeout(() => connect().catch((e) => log.error(e)), 3000);
    }
  });
}

const app = express();
app.use(express.json({ limit: "64kb" }));

app.get("/status", (_req, res) => {
  res.json({ connected: state === "bagli", state, user: me });
});

app.get("/qr", async (_req, res) => {
  if (!lastQr) {
    return res
      .status(404)
      .type("text/plain")
      .send(state === "bagli" ? "Zaten bagli, QR gerekmiyor." : `QR yok (durum: ${state})`);
  }
  res.type("image/png").send(await qrcode.toBuffer(lastQr, { width: 320 }));
});

app.post("/send", async (req, res) => {
  const { to, text } = req.body || {};
  if (!to || !text) return res.status(400).json({ error: "to ve text zorunlu" });
  if (state !== "bagli") return res.status(503).json({ error: `bagli degil: ${state}` });

  try {
    const jid = toJid(to);
    // Numara WhatsApp'ta kayıtlı mı — değilse sessizce kaybolmasın
    const [check] = await sock.onWhatsApp(jid);
    if (!check?.exists) {
      return res.status(422).json({ error: `numara WhatsApp'ta yok: ${to}` });
    }
    await sock.sendMessage(check.jid, { text });
    log.info({ to }, "mesaj gonderildi");
    res.json({ ok: true });
  } catch (err) {
    log.error({ err: String(err), to }, "gonderim hatasi");
    res.status(500).json({ error: String(err) });
  }
});

app.listen(PORT, () => log.info(`ag gecidi ${PORT} portunda`));
connect().catch((e) => {
  log.error(e);
  state = `baslatilamadi: ${e}`;
});
