/** NÖBET — Okuyucular ve mekânlar (kontrat §3.5) */
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, type NodeRow } from "../api";
import { ADMIN_ROLES, useAuth } from "../auth";
import { Empty, ErrorBox, Loading, formatDateTime, relativeFromNow } from "../ui";

const STATUS: Record<string, { text: string; cls: string }> = {
  online: { text: "Çevrimiçi", cls: "ok" },
  offline: { text: "Çevrimdışı", cls: "danger" },
  disabled: { text: "Devre dışı", cls: "muted" },
};

const ZONE_KIND_LABEL: Record<string, string> = {
  entrance: "Ana giriş",
  library: "Kütüphane",
  classroom: "Derslik",
};

interface Zone {
  id: string;
  name: string;
  kind: string;
  parent_zone_id: string | null;
  auto_close_at: string | null;
}

/**
 * Kontrat v1.2 — okuyucunun sessiz arızası.
 * RC522 askıda kalabiliyor: cihaz ağa bağlı ve heartbeat düzenli gelirken
 * hiçbir kart okunmuyor. "Çevrimiçi" rozeti bu durumu gizler, bu yüzden
 * okuyucu sağlığı AYRI bir sütunda gösteriliyor.
 */
function ReaderHealth({ node }: { node: NodeRow }) {
  if (node.reader_ok === null || node.reader_ok === undefined) {
    return <span className="badge muted" title="Firmware bildirmiyor (eski sürüm)">—</span>;
  }
  if (!node.reader_ok) {
    return <span className="badge danger">Arızalı</span>;
  }
  if (node.reader_reinits > 0) {
    return (
      <span
        className="badge warn"
        title={`Okuyucu ${node.reader_reinits} kez kendini toparladı. Sürekli artıyorsa kablo/besleme kontrol edin.`}
      >
        Çalışıyor · {node.reader_reinits}×
      </span>
    );
  }
  return <span className="badge ok">Sağlam</span>;
}

