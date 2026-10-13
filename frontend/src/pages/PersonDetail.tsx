/** NÖBET — Kişi detayı (kontrat §3.2, §3.3) */
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type GuardianLink, type PersonDetail as Detail } from "../api";
import { STAFF_ROLES, useAuth } from "../auth";
import {
  DecisionBadge, Empty, ErrorBox, Loading, PERSON_TYPE_LABEL, formatDateTime,
} from "../ui";

const CRED_STATUS: Record<string, { text: string; cls: string }> = {
  active: { text: "Aktif", cls: "ok" },
  lost: { text: "Kayıp", cls: "warn" },
  revoked: { text: "İptal", cls: "danger" },
};

function Info({ label, value, mono }: { label: string; value: string | null | undefined; mono?: boolean }) {
  return (
    <div>
      <div className="muted" style={{ fontSize: ".8rem" }}>{label}</div>
      <div className={mono ? "mono" : undefined}>{value || "—"}</div>
    </div>
  );
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("tr-TR");
}

/**
 * Veli / acil durum kişisi — ekleme ve düzenleme.
 *
 * `person_guardian` çoka-çok olduğu için ikinci veli ayrı bir alan
 * gerektirmiyor; acil durum kişisi de aynı tabloda `relation` ile ayrılıyor.
 *
 * `edit` verilirse düzenleme kipinde çalışır. Kimlik alanları (ad, telefon)
 * `guardian` satırına yazıldığı ve o satır kardeşler arasında paylaşılabildiği
 * için düzenleme kipinde kullanıcı uyarılır.
 */
