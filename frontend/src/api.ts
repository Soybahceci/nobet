/**
 * NÖBET — API istemcisi
 * Kontrat: docs/nobet-faz1-sistem-sozlesmesi.md §3
 *
 * Token saklama kararı (denetim bulgusu D-3, 2026-08-10):
 *   access_token  -> yalnızca BELLEKTE. Sayfa yenilenince kaybolur, refresh
 *                    ile yeniden alınır. Kısa ömürlü (30 dk).
 *   refresh_token -> **HttpOnly ÇEREZ.** JavaScript göremez, dolayısıyla bu
 *                    dosyada hiçbir yerde geçmez.
 *
 * Eskiden refresh token `localStorage`'daydı ve tek bir XSS açığı 14 günlük
 * oturumu kalıcı olarak çalabiliyordu. Artık sunucu çerezi kendisi kuruyor
 * (SameSite=strict, path=/api/v1/auth) ve yanıt gövdesinde DÖNMÜYOR —
 * dönseydi burada yine saklanabilir ve korumanın anlamı kalmazdı.
 *
 * Bearer modeli korunuyor: access_token hâlâ `Authorization` başlığında
 * gidiyor (kontrat §3.1). Değişen yalnızca uzun ömürlü kimlik bilgisinin
 * NEREDE durduğu.
 */

const BASE = "/api/v1";
let accessToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

/** Access token'ı belleğe koyar. Refresh token'a dokunulmaz — o çerezde. */
export function setTokens(access: string) {
  accessToken = access;
}

/**
 * Bellekteki access token'ı siler.
 *
 * ⚠️ Refresh çerezini SİLEMEZ (HttpOnly). Gerçek çıkış için
 * `POST /auth/logout` çağrılmalı — sunucu çerezi orada temizler.
 */
export function clearTokens() {
  accessToken = null;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: unknown,
  ) {
    super(message);
  }
}

/** Sunucu hata gövdesinden okunabilir bir mesaj çıkarır. */
function readError(status: number, body: any): ApiError {
  let msg = `İstek başarısız (HTTP ${status})`;
  const d = body?.detail;
  if (typeof d === "string") {
    msg = d;
  } else if (Array.isArray(d) && d.length) {
    // FastAPI doğrulama hatası
    const first = d[0];
    const field = Array.isArray(first?.loc) ? first.loc.slice(1).join(".") : "";
    msg = field ? `${field}: ${first?.msg ?? "geçersiz"}` : (first?.msg ?? msg);
  }
  return new ApiError(status, msg, d);
}

async function refreshAccess(): Promise<boolean> {
  // Refresh token çerezde; aynı kökene giden istekte tarayıcı onu
  // kendiliğinden ekler (fetch varsayılanı `credentials: "same-origin"`).
  const res = await fetch(`${BASE}/auth/refresh`, { method: "POST" });
  if (!res.ok) return false;

  const data = await res.json();
  accessToken = data.access_token;
  return true;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  retry = true,
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);

  const res = await fetch(`${BASE}${path}`, { ...init, headers });

  // Access token süresi dolduysa sessizce yenile ve bir kez tekrar dene
  if (res.status === 401 && retry) {
    if (await refreshAccess()) return request<T>(path, init, false);
    clearTokens();
    onUnauthorized?.();
    throw new ApiError(401, "Oturum sona erdi, tekrar giriş yapın");
  }

  if (res.status === 204) return undefined as T;

  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) throw readError(res.status, body);
  return body as T;
}

/**
 * Oturum GEREKTİRMEYEN uçlar: parola sıfırlama akışı.
 *
 * `request` 401 alınca token yenilemeye çalışıp oturumu düşürüyor; bu uçlarda
 * zaten oturum yok, o mekanizma yanlışlıkla "oturum sona erdi" durumunu
 * tetiklerdi.
 */
async function publicRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(`${BASE}${path}`, { ...init, headers });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) throw readError(res.status, body);
  return body as T;
}

export const publicGet = <T>(p: string) => publicRequest<T>(p);
export const publicPost = <T>(p: string, body?: unknown) =>
  publicRequest<T>(p, {
    method: "POST",
    body: body ? JSON.stringify(body) : undefined,
  });

/**
 * Kimlik doğrulamalı ikili içerik (QR görseli gibi).
 * `<img src>` özel başlık gönderemediği için görsel blob olarak çekilip
 * object URL'e çevrilir.
 */
