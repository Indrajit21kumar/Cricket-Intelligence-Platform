// Typed API client for the CIP services the console talks to today:
//   identity-service (M02) — auth, /v1/me, memberships
//   profile-service  (M04) — profile attributes, Cricket DNA, baseline, progress
//   video-service    (M05) — upload, capture guidance, quality result
//   pose-service     (M06) — the pose run for an analysed clip
// Calls go through same-origin /api/<svc>/* which Vite proxies per service.
//
// M04 is person-anchored (Bearer only — the JWT subject is the player).
// M05/M06 are tenant-scoped (Bearer + X-Tenant-ID). The client holds the
// session token + the active tenant, set after login.

export interface ApiErrorBody {
  code: string;
  message: string;
  details?: Record<string, unknown> | null;
}

export class CipError extends Error {
  code: string;
  status: number;
  details?: Record<string, unknown> | null;
  constructor(err: ApiErrorBody, status: number) {
    super(err.message);
    this.code = err.code;
    this.status = status;
    this.details = err.details;
  }
}

let _token: string | null = null;
let _tenantId: string | null = null;

export function setAuth(token: string | null, tenantId: string | null) {
  _token = token;
  _tenantId = tenantId;
}

function uuid(): string {
  return crypto.randomUUID();
}

type Svc = "identity" | "profile" | "video" | "pose";

async function request<T>(
  svc: Svc,
  path: string,
  opts: {
    method?: string;
    body?: unknown;
    tenant?: boolean; // send X-Tenant-ID
    idempotent?: boolean; // send Idempotency-Key
    correlationId?: string;
    auth?: boolean; // send Bearer (default true)
  } = {}
): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (opts.auth !== false && _token) headers["Authorization"] = `Bearer ${_token}`;
  if (opts.tenant && _tenantId) headers["X-Tenant-ID"] = _tenantId;
  if (opts.idempotent) headers["Idempotency-Key"] = uuid();
  if (opts.correlationId) headers["X-Correlation-ID"] = opts.correlationId;

  const res = await fetch(`/api/${svc}${path}`, {
    method: opts.method ?? "GET",
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });

  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const data = text ? JSON.parse(text) : {};
  if (!res.ok) {
    const err: ApiErrorBody = data?.error ?? { code: `HTTP_${res.status}`, message: res.statusText };
    throw new CipError(err, res.status);
  }
  return data as T;
}

// Raw byte upload — separate from `request` because the body is the file
// itself, not JSON.
//
// A real cloud backend hands back a presigned `upload_url` pointing at the
// bucket, and the client PUTs straight there. The local-filesystem backend
// points `upload_url` back at video-service's own API, which is a different
// origin from the dev server — so we PUT to the same-origin proxied path
// instead and let Vite forward it. Same route, no CORS preflight.
async function uploadBytes(svc: Svc, path: string, file: File): Promise<RawUploadResponse> {
  const headers: Record<string, string> = { "Content-Type": file.type || "application/octet-stream" };
  if (_token) headers["Authorization"] = `Bearer ${_token}`;
  if (_tenantId) headers["X-Tenant-ID"] = _tenantId;

  const res = await fetch(`/api/${svc}${path}`, { method: "PUT", headers, body: file });
  const text = await res.text();
  const data = text ? JSON.parse(text) : {};
  if (!res.ok) {
    const err: ApiErrorBody = data?.error ?? { code: `HTTP_${res.status}`, message: res.statusText };
    throw new CipError(err, res.status);
  }
  return data as RawUploadResponse;
}

// --- M02 identity ------------------------------------------------------------
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

// --- M04 profile -------------------------------------------------------------
export interface Profile {
  id: string;
  person_id: string;
  height_cm: number | null;
  stance: string | null;
  age_band: string | null;
  dominant_hand: string | null;
}
export type Provenance = "measured" | "estimated" | "modelled";
export interface DnaTrait {
  trait_key: string;
  value: string;
  confidence: number | null;
  provenance: Provenance;
  source_ref?: string | null;
  updated_at?: string | null;
}
export interface TrendPoint {
  period_start: string;
  value: string;
  confidence: number | null;
}

