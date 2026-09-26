"use client";

/**
 * Typed API client. Talks to the FastAPI backend through the same-origin
 * `/api/*` proxy route. RBAC and tenant isolation are enforced server-side;
 * a 403 here means the backend declined, and the UI surfaces that truthfully.
 *
 * Session: the browser holds HttpOnly cookies set by the API, so page
 * JavaScript never sees an access or refresh token. State-changing requests
 * echo the readable CSRF cookie in `X-CSRF-Token` (double-submit).
 *
 * MSSP tenant context: when the user switches into a customer tenant, every
 * request carries `X-Tenant-ID`. The backend re-evaluates delegated access on
 * each request, so revoking a grant takes effect immediately.
 *
 * Refresh tokens rotate and replaying a superseded one revokes the session
 * (theft detection), so refreshes are serialised: within this tab through a
 * shared promise, across tabs through the Web Locks API plus a timestamp other
 * tabs can see.
 */

export interface ApiError {
  status: number;
  error: string;
  message: string;
  detail?: unknown;
  request_id?: string;
}

const TENANT_KEY = "astrasoc.tenant";
const REFRESHED_AT_KEY = "astrasoc.refreshedAt";
const FLASH_KEY = "astrasoc.flash";
const CSRF_COOKIE = "astrasoc_csrf";
const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

function store(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const hit = document.cookie.split("; ").find((c) => c.startsWith(name + "="));
  return hit ? decodeURIComponent(hit.slice(name.length + 1)) : null;
}

/** Forget client-side session state (the cookies are cleared by /auth/logout). */
export function clearLocalSession() {
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

/** One-shot message shown by the shell after a redirect. */
export function setFlash(message: string) {
  try {
    sessionStorage.setItem(FLASH_KEY, message);
  } catch {
    /* ignore */
  }
}
export function takeFlash(): string | null {
  try {
    const m = sessionStorage.getItem(FLASH_KEY);
    sessionStorage.removeItem(FLASH_KEY);
    return m;
  } catch {
    return null;
  }
}

function buildHeaders(method: string, extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = { ...(extra || {}) };
  const tenant = getActiveTenant();
  if (tenant) headers["X-Tenant-ID"] = tenant;
  if (UNSAFE.has(method)) {
    const csrf = readCookie(CSRF_COOKIE);
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
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

const PUBLIC_AUTH = ["/auth/login", "/auth/login/mfa", "/auth/login-options", "/auth/mfa/setup", "/auth/mfa/enable"];

async function send(method: string, path: string, body: unknown, retry: boolean): Promise<Response> {
  const startedAt = Date.now();
  const res = await fetch(`/api/v1${path}`, {
    method,
    headers: buildHeaders(method, body !== undefined ? { "Content-Type": "application/json" } : undefined),
    body: body !== undefined ? JSON.stringify(body) : undefined,
    cache: "no-store",
    credentials: "same-origin",
  });
  if (res.status === 401 && retry && typeof window !== "undefined" && !PUBLIC_AUTH.includes(path)) {
    if (await refreshSession(startedAt)) return send(method, path, body, false);
    clearLocalSession();
    if (!window.location.pathname.startsWith("/login")) window.location.href = "/login";
  }
  if (res.status === 403 && typeof window !== "undefined") {
    let code = "";
    try {
      const p = await res.clone().json();
      code = p?.detail?.error || p?.error || "";
    } catch {
      /* ignore */
    }
    if (code === "mfa_required") {
      // The organization now requires MFA and this session predates it.
      await fetch("/api/v1/auth/logout", { method: "POST", headers: buildHeaders("POST"), credentials: "same-origin" }).catch(() => undefined);
      clearLocalSession();
      window.location.href = "/login?reason=mfa_required";
    } else if ((code === "tenant_access_denied" || code === "mfa_required_by_tenant") && getActiveTenant()) {
      // The acting tenant was switched off, access revoked, or it requires MFA.
      setActiveTenant(null);
      if (code === "mfa_required_by_tenant") {
        setFlash("That customer requires multi-factor authentication. Enable MFA in My Account, then sign in again with it.");
      }
      window.location.href = "/mssp";
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

/** Refresh once for everyone waiting. If another tab refreshed after our
 * request started, its new cookies are already ours: just retry. */
function refreshSession(startedAt: number): Promise<boolean> {
  if (!inflight) {
    const run = async () => {
      if (Number(store()?.getItem(REFRESHED_AT_KEY) || 0) > startedAt) return true;
      // The CSRF cookie is set and cleared together with the refresh cookie,
      // and a cookie refresh without it is refused. Without it there is no
      // session to refresh, so don't spend the per-IP sign-in rate limit.
      if (!readCookie(CSRF_COOKIE)) return false;
      try {
        const res = await fetch(`/api/v1/auth/refresh`, {
          method: "POST",
          headers: buildHeaders("POST"),
          credentials: "same-origin",
        });
        if (!res.ok) return false;
        store()?.setItem(REFRESHED_AT_KEY, String(Date.now()));
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