export async function fetchBlob(path: string, retry = true): Promise<Blob> {
  const headers = new Headers();
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);

  const res = await fetch(`${BASE}${path}`, { headers });

  if (res.status === 401 && retry) {
    if (await refreshAccess()) return fetchBlob(path, false);
    clearTokens();
    onUnauthorized?.();
    throw new ApiError(401, "Oturum sona erdi");
  }
  if (!res.ok) {
    let detail: unknown = null;
    try { detail = await res.json(); } catch { /* gövde JSON değil */ }
    throw readError(res.status, detail);
  }
  return res.blob();
}

export const api = {
  get: <T>(p: string) => request<T>(p),
  post: <T>(p: string, body?: unknown) =>
    request<T>(p, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  put: <T>(p: string, body: unknown) =>
    request<T>(p, { method: "PUT", body: JSON.stringify(body) }),
  patch: <T>(p: string, body: unknown) =>
    request<T>(p, { method: "PATCH", body: JSON.stringify(body) }),
  del: <T>(p: string) => request<T>(p, { method: "DELETE" }),
};

/**
 * Canlı olay akışı — kontrat §3.6 (Server-Sent Events)
 *
 * Tarayıcının `EventSource` API'si özel başlık gönderemiyor, ucumuz ise
 * Bearer token istiyor. Token'ı URL'ye koymak onu tarayıcı geçmişine ve
 * sunucu loglarına sızdırırdı; bu yüzden akış `fetch` ile okunuyor.
 *
 * Bağlantı koparsa artan gecikmeyle yeniden bağlanır. `stop()` ile kapatılır.
 */
export function streamEvents(
  onEvent: (e: EventRow) => void,
  onStateChange?: (connected: boolean) => void,
): () => void {
  const controller = new AbortController();
  let stopped = false;
  let backoff = 1000;

  async function connect() {
    while (!stopped) {
      try {
        if (!accessToken && !(await refreshAccess())) {
          throw new Error("token yok");
        }

        const res = await fetch(`${BASE}/events/stream`, {
          headers: { Authorization: `Bearer ${accessToken}` },
          signal: controller.signal,
        });

        if (res.status === 401) {
          if (!(await refreshAccess())) throw new Error("yetki yok");
          continue;
        }
        if (!res.ok || !res.body) throw new Error(`akış açılamadı (${res.status})`);

        onStateChange?.(true);
        backoff = 1000;

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";

        while (!stopped) {
          const { done, value } = await reader.read();
          if (done) break;

          buf += decoder.decode(value, { stream: true });

          // SSE olayları boş satırla ayrılır
          let sep: number;
          while ((sep = buf.indexOf("\n\n")) !== -1) {
            const chunk = buf.slice(0, sep);
            buf = buf.slice(sep + 2);

            const dataLine = chunk
              .split("\n")
              .find((l) => l.startsWith("data:"));
            if (!dataLine) continue;   // keepalive yorumu

            try {
              onEvent(JSON.parse(dataLine.slice(5).trim()) as EventRow);
            } catch {
              /* bozuk kare akışı düşürmesin */
            }
          }
        }
      } catch (err) {
        if (stopped || (err as Error)?.name === "AbortError") return;
      }

      onStateChange?.(false);
      if (stopped) return;
      await new Promise((r) => setTimeout(r, backoff));
      backoff = Math.min(backoff * 2, 15000);
    }
  }

  connect();

  return () => {
    stopped = true;
    controller.abort();
  };
}

/** Giriş — kontrat §3.1 */
/** Birden fazla kuruma üye olan kullanıcıya sunulan seçenek (Faz 13a-0). */
export interface TenantChoice {
  tenant_id: string;
  tenant_name: string;
  role: Role;
}

/**
 * Girişin iki olası sonucu (Faz 13a-0).
 *  - `user` dolu  → giriş tamam
 *  - `choices` dolu → kurum seçilmeli, aynı çağrı `tenantId` ile tekrarlanır
 */
export type LoginResult =
  | { kind: "ok"; user: User }
  | { kind: "choose"; choices: TenantChoice[] };

export async function login(
  email: string,
  password: string,
  tenantId?: string,
): Promise<LoginResult> {
  const res = await fetch(`${BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, tenant_id: tenantId ?? null }),
  });
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) throw readError(res.status, body);

  if (!body.access_token) {
    return { kind: "choose", choices: (body.choices ?? []) as TenantChoice[] };
  }
  // Refresh token gövdede yok — sunucu çerez olarak kurdu.
  setTokens(body.access_token);
  return { kind: "ok", user: body.user as User };
}

/** Sayfa yenilendiğinde oturumu geri kur. */
export async function restoreSession(): Promise<User | null> {
  // Çerez HttpOnly olduğu için varlığı buradan görülemez; doğrudan
  // denenir. Yoksa sunucu 401 döner ve oturum yok sayılır.
  if (!(await refreshAccess())) {
    clearTokens();
    return null;
  }
  try {
    return await api.get<User>("/me");
  } catch {
    clearTokens();
    return null;
  }
}

// --- Tipler (kontrat §3) ---------------------------------------------------
export type Role = "super_admin" | "kurum_admin" | "operator" | "coach";
export type PersonType = "student" | "staff" | "coach";
export type Decision =
  | "granted"
  | "unknown_credential"
  | "revoked"
  | "duplicate"
  | "disabled_node";

export interface User {
  id: string;
  email: string;
  role: Role;
  tenant_id: string;
  person_id: string | null;
  is_active: boolean;
  // Faz 13b: abonelik kademesi — kabuk bandrolü buna bakar.
  subscription_status?: string;
}

/**
 * Kullanıcılar sayfasındaki satır. `User`'dan ayrı tutuldu: bu, yöneticinin
 * BAŞKA hesaplar hakkında gördüğü bilgi (son giriş, bağlı kişi adı);
 * `User` ise oturum açan kişinin kendisi.
 */
export interface AppUserRow {
  id: string;
  email: string;
  role: Role;
  is_active: boolean;
  person_id: string | null;
  person_name: string | null;
  last_login_at: string | null;
  created_at: string;
  /**
   * Davet e-postasının akıbeti — yalnızca hesap açma yanıtında dolu olur.
   * `invite_error` doluysa hesap açıldı ama e-posta gitmedi; arayüz bunu
   * söylemek zorunda, yoksa yönetici işin bittiğini sanır.
   */
  invite_sent?: boolean | null;
  invite_error?: string | null;
}

export interface Person {
  id: string;
  full_name: string;
  person_type: PersonType;
  birth_date: string | null;
  external_ref: string | null;
  phone: string | null;
  email: string | null;
  status: string;
  is_minor: boolean;
  /** Kayıt alanları — kontrat v1.4 */
  grade: string | null;
  started_at: string | null;
  address: string | null;
  title: string | null;
  department: string | null;
  /** Dolu ise kimlik alanları KVKK talebi üzerine temizlenmiştir */
  anonymized_at: string | null;
}

export interface Credential {
  id: string;
  person_id: string;
  type: "rfid" | "fingerprint";
  identifier: string;
  label: string | null;
  status: "active" | "lost" | "revoked";
  issued_at: string;
}

export interface GuardianLink {
  id: string;
  full_name: string;
  phone: string;
  email: string | null;
  relation: string;
  is_primary: boolean;
  notify_enabled: boolean;
  /**
   * Bu velinin bağlı olduğu öğrenci sayısı. `guardian` satırı kardeşler
   * arasında ortak olduğu için düzenleme formu buradan uyarı üretir.
   */
  linked_person_count: number;
}

export interface EventRow {
  id: number;
  seq: number;
  node_id: string;
  cred_type: string;
  cred_identifier: string;
  person_id: string | null;
  /** Kayıtsız kart okumasında null olur */
  person_name: string | null;
  decision: Decision;
  effective_ts: string;
  server_ts: string;
  from_buffer: boolean;
}

export interface PersonDetail extends Person {
  credentials: Credential[];
  guardians: GuardianLink[];
  recent_events: EventRow[];
}

export interface PendingRead {
  event_id: number;
  cred_type: "rfid" | "fingerprint";
  cred_identifier: string;
  node_name: string;
  seen_at: string;
}

export interface NodeRow {
  id: string;
  node_key: string;
  name: string;
  zone_id: string;
  direction: string;
  reader_type: string;
  firmware_version: string | null;
  last_seen_at: string | null;
  status: "online" | "offline" | "disabled";
  /** Kontrat v1.2 — null: firmware bildirmiyor */
  reader_ok: boolean | null;
  reader_reinits: number;
}

export interface DashboardSummary {
  inside_now: Record<string, number>;
  today_events: number;
  nodes: Record<string, number>;
  open_sessions: number;
  unknown_reads_24h: number;
}

export interface Paged<T> {
  total: number;
  page: number;
  size: number;
  items: T[];
}