export default function Nodes() {
  const { can } = useAuth();
  const isAdmin = can(...ADMIN_ROLES);

  const [nodes, setNodes] = useState<NodeRow[]>([]);
  const [zones, setZones] = useState<Zone[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState<"none" | "node" | "zone">("none");

  const load = useCallback(async () => {
    try {
      const [n, z] = await Promise.all([
        api.get<NodeRow[]>("/nodes"),
        api.get<Zone[]>("/zones"),
      ]);
      setNodes(n);
      setZones(z);
      setError(null);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 10_000);
    return () => clearInterval(t);
  }, [load]);

  if (loading) return <Loading />;

  return (
    <>
      <div className="page-head">
        <h1>Donanım</h1>
        {isAdmin && (
          <div className="row">
            <button className="ghost" onClick={() => setForm("zone")}>Yeni mekân</button>
            <button onClick={() => setForm("node")}>Yeni okuyucu</button>
          </div>
        )}
      </div>

      <ErrorBox error={error} />

      {form === "zone" && (
        <NewZone
          onDone={() => { setForm("none"); load(); }}
          onCancel={() => setForm("none")}
        />
      )}
      {form === "node" && (
        <NewNode
          zones={zones}
          onDone={() => { setForm("none"); load(); }}
          onCancel={() => setForm("none")}
        />
      )}

      <div className="card" style={{ marginBottom: "1rem" }}>
        <h2>Okuyucular</h2>
        {nodes.length === 0 ? (
          <Empty>
            Tanımlı okuyucu yok.
            {isAdmin && " Yukarıdaki “Yeni okuyucu” ile ekleyin."}
          </Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Cihaz</th>
                <th>Anahtar</th>
                <th>Mekân</th>
                <th>Durum</th>
                <th>Okuyucu</th>
                <th>Son görülme</th>
                <th>Firmware</th>
              </tr>
            </thead>
            <tbody>
              {nodes.map((n) => {
                const s = STATUS[n.status] ?? { text: n.status, cls: "muted" };
                const zone = zones.find((z) => z.id === n.zone_id);
                return (
                  <tr key={n.id}>
                    <td><strong>{n.name}</strong></td>
                    <td className="mono">{n.node_key}</td>
                    <td className="muted">{zone?.name ?? "—"}</td>
                    <td><span className={`badge ${s.cls}`}>{s.text}</span></td>
                    <td><ReaderHealth node={n} /></td>
                    <td title={formatDateTime(n.last_seen_at)}>
                      {relativeFromNow(n.last_seen_at)}
                    </td>
                    <td className="mono muted">{n.firmware_version ?? "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h2>Mekânlar</h2>
        {zones.length === 0 ? (
          <Empty>Tanımlı mekân yok.</Empty>
        ) : (
          <table>
            <thead>
              <tr><th>Ad</th><th>Tür</th><th>Gece kapatma</th><th>Okuyucu</th></tr>
            </thead>
            <tbody>
              {zones.map((z) => (
                <tr key={z.id}>
                  <td><strong>{z.name}</strong></td>
                  <td className="muted">{ZONE_KIND_LABEL[z.kind] ?? z.kind}</td>
                  <td className="muted">{z.auto_close_at?.slice(0, 5) ?? "—"}</td>
                  <td className="muted">
                    {nodes.filter((n) => n.zone_id === z.id).length}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

function NewZone({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState("entrance");
  const [autoClose, setAutoClose] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/zones", {
        name: name.trim(),
        kind,
        auto_close_at: autoClose || null,
      });
      onDone();
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <div className="card" style={{ marginBottom: "1rem" }}>
      <h2>Yeni mekân</h2>
      <ErrorBox error={error} />
      <form onSubmit={submit}>
        <div className="grid cols-2">
          <div className="field">
            <label htmlFor="zn">Mekân adı</label>
            <input id="zn" required autoFocus value={name}
                   onChange={(e) => setName(e.target.value)}
                   placeholder="Örn. Ana Giriş" />
          </div>
          <div className="field">
            <label htmlFor="zk">Tür</label>
            <select id="zk" value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="entrance">Ana giriş</option>
              <option value="library">Kütüphane</option>
              <option value="classroom">Derslik</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="zc">Gece kapatma saati</label>
            <input id="zc" type="time" value={autoClose}
                   onChange={(e) => setAutoClose(e.target.value)} />
            <span className="muted" style={{ fontSize: ".82rem" }}>
              Bu saatte açık kalan oturumlar kapatılır. Boş bırakılabilir.
            </span>
          </div>
        </div>
        <div className="row">
          <button type="submit" disabled={busy}>{busy ? "Kaydediliyor…" : "Kaydet"}</button>
          <button type="button" className="ghost" onClick={onCancel} disabled={busy}>
            Vazgeç
          </button>
        </div>
      </form>
    </div>
  );
}

function NewNode({
  zones, onDone, onCancel,
}: { zones: Zone[]; onDone: () => void; onCancel: () => void }) {
  const [nodeKey, setNodeKey] = useState("");
  const [name, setName] = useState("");
  const [zoneId, setZoneId] = useState(zones[0]?.id ?? "");
  const [direction, setDirection] = useState("toggle");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/nodes", {
        node_key: nodeKey.trim().toLowerCase(),
        name: name.trim(),
        zone_id: zoneId,
        direction,
        reader_type: "rfid",
      });
      onDone();
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  if (zones.length === 0) {
    return (
      <div className="card" style={{ marginBottom: "1rem" }}>
        <div className="alert info">
          Okuyucu eklemeden önce en az bir mekân tanımlamalısınız.
        </div>
        <button className="ghost" onClick={onCancel}>Kapat</button>
      </div>
    );
  }

  return (
    <div className="card" style={{ marginBottom: "1rem" }}>
      <h2>Yeni okuyucu</h2>
      <ErrorBox error={error} />
      <form onSubmit={submit}>
        <div className="grid cols-2">
          <div className="field">
            <label htmlFor="nk">Cihaz anahtarı</label>
            <input id="nk" required autoFocus value={nodeKey}
                   onChange={(e) => setNodeKey(e.target.value)}
                   pattern="[a-z0-9-]+" placeholder="giris-01" className="mono" />
            <span className="muted" style={{ fontSize: ".82rem" }}>
              Cihazın firmware'indeki <code>NODE_KEY</code> ile <strong>birebir
              aynı</strong> olmalı. Sadece küçük harf, rakam ve tire.
              Sonradan değiştirilemez.
            </span>
          </div>
          <div className="field">
            <label htmlFor="nn">Görünen ad</label>
            <input id="nn" required value={name}
                   onChange={(e) => setName(e.target.value)}
                   placeholder="Ana Giriş Okuyucu" />
          </div>
          <div className="field">
            <label htmlFor="nz">Mekân</label>
            <select id="nz" value={zoneId} onChange={(e) => setZoneId(e.target.value)}>
              {zones.map((z) => <option key={z.id} value={z.id}>{z.name}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="nd">Yön</label>
            <select id="nd" value={direction}
                    onChange={(e) => setDirection(e.target.value)}>
              <option value="toggle">Tek okuyucu (giriş/çıkış sırayla)</option>
              <option value="in">Yalnızca giriş</option>
              <option value="out">Yalnızca çıkış</option>
            </select>
          </div>
        </div>
        <div className="row">
          <button type="submit" disabled={busy}>{busy ? "Kaydediliyor…" : "Kaydet"}</button>
          <button type="button" className="ghost" onClick={onCancel} disabled={busy}>
            Vazgeç
          </button>
        </div>
      </form>
    </div>
  );
}
