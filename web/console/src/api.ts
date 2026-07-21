// Thin API client for the CIP identity-service (M02).
// All calls go through /api which Vite proxies to the backend on :8000.

const BASE = "/api";

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface Membership {
  id: string;
  person_id: string;
  tenant_id: string;
  role: string;
  status: string;
}

export interface Me {
  person_id: string;
  email: string;
  status: string;
  dob_band: string | null;
  display_name: string | null;
  roles: string[];
  memberships: Membership[];
}

export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, unknown> | null;
}

class CipError extends Error {
  code: string;
  details?: Record<string, unknown> | null;
  constructor(err: ApiError) {
    super(err.message);
    this.code = err.code;
    this.details = err.details;
  }
}

function idempotencyKey(): string {
  return crypto.randomUUID();
}

async function request<T>(
  path: string,
  opts: {
    method?: string;
    body?: unknown;
    token?: string | null;
    idempotent?: boolean;
  } = {}
): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (opts.token) headers["Authorization"] = `Bearer ${opts.token}`;
  if (opts.idempotent) headers["Idempotency-Key"] = idempotencyKey();

  const res = await fetch(`${BASE}${path}`, {
    method: opts.method ?? "GET",
    headers,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });

  if (res.status === 204) return undefined as T;

  const text = await res.text();
  const data = text ? JSON.parse(text) : {};

  if (!res.ok) {
    const err: ApiError = data?.error ?? {
      code: `HTTP_${res.status}`,
      message: res.statusText,
    };
    throw new CipError(err);
  }
  return data as T;
}

export interface RegisterResponse {
  person_id: string;
  status: string;
  verification_url_hint: string;
}

export const api = {
  register: (email: string, password: string, dob: string, displayName?: string) =>
    request<RegisterResponse>("/v1/auth/register", {
      method: "POST",
      idempotent: true,
      body: { email, password, dob, display_name: displayName || null },
    }),

  verifyEmail: (token: string) =>
    request<{ person_id: string; status: string }>("/v1/auth/verify-email", {
      method: "POST",
      body: { token },
    }),

  login: (email: string, password: string) =>
    request<TokenResponse>("/v1/auth/login", {
      method: "POST",
      body: { email, password },
    }),

  me: (token: string) => request<Me>("/v1/me", { token }),

  joinTenant: (token: string, tenantId: string, role: string) =>
    request<Membership>("/v1/memberships", {
      method: "POST",
      token,
      idempotent: true,
      body: { tenant_id: tenantId, role },
    }),

  leaveTenant: (token: string, membershipId: string) =>
    request<void>(`/v1/memberships/${membershipId}`, {
      method: "DELETE",
      token,
    }),

  logout: (refreshToken: string) =>
    request<{ revoked_count: number }>("/v1/auth/logout", {
      method: "POST",
      body: { refresh_token: refreshToken },
    }),
};

export { CipError };
