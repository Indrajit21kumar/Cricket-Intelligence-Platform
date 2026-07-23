// Session store — holds the auth tokens + the resolved player identity and
// active tenant, and keeps the api client's auth header in sync. Persisted to
// localStorage so a refresh keeps you signed in.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, setAuth, type Me } from "./api";

interface Tokens {
  accessToken: string;
  refreshToken: string;
}

interface SessionState {
  tokens: Tokens | null;
  me: Me | null;
  tenantId: string | null; // active academy for tenant-scoped (M05) calls
  loading: boolean;
}

interface SessionApi extends SessionState {
  signIn: (tokens: Tokens) => Promise<void>;
  signOut: () => void;
  setTenant: (tenantId: string) => void;
  refreshMe: () => Promise<void>;
}

const KEY = "cip_session_v2";
const SessionContext = createContext<SessionApi | null>(null);

function load(): { tokens: Tokens | null; tenantId: string | null } {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? JSON.parse(raw) : { tokens: null, tenantId: null };
  } catch {
    return { tokens: null, tenantId: null };
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const initial = load();
  const [tokens, setTokens] = useState<Tokens | null>(initial.tokens);
  const [tenantId, setTenantId] = useState<string | null>(initial.tenantId);
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState<boolean>(!!initial.tokens);

  // Keep the api client + localStorage in sync with the token/tenant.
  useEffect(() => {
    setAuth(tokens?.accessToken ?? null, tenantId);
    localStorage.setItem(KEY, JSON.stringify({ tokens, tenantId }));
  }, [tokens, tenantId]);

  const refreshMe = useCallback(async () => {
    if (!tokens) return;
    setLoading(true);
    try {
      const m = await api.me();
      setMe(m);
      // Default the active tenant to the first active membership.
      setTenantId((cur) => cur ?? m.memberships.find((x) => x.status === "active")?.tenant_id ?? null);
    } finally {
      setLoading(false);
    }
  }, [tokens]);

  useEffect(() => {
    if (tokens) void refreshMe();
    else setMe(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tokens]);

  const signIn = useCallback(async (t: Tokens) => {
    setTokens(t);
  }, []);

  const signOut = useCallback(() => {
    if (tokens) api.logout(tokens.refreshToken).catch(() => {});
    setTokens(null);
    setTenantId(null);
    setMe(null);
    localStorage.removeItem(KEY);
  }, [tokens]);

  const value = useMemo<SessionApi>(
    () => ({ tokens, me, tenantId, loading, signIn, signOut, setTenant: setTenantId, refreshMe }),
    [tokens, me, tenantId, loading, signIn, signOut, refreshMe]
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionApi {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used within SessionProvider");
  return ctx;
}