function GuardianForm({
  personId, edit, siblingCount, onDone, onCancel, onError,
}: {
  personId: string;
  edit?: GuardianLink;
  /** Bu velinin bağlı olduğu diğer öğrenci sayısı (bilinmiyorsa undefined) */
  siblingCount?: number;
  onDone: () => void;
  onCancel: () => void;
  onError: (e: unknown) => void;
}) {
  const [fullName, setFullName] = useState(edit?.full_name ?? "");
  const [phone, setPhone] = useState(edit?.phone ?? "");
  const [relation, setRelation] = useState(edit?.relation ?? "anne");
  const [notify, setNotify] = useState(edit?.notify_enabled ?? true);
  const [isPrimary, setIsPrimary] = useState(edit?.is_primary ?? false);
  const [busy, setBusy] = useState(false);

  const isEmergency = relation === "acil_durum";
  const isEdit = edit !== undefined;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      // Acil durum kişisine her giriş-çıkışta mesaj gitmesi istenmez
      const notifyEnabled = isEmergency ? false : notify;
      if (isEdit) {
        await api.patch(`/persons/${personId}/guardians/${edit.id}`, {
          full_name: fullName.trim(),
          phone: phone.trim(),
          relation,
          is_primary: isEmergency ? false : isPrimary,
          notify_enabled: notifyEnabled,
        });
      } else {
        await api.post(`/persons/${personId}/guardians`, {
          guardian: { full_name: fullName.trim(), phone: phone.trim() },
          relation,
          is_primary: false,
          notify_enabled: notifyEnabled,
        });
      }
      onDone();
    } catch (err) {
      onError(err);
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} style={{ marginBottom: "1rem" }}>
      {isEdit && siblingCount !== undefined && siblingCount > 0 && (
        <div className="alert info">
          Bu veli <strong>{siblingCount} öğrenciye daha</strong> bağlı.
          Ad ve telefon değişikliği hepsinde geçerli olur; yakınlık ve
          bildirim ayarı yalnızca bu öğrenci için değişir.
        </div>
      )}
      <div className="field">
        <label htmlFor="agn">Ad Soyad</label>
        <input id="agn" required autoFocus value={fullName}
               onChange={(e) => setFullName(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="agp">Cep telefonu</label>
        <input id="agp" required type="tel" inputMode="tel" value={phone}
               placeholder="+90 5.. ... .. .."
               onChange={(e) => setPhone(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="agr">Yakınlık</label>
        <select id="agr" value={relation} onChange={(e) => setRelation(e.target.value)}>
          <option value="anne">Anne</option>
          <option value="baba">Baba</option>
          <option value="vasi">Vasi</option>
          <option value="acil_durum">Acil durum kişisi</option>
        </select>
      </div>
      {isEmergency ? (
        <div className="alert info">
          Acil durum kişisine <strong>rutin giriş-çıkış bildirimi gitmez</strong>,
          yalnızca kayıt olarak tutulur.
        </div>
      ) : (
        <>
          <div className="field">
            <label>
              <input type="checkbox" checked={notify} style={{ width: "auto", marginRight: ".4rem" }}
                     onChange={(e) => setNotify(e.target.checked)} />
              Giriş-çıkış bildirimi gönderilsin
            </label>
          </div>
          {isEdit && (
            <div className="field">
              <label>
                <input type="checkbox" checked={isPrimary}
                       style={{ width: "auto", marginRight: ".4rem" }}
                       onChange={(e) => setIsPrimary(e.target.checked)} />
                Birincil veli
              </label>
              <span className="muted" style={{ fontSize: ".8rem" }}>
                Bir öğrencinin tek birincil velisi olur; işaretlerseniz diğeri düşer.
              </span>
            </div>
          )}
        </>
      )}
      <div className="row">
        <button type="submit" disabled={busy}>
          {busy ? (isEdit ? "Kaydediliyor…" : "Ekleniyor…") : (isEdit ? "Kaydet" : "Ekle")}
        </button>
        <button type="button" className="ghost" onClick={onCancel} disabled={busy}>
          Vazgeç
        </button>
      </div>
    </form>
  );
}

/**
 * Koç ataması (kontrat §1.3).
 * Bu bir YETKİ işlemidir: koç yalnızca atandığı öğrencileri görebilir,
 * dolayısıyla atama yapmak veri erişimi açmak demektir — admin gerektirir.
 */
function CoachBox({
  personId, isAdmin, onError,
}: { personId: string; isAdmin: boolean; onError: (e: unknown) => void }) {
  const [coaches, setCoaches] = useState<{ id: string; full_name: string }[]>([]);
  const [available, setAvailable] = useState<{ id: string; full_name: string }[]>([]);
  const [pick, setPick] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.get<{ id: string; full_name: string }[]>(`/persons/${personId}/coaches`)
      .then(setCoaches)
      .catch(onError);
  }, [personId, onError]);

  useEffect(load, [load]);

  useEffect(() => {
    if (!isAdmin) return;
    api.get<{ items: { id: string; full_name: string }[] }>("/persons?type=coach&size=100")
      .then((d) => setAvailable(d.items))
      .catch(() => {});
  }, [isAdmin]);

  async function assign() {
    if (!pick) return;
    setBusy(true);
    try {
      await api.post(`/persons/${personId}/coaches/${pick}`);
      setPick("");
      load();
    } catch (e) { onError(e); } finally { setBusy(false); }
  }

  async function remove(coachId: string) {
    setBusy(true);
    try {
      await api.del(`/persons/${personId}/coaches/${coachId}`);
      load();
    } catch (e) { onError(e); } finally { setBusy(false); }
  }

  const assignable = available.filter((a) => !coaches.some((c) => c.id === a.id));

  return (
    <div className="card" style={{ marginTop: "1rem" }}>
      <h2>Koçlar</h2>
      {coaches.length === 0 ? (
        <Empty>Koç atanmamış.</Empty>
      ) : (
        <table>
          <tbody>
            {coaches.map((c) => (
              <tr key={c.id}>
                <td><strong>{c.full_name}</strong></td>
                {isAdmin && (
                  <td className="right">
                    <button className="ghost" disabled={busy}
                            onClick={() => remove(c.id)}>Kaldır</button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {isAdmin && (
        assignable.length > 0 ? (
          <div className="row" style={{ marginTop: ".75rem" }}>
            <select value={pick} onChange={(e) => setPick(e.target.value)}
                    style={{ maxWidth: 260 }} aria-label="Koç seç">
              <option value="">Koç seçin…</option>
              {assignable.map((a) => (
                <option key={a.id} value={a.id}>{a.full_name}</option>
              ))}
            </select>
            <button onClick={assign} disabled={busy || !pick}>Ata</button>
          </div>
        ) : (
          <p className="muted" style={{ fontSize: ".85rem", marginBottom: 0 }}>
            Atanabilecek koç yok. Kişiler sayfasından <strong>tür: Koç</strong>{" "}
            olan kişi ekleyin.
          </p>
        )
      )}
    </div>
  );
}

export default function PersonDetail() {
  const { id } = useParams<{ id: string }>();
  const { can } = useAuth();
  const [p, setP] = useState<Detail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [confirmOff, setConfirmOff] = useState(false);
  const [addingGuardian, setAddingGuardian] = useState(false);
  const [editingGuardian, setEditingGuardian] = useState<GuardianLink | null>(null);
  const [confirmAnon, setConfirmAnon] = useState(false);

  const load = useCallback(() => {
    if (!id) return;
    setLoading(true);
    api.get<Detail>(`/persons/${id}`)
      .then((d) => { setP(d); setError(null); })
      .catch(setError)
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(load, [load]);

  async function setCredStatus(credId: string, status: string) {
    try {
      await api.patch(`/credentials/${credId}`, { status });
      load();
    } catch (e) {
      setError(e);
    }
  }

  /**
   * Kontrat §3.2 — yumuşak silme. Kişi kaydı ve geçmiş olayları KORUNUR,
   * yalnızca `passive` işaretlenir. Kalıcı silme bilinçli olarak yok:
   * `event.person_id` yabancı anahtarı RESTRICT, çünkü olaylar değişmez.
   */
  async function setPersonStatus(status: "active" | "passive") {
    setError(null);
    try {
      if (status === "passive") {
        await api.del(`/persons/${id}`);
      } else {
        await api.patch(`/persons/${id}`, { status: "active" });
      }
      setConfirmOff(false);
      load();
    } catch (e) {
      setError(e);
    }
  }

  async function anonymize() {
    setError(null);
    try {
      await api.post(`/persons/${id}/anonymize`);
      setConfirmAnon(false);
      load();
    } catch (e) { setError(e); }
  }

  async function removeGuardian(guardianId: string) {
    try {
      await api.del(`/persons/${id}/guardians/${guardianId}`);
      load();
    } catch (e) { setError(e); }
  }

  if (loading) return <Loading />;
  if (error && !p) return <ErrorBox error={error} />;
  if (!p) return null;

  const isStaff = can(...STAFF_ROLES);
  const isStudent = p.person_type === "student";
  // Anonimleştirilmiş kayda yeni kişisel veri bağlanamaz (API de 409 döner)
  const canEditGuardians = isStaff && !p.anonymized_at;

  return (
    <>
      <div className="page-head">
        <div>
          <h1 style={{ marginBottom: ".25rem" }}>
            {p.full_name}{" "}
            {p.is_minor && <span className="badge warn">18 yaş altı</span>}
          </h1>
          <span className="muted">
            {PERSON_TYPE_LABEL[p.person_type]}
            {p.external_ref && ` · ${p.external_ref}`}
          </span>
          {p.status !== "active" && (
            <span className="badge muted" style={{ marginLeft: ".5rem" }}>Pasif</span>
          )}
        </div>
        <div className="row">
          {isStaff && (
            p.status === "active" ? (
              <button className="ghost" onClick={() => setConfirmOff(true)}>
                Pasife al
              </button>
            ) : (
              !p.anonymized_at && (
                <button className="ghost" onClick={() => setPersonStatus("active")}>
                  Yeniden aktif et
                </button>
              )
            )
          )}
          {can("super_admin", "kurum_admin") && !p.anonymized_at && (
            <button className="ghost" onClick={() => setConfirmAnon(true)}
                    title="KVKK silme talebi">
              Anonimleştir
            </button>
          )}
          <Link to="/kisiler"><button className="ghost">Listeye dön</button></Link>
        </div>
      </div>

      <ErrorBox error={error} />

      {p.anonymized_at && (
        <div className="alert info">
          Bu kayıt <strong>{formatDate(p.anonymized_at)}</strong> tarihinde
          KVKK talebi üzerine anonimleştirildi. Kimlik bilgileri temizlendi;
          geçmiş hareketler denetim izi olarak korunuyor.
        </div>
      )}

      {confirmAnon && (
        <div className="card" style={{ marginBottom: "1rem", borderColor: "var(--danger)" }}>
          <h2>KVKK — kaydı anonimleştir</h2>
          <div className="alert error">
            <strong>Bu işlem geri alınamaz.</strong> Temizlenen bilgiler
            hiçbir yerde saklanmaz.
          </div>
          <p className="muted" style={{ marginTop: 0 }}>
            Silinecek: ad soyad, doğum tarihi, telefon, e-posta, adres,
            öğrenci/personel no, sınıf, unvan. Kartları iptal edilecek,
            veli ve koç bağlantıları kaldırılacak.
          </p>
          <p className="muted">
            Korunacak: geçmiş giriş-çıkış hareketleri. Bunlar silinemez
            (denetim izi) ama artık bir kişiyi işaret etmeyecek.
          </p>
          <div className="row">
            <button className="danger" onClick={anonymize}>
              Evet, anonimleştir
            </button>
            <button className="ghost" onClick={() => setConfirmAnon(false)}>
              Vazgeç
            </button>
          </div>
        </div>
      )}

      {confirmOff && (
        <div className="card" style={{ marginBottom: "1rem" }}>
          <h2>{p.full_name} pasife alınsın mı?</h2>
          <p className="muted" style={{ marginTop: 0 }}>
            Kişi listelerden düşer ve kartları çalışmaya devam etmez.
            <strong> Kayıt silinmez</strong> — geçmiş giriş-çıkış hareketleri
            denetim izi olarak korunur ve kişi istendiğinde yeniden aktif edilebilir.
          </p>
          <div className="row">
            <button className="danger" onClick={() => setPersonStatus("passive")}>
              Evet, pasife al
            </button>
            <button className="ghost" onClick={() => setConfirmOff(false)}>
              Vazgeç
            </button>
          </div>
        </div>
      )}

      <div className="card" style={{ marginBottom: "1rem" }}>
        <h2>Kayıt bilgileri</h2>
        <div className="grid cols-2">
          <Info label={isStudent ? "Kayıt tarihi" : "İşe başlama"}
                value={p.started_at ? formatDate(p.started_at) : null} />
          {isStudent
            ? <Info label="Sınıf / seviye" value={p.grade} />
            : <Info label="Görev / unvan" value={p.title} />}
          {!isStudent && <Info label="Departman" value={p.department} />}
          <Info label="Doğum tarihi"
                value={p.birth_date ? formatDate(p.birth_date) : null} />
          <Info label="Cep telefonu" value={p.phone} mono />
          <Info label="E-posta" value={p.email} />
          <Info label={isStudent ? "Öğrenci no" : "Personel no"}
                value={p.external_ref} mono />
          <Info label="Adres" value={p.address} />
        </div>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <h2>Kartlar</h2>
          {p.credentials.length === 0 ? (
            <Empty>
              Kart atanmamış.{" "}
              {isStaff && <Link to="/kart-ata">Kart ata</Link>}
            </Empty>
          ) : (
            <table>
              <thead>
                <tr><th>Kart No</th><th>Etiket</th><th>Durum</th>{isStaff && <th />}</tr>
              </thead>
              <tbody>
                {p.credentials.map((c) => {
                  const s = CRED_STATUS[c.status] ?? { text: c.status, cls: "muted" };
                  return (
                    <tr key={c.id}>
                      <td className="mono">{c.identifier}</td>
                      <td className="muted">{c.label ?? "—"}</td>
                      <td><span className={`badge ${s.cls}`}>{s.text}</span></td>
                      {isStaff && (
                        <td className="right">
                          {c.status === "active" ? (
                            <button className="ghost"
                                    onClick={() => setCredStatus(c.id, "lost")}>
                              Kayıp bildir
                            </button>
                          ) : (
                            <button className="ghost"
                                    onClick={() => setCredStatus(c.id, "active")}>
                              Geri aç
                            </button>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        <div className="card">
          <div className="row" style={{ marginBottom: ".5rem" }}>
            <h2 style={{ margin: 0 }}>Veliler ve acil durum</h2>
            <div className="spacer" />
            {canEditGuardians && !editingGuardian && (
              <button className="ghost" onClick={() => setAddingGuardian(true)}>
                Ekle
              </button>
            )}
          </div>

          {addingGuardian && !editingGuardian && (
            <GuardianForm
              personId={p.id}
              onDone={() => { setAddingGuardian(false); load(); }}
              onCancel={() => setAddingGuardian(false)}
              onError={setError}
            />
          )}

          {editingGuardian && (
            <GuardianForm
              personId={p.id}
              edit={editingGuardian}
              siblingCount={editingGuardian.linked_person_count - 1}
              onDone={() => { setEditingGuardian(null); load(); }}
              onCancel={() => setEditingGuardian(null)}
              onError={setError}
            />
          )}

          {p.guardians.length === 0 ? (
            <Empty>
              {p.is_minor
                ? "18 yaş altı öğrenci için veli tanımlanmamış — bildirim gönderilemez."
                : "Veli tanımlanmamış."}
            </Empty>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Ad Soyad</th><th>Yakınlık</th><th>Telefon</th>
                  <th>Bildirim</th>{canEditGuardians && <th />}
                </tr>
              </thead>
              <tbody>
                {p.guardians.map((g) => (
                  <tr key={g.id}>
                    <td>
                      {g.full_name}
                      {g.is_primary && (
                        <span className="badge muted" style={{ marginLeft: ".4rem" }}>
                          birincil
                        </span>
                      )}
                    </td>
                    <td className="muted">
                      {g.relation === "acil_durum" ? "Acil durum" : g.relation}
                    </td>
                    <td className="mono">{g.phone}</td>
                    <td>
                      <span className={`badge ${g.notify_enabled ? "ok" : "muted"}`}>
                        {g.notify_enabled ? "Açık" : "Kapalı"}
                      </span>
                    </td>
                    {canEditGuardians && (
                      <td className="right">
                        <button className="ghost" onClick={() => {
                          setAddingGuardian(false);
                          setEditingGuardian(g);
                        }}>
                          Düzenle
                        </button>{" "}
                        <button className="ghost" onClick={() => removeGuardian(g.id)}>
                          Kaldır
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {isStudent && (
        <CoachBox personId={p.id} isAdmin={can("super_admin", "kurum_admin")}
                  onError={setError} />
      )}

      <div className="card" style={{ marginTop: "1rem" }}>
        <h2>Son hareketler</h2>
        {p.recent_events.length === 0 ? (
          <Empty>Henüz hareket yok.</Empty>
        ) : (
          <table>
            <thead>
              <tr><th>Zaman</th><th>Kart</th><th>Sonuç</th></tr>
            </thead>
            <tbody>
              {p.recent_events.map((e) => (
                <tr key={e.id}>
                  <td>{formatDateTime(e.effective_ts)}</td>
                  <td className="mono">{e.cred_identifier}</td>
                  <td><DecisionBadge decision={e.decision} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
