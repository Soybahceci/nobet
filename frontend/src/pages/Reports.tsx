/**
 * NÖBET — Raporlar (Faz 9)
 *
 * Kütüphane senaryosunun karşılığı: kim, nerede, ne kadar kaldı.
 * Eksik çıkışlar süreye DAHİL DEĞİL — ayrı sütunda uyarı olarak gösterilir.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Empty, ErrorBox, Loading, PERSON_TYPE_LABEL, formatDateTime } from "../ui";

interface Row {
  person_id: string;
  full_name: string;
  person_type: string;
  grade: string | null;
  sessions: number;
  total_seconds: number;
  missing_exits: number;
  last_seen: string | null;
}

interface Report {
  date_from: string;
  date_to: string;
  zone_id: string | null;
  zone_name: string | null;
  rows: Row[];
}

interface Zone { id: string; name: string; kind: string }

export function hours(secs: number): string {
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  if (h === 0) return `${m} dk`;
  return `${h} sa ${m} dk`;
}

function isoDaysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

export default function Reports() {
  const [report, setReport] = useState<Report | null>(null);
  const [zones, setZones] = useState<Zone[]>([]);
  const [from, setFrom] = useState(isoDaysAgo(7));
  const [to, setTo] = useState(new Date().toISOString().slice(0, 10));
  const [zoneId, setZoneId] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get<Zone[]>("/zones").then(setZones).catch(() => {});
  }, []);

  const load = useCallback(() => {
    setLoading(true);
    const p = new URLSearchParams({ from, to });
    if (zoneId) p.set("zone_id", zoneId);
    api.get<Report>(`/reports/attendance?${p}`)
      .then((d) => { setReport(d); setError(null); })
      .catch(setError)
      .finally(() => setLoading(false));
  }, [from, to, zoneId]);

  useEffect(load, [load]);

  const totalSecs = report?.rows.reduce((a, r) => a + r.total_seconds, 0) ?? 0;
  const totalMissing = report?.rows.reduce((a, r) => a + r.missing_exits, 0) ?? 0;

  return (
    <>
      <div className="page-head">
        <h1>Raporlar</h1>
        {report && (
          <span className="muted">
            {report.rows.length} kişi · toplam {hours(totalSecs)}
          </span>
        )}
      </div>

      <ErrorBox error={error} />

      <div className="card" style={{ marginBottom: "1rem" }}>
        <div className="row" style={{ flexWrap: "wrap" }}>
          <div className="field" style={{ margin: 0 }}>
            <label htmlFor="rf">Başlangıç</label>
            <input id="rf" type="date" value={from}
                   onChange={(e) => setFrom(e.target.value)} />
          </div>
          <div className="field" style={{ margin: 0 }}>
            <label htmlFor="rt">Bitiş</label>
            <input id="rt" type="date" value={to}
                   onChange={(e) => setTo(e.target.value)} />
          </div>
          <div className="field" style={{ margin: 0, minWidth: 180 }}>
            <label htmlFor="rz">Mekân</label>
            <select id="rz" value={zoneId} onChange={(e) => setZoneId(e.target.value)}>
              <option value="">Tüm mekânlar</option>
              {zones.map((z) => <option key={z.id} value={z.id}>{z.name}</option>)}
            </select>
          </div>
        </div>
      </div>

      {totalMissing > 0 && (
        <div className="alert warn" style={{ background: "var(--warn-bg)", color: "var(--warn)" }}>
          <strong>{totalMissing} oturumda çıkış okutulmamış.</strong> Bu oturumlar
          süre toplamına <strong>dahil edilmedi</strong> — gerçek süreler
          gösterilenden fazla olabilir. Oturumlar sayfasından düzeltilebilir.
        </div>
      )}

      <div className="card">
        {loading ? (
          <Loading />
        ) : !report || report.rows.length === 0 ? (
          <Empty>Bu aralıkta kayıt yok.</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Kişi</th><th>Sınıf</th><th>Tür</th>
                <th>Oturum</th><th>Toplam süre</th>
                <th>Eksik çıkış</th><th>Son hareket</th>
              </tr>
            </thead>
            <tbody>
              {report.rows.map((r) => (
                <tr key={r.person_id}>
                  <td>
                    <Link to={`/kisiler/${r.person_id}`}>{r.full_name}</Link>
                  </td>
                  <td className="muted">{r.grade ?? "—"}</td>
                  <td className="muted">{PERSON_TYPE_LABEL[r.person_type]}</td>
                  <td>{r.sessions}</td>
                  <td><strong>{hours(r.total_seconds)}</strong></td>
                  <td>
                    {r.missing_exits > 0
                      ? <span className="badge warn">{r.missing_exits}</span>
                      : <span className="muted">—</span>}
                  </td>
                  <td className="muted">{formatDateTime(r.last_seen)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
