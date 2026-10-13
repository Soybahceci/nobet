/**
 * NÖBET — Koçluk paneli (Faz 9)
 *
 * Koç YALNIZCA kendisine atanmış öğrencileri görür (kontrat §1.3).
 * Filtre sunucuda; bu ekran zaten filtrelenmiş veriyi gösterir.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Empty, ErrorBox, Loading, formatDateTime } from "../ui";
import { hours } from "./Reports";

interface Student {
  person_id: string;
  full_name: string;
  grade: string | null;
  inside_now: boolean;
  week_seconds: number;
  missing_exits: number;
  last_seen: string | null;
}

export default function MyStudents() {
  const [rows, setRows] = useState<Student[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api.get<Student[]>("/reports/my-students")
        .then((d) => { if (alive) { setRows(d); setError(null); } })
        .catch((e) => alive && setError(e))
        .finally(() => alive && setLoading(false));
    load();
    const t = setInterval(load, 30_000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  if (loading) return <Loading />;

  const insideCount = rows.filter((r) => r.inside_now).length;

  return (
    <>
      <div className="page-head">
        <h1>Öğrencilerim</h1>
        <span className="muted">
          {rows.length} öğrenci · {insideCount} tanesi şu an içeride
        </span>
      </div>

      <ErrorBox error={error} />

      <div className="card">
        {rows.length === 0 ? (
          <Empty>
            Size henüz öğrenci atanmamış. Kurum yöneticisi atama yapmalı.
          </Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Öğrenci</th><th>Sınıf</th><th>Durum</th>
                <th>Bu hafta</th><th>Eksik çıkış</th><th>Son hareket</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.person_id}>
                  <td>
                    <Link to={`/kisiler/${r.person_id}`}>{r.full_name}</Link>
                  </td>
                  <td className="muted">{r.grade ?? "—"}</td>
                  <td>
                    {r.inside_now
                      ? <span className="badge ok">İçeride</span>
                      : <span className="muted">—</span>}
                  </td>
                  <td><strong>{hours(r.week_seconds)}</strong></td>
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

      <p className="muted" style={{ fontSize: ".85rem" }}>
        Süreler yalnızca çıkışı okutulmuş oturumları kapsar. Eksik çıkış
        sütununda sayı varsa gerçek süre gösterilenden fazladır.
      </p>
    </>
  );
}