// --- M05 video ---------------------------------------------------------------
export interface CreateVideoResponse {
  ingestion_id: string;
  correlation_id: string;
  raw_ref: string;
  upload_url: string;
  expires_in: number;
  status: string;
}
export interface QualityFlag {
  code: string;
  severity: "fail" | "flag";
  message: string;
}
export interface CompleteResponse {
  ingestion_id: string;
  status: string;
  normalized_ref: string;
  frame_count: number;
  fps: number;
  camera_angle: string;
  angle_supported: boolean;
  angle_recommendation: string | null;
  pixel_to_meter: number | null;
  spatial_confidence: string;
  depth_estimated: boolean;
  calibration_method: string;
  admitted: boolean;
  flags: QualityFlag[];
  usage_recorded?: boolean;
}
export interface QualityResult {
  ingestion_id: string;
  status: string;
  admitted: boolean;
  flags: QualityFlag[];
}
export interface CaptureGuidance {
  thresholds: Record<string, unknown>;
}
export interface RawUploadResponse {
  ingestion_id: string;
  bytes_received: number;
}

// --- M06 pose ----------------------------------------------------------------
export interface PoseRun {
  correlation_id: string;
  person_id: string | null;
  model_version: string;
  frame_count: number;
  mean_confidence: number | null;
  subject_status: string; // tracked | multi_subject_ambiguous | no_subject
  quality: string; // ok | provisional | rejected
  rejection_code: string | null;
  artefact_ref: string | null;
  depth_estimated: boolean;
  created_at: string;
}

export const api = {
  // M02
  register: (email: string, password: string, dob: string, displayName?: string) =>
    request<{ person_id: string; status: string; verification_url_hint: string }>(
      "identity",
      "/v1/auth/register",
      { method: "POST", idempotent: true, auth: false, body: { email, password, dob, display_name: displayName || null } }
    ),
  verifyEmail: (token: string) =>
    request<{ person_id: string; status: string }>("identity", "/v1/auth/verify-email", {
      method: "POST",
      auth: false,
      body: { token },
    }),
  login: (email: string, password: string) =>
    request<TokenResponse>("identity", "/v1/auth/login", { method: "POST", auth: false, body: { email, password } }),
  me: () => request<Me>("identity", "/v1/me"),
  joinTenant: (tenantId: string, role: string) =>
    request<Membership>("identity", "/v1/memberships", { method: "POST", idempotent: true, body: { tenant_id: tenantId, role } }),
  logout: (refreshToken: string) =>
    request<{ revoked_count: number }>("identity", "/v1/auth/logout", { method: "POST", auth: false, body: { refresh_token: refreshToken } }),

  // M04 (person-anchored — Bearer only)
  getProfile: (personId: string) => request<Profile>("profile", `/v1/players/${personId}/profile`),
  createProfile: (personId: string, attrs: Partial<Profile>) =>
    request<Profile>("profile", `/v1/players/${personId}/profile`, { method: "POST", body: attrs }),
  patchProfile: (personId: string, attrs: Partial<Profile>) =>
    request<Profile>("profile", `/v1/players/${personId}/profile`, { method: "PATCH", body: attrs }),
  getDna: (personId: string) => request<DnaTrait[]>("profile", `/v1/players/${personId}/dna`),
  getProgress: (personId: string, traitKey: string, period = "monthly") =>
    request<TrendPoint[]>("profile", `/v1/players/${personId}/progress?trait_key=${encodeURIComponent(traitKey)}&period=${period}`),

  // M05 (tenant-scoped — Bearer + X-Tenant-ID)
  captureGuidance: () => request<CaptureGuidance>("video", "/v1/capture-guidance", { tenant: true }),
  createVideo: (body: { person_id: string; source_type: string; content_type: string; size_bytes?: number }, correlationId: string) =>
    request<CreateVideoResponse>("video", "/v1/videos", { method: "POST", tenant: true, correlationId, body }),
  uploadRaw: (ingestionId: string, file: File) =>
    uploadBytes("video", `/v1/videos/${ingestionId}/raw`, file),
  completeVideo: (ingestionId: string) =>
    request<CompleteResponse>("video", `/v1/videos/${ingestionId}/complete`, { method: "POST", tenant: true }),
  getQuality: (ingestionId: string) =>
    request<QualityResult>("video", `/v1/videos/${ingestionId}/quality`, { tenant: true }),

  // M06 (tenant-scoped). The pose run is produced asynchronously by the
  // pose worker consuming `video.normalized`, so callers poll for it.
  getPose: (correlationId: string) =>
    request<PoseRun>("pose", `/v1/pose/${encodeURIComponent(correlationId)}`, { tenant: true }),
};
