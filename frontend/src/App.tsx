/** NÖBET — Uygulama kabuğu ve yönlendirme */
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { ADMIN_ROLES, ROLE_LABEL, STAFF_ROLES, useAuth } from "./auth";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Persons from "./pages/Persons";
import PersonDetail from "./pages/PersonDetail";
import Enroll from "./pages/Enroll";
import Sessions from "./pages/Sessions";
import Notifications from "./pages/Notifications";
import Chat from "./pages/Chat";
import Settings from "./pages/Settings";
import Reports from "./pages/Reports";
import MyStudents from "./pages/MyStudents";
import Classroom from "./pages/Classroom";
import ManualEntry from "./pages/ManualEntry";
import Tenants from "./pages/Tenants";
import Nodes from "./pages/Nodes";
import Users from "./pages/Users";
import SetPassword from "./pages/SetPassword";
import Account from "./pages/Account";

function Shell() {
  const { user, signOut, can } = useAuth();
  if (!user) return null;

  const isStaff = can(...STAFF_ROLES);
  const isAdmin = can(...ADMIN_ROLES);
  // Faz 13b: kurum/abonelik konsolu YALNIZCA super_admin.
  const isSuper = user.role === "super_admin";
  const isCoach = user.role === "coach";

  return (
    <div className="shell">
      <nav className="sidebar">
        <div className="brand">NÖBET</div>
        <div className="nav">
          <NavLink to="/" end>Panel</NavLink>
          {isCoach && <NavLink to="/ogrencilerim">Öğrencilerim</NavLink>}
          <NavLink to="/kisiler">Kişiler</NavLink>
          <NavLink to="/oturumlar">Oturumlar</NavLink>
          {isStaff && <NavLink to="/yoklama">Yoklama</NavLink>}
          {isStaff && <NavLink to="/elle-giris">Elle Giriş</NavLink>}
          <NavLink to="/raporlar">Raporlar</NavLink>
          {isStaff && <NavLink to="/whatsapp">WhatsApp</NavLink>}
          {isStaff && <NavLink to="/bildirimler">Bildirimler</NavLink>}
          {isStaff && <NavLink to="/kart-ata">Kart Ata</NavLink>}
          {isStaff && <NavLink to="/okuyucular">Donanım</NavLink>}
          {isAdmin && <NavLink to="/kullanicilar">Kullanıcılar</NavLink>}
          {isAdmin && <NavLink to="/ayarlar">Ayarlar</NavLink>}
          {isSuper && <NavLink to="/kurumlar">Kurumlar</NavLink>}
        </div>
        <div className="sidebar-foot">
          <NavLink to="/hesabim" className="who">{user.email}</NavLink>
          <div className="role">{ROLE_LABEL[user.role]}</div>
          <button
            className="ghost"
            onClick={signOut}
            style={{ marginTop: ".6rem", width: "100%" }}
          >
            Çıkış
          </button>
        </div>
      </nav>

      <main className="main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/kisiler" element={<Persons />} />
          <Route path="/kisiler/:id" element={<PersonDetail />} />
          <Route path="/oturumlar" element={<Sessions />} />
          <Route path="/raporlar" element={<Reports />} />
          <Route path="/hesabim" element={<Account />} />
          {isStaff && <Route path="/yoklama" element={<Classroom />} />}
          {isStaff && <Route path="/elle-giris" element={<ManualEntry />} />}
          {isCoach && <Route path="/ogrencilerim" element={<MyStudents />} />}
          {isStaff && <Route path="/whatsapp" element={<Chat />} />}
          {isStaff && <Route path="/bildirimler" element={<Notifications />} />}
          {isStaff && <Route path="/kart-ata" element={<Enroll />} />}
          {isStaff && <Route path="/okuyucular" element={<Nodes />} />}
          {isAdmin && <Route path="/kullanicilar" element={<Users />} />}
          {isAdmin && <Route path="/ayarlar" element={<Settings />} />}
          {isSuper && <Route path="/kurumlar" element={<Tenants />} />}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  const { user, loading } = useAuth();

  // ⚠️ Oturum kontrolünden ÖNCE. Kullanıcı buraya giriş yapamadığı için
  // geliyor; `loading`/`user` durumuna bakmak onu giriş ekranına düşürürdü.
  if (window.location.pathname === "/parola-belirle") return <SetPassword />;

  if (loading) {
    return (
      <div className="login-wrap">
        <div className="card login-card" style={{ textAlign: "center" }}>
          Yükleniyor…
        </div>
      </div>
    );
  }

  return user ? <Shell /> : <Login />;
}
