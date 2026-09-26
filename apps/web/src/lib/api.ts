"use client";

/**
 * Typed API client. Talks to the FastAPI backend through the same-origin
 * `/api/*` proxy route. RBAC and tenant isolation are enforced server-side;
 * a 403 here means the backend declined, and the UI surfaces that truthfully.
 *
 * MSSP tenant context: when the user switches into a customer tenant, every
 * request carries `X-Tenant-ID`. The backend re-evaluates delegated access on
 * each request, so revoking a grant takes effect immediately.
 *
 * Refresh tokens rotate and replaying a superseded one revokes the session
 * (theft detection), so refreshes are serialised — within this tab through a
 * shared promise and across tabs through the Web Locks API.
 */

export interface ApiError {
  status: number;
  error: string;
  message: string;
  detail?: unknown;
  request_id?: string;
}

const TOKEN_KEY = "astrasoc.access";
const REFRESH_KEY = "astrasoc.refresh";
const TENANT_KEY = "astrasoc.tenant";

function store(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

export function getToken(): string | null {
  return store()?.getItem(TOKEN_KEY) ?? null;
}
export function setTokens(access: string, refresh: string) {
  store()?.setItem(TOKEN_KEY, access);
  store()?.setItem(REFRESH_KEY, refresh);
}
export function clearTokens() {
  store()?.removeItem(TOKEN_KEY);
  store()?.removeItem(REFRESH_KEY);
  store()?.removeItem(TENANT_KEY);
}

/** Tenant the user is acting in (null = their home tenant). */
export function getActiveTenant(): string | null {
  return store()?.getItem(TENANT_KEY) ?? null;
}
export function setActiveTenant(tenantId: string | null) {
  if (tenantId) store()?.setItem(TENANT_KEY, tenantId);
  else store()?.removeItem(TENANT_KEY);
}

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = { ...(extra || {}) };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const tenant = getActiveTenant();
  if (tenant) headers["X-Tenant-ID"] = tenant;
  return headers;
}

async function toError(res: Response): Promise<ApiError> {
  let payload: Record<string, any> = {};
  try {
    payload = await res.json();
  } catch {
    /* non-JSON error */
  }
  // FastAPI HTTPException wraps structured errors in `detail`.
  const d = payload.detail;
  const nested = d && typeof d === "object" && !Array.isArray(d) ? d : null;
  let message = payload.message || nested?.message || (typeof d === "string" ? d : "") || res.statusText;
  if (Array.isArray(d) && d.length && d[0]?.msg) {
    message = d.map((e: any) => `${(e.loc || []).slice(1).join(".")}: ${e.msg}`).join("; ");
  }
  return {
    status: res.status,
    error: payload.error || nested?.error || "error",
    message,
    detail: d,
    request_id: payload.request_id,
  };
}

async function send(method: string, path: string, body: unknown, retry: boolean): Promise<Response> {
  const usedToken = getToken();
  const res = await fetch(`/api/v1${path}`, {
    method,
    headers: authHeaders(body !== undefined ? { "Content-Type": "application/json" } : undefined),
    body: body !== undefined ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  if (res.status === 401 && retry && typeof window !== "undefined" && !path.startsWith("/auth/login")) {
    if (await refreshSession(usedToken)) return send(method, path, body, false);
    clearTokens();
    if (!window.location.pathname.startsWith("/login")) window.location.href = "/login";
  }
  // The acting tenant was switched off or access revoked: fall back home.
  if (res.status === 403 && getActiveTenant()) {
    const clone = res.clone();
    try {
      const p = await clone.json();
      if ((p?.detail?.error || p?.error) === "tenant_access_denied") {
        setActiveTenant(null);
        window.location.href = "/dashboard";
      }
    } catch {
      /* ignore */
    }
  }
  return res;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await send(method, path, body, true);
  if (!res.ok) throw await toError(res);
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return text ? (JSON.parse(text) as T) : (undefined as T);
}

let inflight: Promise<boolean> | null = null;

/** Refresh once for everyone waiting. `staleToken` is the access token the
 * failed request used: if another tab already rotated it, just retry. */
function refreshSession(staleToken: string | null): Promise<boolean> {
  if (!inflight) {
    const run = async () => {
      if (getToken() && getToken() !== staleToken) return true;
      const refresh = store()?.getItem(REFRESH_KEY);
      if (!refresh) return false;
      try {
        const res = await fetch(`/api/v1/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refresh }),
        });
        if (!res.ok) return false;
        const data = await res.json();
        setTokens(data.access_token, data.refresh_token);
        return true;
      } catch {
        return false;
      }
    };
    const locks = typeof navigator !== "undefined" ? (navigator as any).locks : undefined;
    inflight = (locks ? locks.request("astrasoc-refresh", run) : run()).finally(() => {
      inflight = null;
    });
  }
  return inflight as Promise<boolean>;
}

export const api = {
  get: <T,>(path: string) => request<T>("GET", path),
  post: <T,>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  put: <T,>(path: string, body?: unknown) => request<T>("PUT", path, body ?? {}),
  patch: <T,>(path: string, body?: unknown) => request<T>("PATCH", path, body ?? {}),
  del: <T,>(path: string, body?: unknown) => request<T>("DELETE", path, body),
};

/** Authenticated file download (exports, CSV, report bundles). */
export async function download(path: string, fallbackName: string): Promise<void> {
  const res = await send("GET", path, undefined, true);
  if (!res.ok) throw await toError(res);
  const disposition = res.headers.get("content-disposition") || "";
  const match = /filename="?([^";]+)"?/i.exec(disposition);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = match?.[1] || fallbackName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Save an in-memory JSON value as a file. */
export function saveJson(value: unknown, filename: string) {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function errorMessage(e: unknown): string {
  const err = e as Partial<ApiError> | undefined;
  return err?.message || "Request failed";
}

export function qs(params: Record<string, string | number | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}
