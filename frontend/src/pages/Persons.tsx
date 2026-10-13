/** NÖBET — Kişi listesi (kontrat §3.2) */
import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, type Paged, type Person, type PersonType } from "../api";
import { STAFF_ROLES, useAuth } from "../auth";
import { ErrorBox, Empty, Loading, PERSON_TYPE_LABEL } from "../ui";

const SIZE = 25;

export default function Persons() {
  const { can } = useAuth();
  const [data, setData] = useState<Paged<Person> | null>(null);
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [type, setType] = useState<PersonType | "">("");
  const [page, setPage] = useState(1);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true);

    const params = new URLSearchParams({ page: String(page), size: String(SIZE) });
    if (query) params.set("q", query);
    if (type) params.set("type", type);

    api.get<Paged<Person>>(`/persons?${params}`)
      .then((d) => { if (alive) { setData(d); setError(null); } })
      .catch((e) => alive && setError(e))
      .finally(() => alive && setLoading(false));

    return () => { alive = false; };
  }, [query, type, page, creating]);

  function onSearch(e: FormEvent) {
    e.preventDefault();
    setPage(1);
    setQuery(q.trim());
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / SIZE)) : 1;

  return (
    <>
      <div className="page-head">
        <h1>Kişiler</h1>
        {can(...STAFF_ROLES) && (
          <button onClick={() => setCreating(true)}>Yeni kişi</button>
        )}
      </div>

      <ErrorBox error={error} />

      {creating && (
        <NewPerson
          onDone={() => setCreating(false)}
          onCancel={() => setCreating(false)}
        />
      )}

      <div className="card">
        <form onSubmit={onSearch} className="row" style={{ marginBottom: "1rem" }}>
          <input
            placeholder="İsim veya öğrenci no ara…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            style={{ maxWidth: 320 }}
            aria-label="Ara"
          />
          <select
            value={type}
            onChange={(e) => { setPage(1); setType(e.target.value as PersonType | ""); }}
            style={{ maxWidth: 170 }}
            aria-label="Tür"
          >
            <option value="">Tüm türler</option>
            <option value="student">Öğrenci</option>
            <option value="staff">Personel</option>
            <option value="coach">Koç</option>
          </select>
          <button type="submit" className="ghost">Ara</button>
          <div className="spacer" />
          <span className="muted">{data?.total ?? 0} kayıt</span>
        </form>

        {loading ? (
          <Loading />
        ) : !data || data.items.length === 0 ? (
          <Empty>Kayıt bulunamadı.</Empty>
        ) : (
          <>
            <table>
              <thead>
                <tr>
                  <th>Ad Soyad</th>
                  <th>Tür</th>
                  <th>Öğrenci No</th>
                  <th>Durum</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <Link to={`/kisiler/${p.id}`}>{p.full_name}</Link>
                      {p.is_minor && (
                        <span className="badge warn" style={{ marginLeft: ".5rem" }}>
                          18 yaş altı
                        </span>
                      )}
                    </td>
                    <td>{PERSON_TYPE_LABEL[p.person_type] ?? p.person_type}</td>
                    <td className="mono">{p.external_ref ?? "—"}</td>
                    <td>
                      <span className={`badge ${p.status === "active" ? "ok" : "muted"}`}>
                        {p.status === "active" ? "Aktif" : "Pasif"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {totalPages > 1 && (
              <div className="row" style={{ marginTop: "1rem" }}>
                <button
                  className="ghost"
                  disabled={page <= 1}
                  onClick={() => setPage((n) => n - 1)}
                >
                  Önceki
                </button>
                <span className="muted">{page} / {totalPages}</span>
                <button
                  className="ghost"
                  disabled={page >= totalPages}
                  onClick={() => setPage((n) => n + 1)}
                >
                  Sonraki
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}

/** Doğum tarihinden 18 yaş altı mı — form velisini ne zaman soracağını buna göre bilir */
function isMinorDate(iso: string): boolean {
  if (!iso) return false;
  const b = new Date(iso);
  if (Number.isNaN(b.getTime())) return false;
  const t = new Date();
  let age = t.getFullYear() - b.getFullYear();
  const m = t.getMonth() - b.getMonth();
  if (m < 0 || (m === 0 && t.getDate() < b.getDate())) age--;
  return age < 18;
}

function NewPerson({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const [fullName, setFullName] = useState("");
  const [personType, setPersonType] = useState<PersonType>("student");
  const [birthDate, setBirthDate] = useState("");
  const [externalRef, setExternalRef] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");

  // Kayıt alanları (kontrat v1.4)
  const [grade, setGrade] = useState("");
  const [startedAt, setStartedAt] = useState("");
  const [address, setAddress] = useState("");
  const [title, setTitle] = useState("");
  const [department, setDepartment] = useState("");

  // Veli — yalnızca 18 yaş altı öğrencide gösterilir
  const [gName, setGName] = useState("");
  const [gPhone, setGPhone] = useState("");
  const [gRelation, setGRelation] = useState("anne");

  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const minor = personType === "student" && isMinorDate(birthDate);
  const isStudent = personType === "student";

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const person = await api.post<Person>("/persons", {
        full_name: fullName.trim(),
        person_type: personType,
        birth_date: birthDate || null,
        external_ref: externalRef.trim() || null,
        phone: phone.trim() || null,
        email: email.trim() || null,
        started_at: startedAt || null,
        address: address.trim() || null,
        // Alanlar türe göre: öğrenciye unvan, personele sınıf yazılmaz
        grade: isStudent ? (grade.trim() || null) : null,
        title: isStudent ? null : (title.trim() || null),
        department: isStudent ? null : (department.trim() || null),
      });

      // Veli varsa aynı akışta bağla — ayrı adım bırakılırsa unutuluyor
      if (minor && gName.trim() && gPhone.trim()) {
        await api.post(`/persons/${person.id}/guardians`, {
          guardian: { full_name: gName.trim(), phone: gPhone.trim() },
          relation: gRelation,
          is_primary: true,
          notify_enabled: true,
        });
      }
      onDone();
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <div className="card" style={{ marginBottom: "1rem" }}>
      <h2>Yeni kişi</h2>
      <ErrorBox error={error} />
      <form onSubmit={submit}>
        <div className="grid cols-2">
          <div className="field">
            <label htmlFor="fn">Ad Soyad</label>
            <input id="fn" required autoFocus value={fullName}
                   onChange={(e) => setFullName(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="pt">Tür</label>
            <select id="pt" value={personType}
                    onChange={(e) => setPersonType(e.target.value as PersonType)}>
              <option value="student">Öğrenci</option>
              <option value="staff">Personel</option>
              <option value="coach">Koç</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="bd">Doğum tarihi</label>
            <input id="bd" type="date" value={birthDate}
                   onChange={(e) => setBirthDate(e.target.value)} />
            <span className="muted" style={{ fontSize: ".82rem" }}>
              18 yaş altı veli bildirimi buna bakar.
            </span>
          </div>
          <div className="field">
            <label htmlFor="er">{isStudent ? "Öğrenci no" : "Personel no"}</label>
            <input id="er" value={externalRef}
                   onChange={(e) => setExternalRef(e.target.value)} />
            <span className="muted" style={{ fontSize: ".82rem" }}>
              TC kimlik no girmeyin — sistem saklamaz.
            </span>
          </div>
          <div className="field">
            <label htmlFor="ph">Cep telefonu</label>
            <input id="ph" type="tel" value={phone} inputMode="tel"
                   placeholder="+90 5.. ... .. .."
                   onChange={(e) => setPhone(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="em">E-posta</label>
            <input id="em" type="email" value={email}
                   onChange={(e) => setEmail(e.target.value)} />
          </div>

          {/* Kayıt alanları — kontrat v1.4 */}
          <div className="field">
            <label htmlFor="sd">
              {isStudent ? "Kayıt tarihi" : "İşe başlama tarihi"}
            </label>
            <input id="sd" type="date" value={startedAt}
                   onChange={(e) => setStartedAt(e.target.value)} />
          </div>

          {isStudent ? (
            <div className="field">
              <label htmlFor="gr2">Sınıf / seviye</label>
              <input id="gr2" value={grade} placeholder="Örn. 11-A"
                     onChange={(e) => setGrade(e.target.value)} />
            </div>
          ) : (
            <>
              <div className="field">
                <label htmlFor="tt">Görev / unvan</label>
                <input id="tt" value={title} placeholder="Örn. Matematik Öğretmeni"
                       onChange={(e) => setTitle(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="dp">Departman</label>
                <input id="dp" value={department} placeholder="Örn. Sayısal Bölüm"
                       onChange={(e) => setDepartment(e.target.value)} />
              </div>
            </>
          )}
        </div>

        <div className="field">
          <label htmlFor="ad">Adres</label>
          <input id="ad" value={address} onChange={(e) => setAddress(e.target.value)} />
          <span className="muted" style={{ fontSize: ".82rem" }}>
            Kişisel veridir — kurumun aydınlatma metninde yer almalı.
          </span>
        </div>

        {minor && (
          <div style={{ borderTop: "1px solid var(--border)", paddingTop: "1rem" }}>
            <h2 style={{ fontSize: "1rem" }}>Veli bilgileri</h2>
            <div className="alert info">
              Bu öğrenci <strong>18 yaş altı</strong>. Giriş-çıkış bildirimleri
              veliye gider — numara girilmezse <strong>bildirim gönderilemez</strong>.
            </div>
            <div className="grid cols-2">
              <div className="field">
                <label htmlFor="gn">Veli adı soyadı</label>
                <input id="gn" value={gName} onChange={(e) => setGName(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="gp">Veli cep telefonu</label>
                <input id="gp" type="tel" inputMode="tel" value={gPhone}
                       placeholder="+90 5.. ... .. .."
                       onChange={(e) => setGPhone(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="gr">Yakınlık</label>
                <select id="gr" value={gRelation}
                        onChange={(e) => setGRelation(e.target.value)}>
                  <option value="anne">Anne</option>
                  <option value="baba">Baba</option>
                  <option value="vasi">Vasi</option>
                </select>
              </div>
            </div>
          </div>
        )}

        <div className="row">
          <button type="submit" disabled={busy}>
            {busy ? "Kaydediliyor…" : "Kaydet"}
          </button>
          <button type="button" className="ghost" onClick={onCancel} disabled={busy}>
            Vazgeç
          </button>
          {minor && (!gName.trim() || !gPhone.trim()) && (
            <span className="muted">Veli bilgisi boş bırakılırsa sonradan eklenmeli.</span>
          )}
        </div>
      </form>
    </div>
  );
}
