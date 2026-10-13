/** NÖBET — Oturum bağlamı (kontrat §3.1, §1.3) */
import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
  type ReactNode,
} from "react";
import {
  clearTokens, login as apiLogin, restoreSession, setUnauthorizedHandler,
  api, type Role, type TenantChoice, type User,
} from "./api";

interface AuthState {
  user: User | null;
  loading: boolean;
  /** Kurum seçimi gerekiyorsa seçenekleri döndürür, aksi hâlde `null`. */
  signIn: (
    email: string, password: string, tenantId?: string,
  ) => Promise<TenantChoice[] | null>;
  signOut: () => void;
  can: (...roles: Role[]) => boolean;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // Sayfa yenilendiğinde refresh token ile oturumu geri kur
  useEffect(() => {
    let alive = true;
    restoreSession()
      .then((u) => alive && setUser(u))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, []);

  // Token yenilenemezse istemci bizi buraya düşürür
  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null));
  }, []);

  /**
   * Giriş. Kullanıcı birden fazla kuruma üyeyse sunucu seçenek listesi
   * döndürür; o durumda oturum AÇILMAZ ve seçenekler çağırana verilir
   * (Faz 13a-0). Seçim yapılınca aynı işlev `tenantId` ile çağrılır.
   */
  const signIn = useCallback(
    async (email: string, password: string, tenantId?: string) => {
      const res = await apiLogin(email, password, tenantId);
      if (res.kind === "choose") return res.choices;
      setUser(res.user);
      return null;
    },
    [],
  );

  const signOut = useCallback(() => {
    // Sunucu tarafı durumsuz; yine de logout'u bildir, hata olursa yut.
    api.post("/auth/logout").catch(() => {});
    clearTokens();
    setUser(null);
  }, []);

  const can = useCallback(
    (...roles: Role[]) => (user ? roles.includes(user.role) : false),
    [user],
  );

  const value = useMemo(
    () => ({ user, loading, signIn, signOut, can }),
    [user, loading, signIn, signOut, can],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth, AuthProvider içinde kullanılmalı");
  return ctx;
}

/** Kontrat §1.3 — kişi/kart işlemleri operator ve üstü */
export const STAFF_ROLES: Role[] = ["super_admin", "kurum_admin", "operator"];
export const ADMIN_ROLES: Role[] = ["super_admin", "kurum_admin"];

export const ROLE_LABEL: Record<Role, string> = {
  super_admin: "Sistem Yöneticisi",
  kurum_admin: "Kurum Yöneticisi",
  operator: "Operatör",
  coach: "Koç",
};
