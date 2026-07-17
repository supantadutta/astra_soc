"use client";

/**
 * Typed API client. Talks to the FastAPI backend through the Next.js rewrite
 * (`/api/*`). The access token is kept in memory + localStorage and refreshed
 * automatically. RBAC is enforced server-side; a 403 here means the backend
 * declined, and the UI surfaces that truthfully.
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

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}
export function setTokens(access: string, refresh: string) {
  localStorage.setItem(TOKEN_KEY, access);
  localStorage.setItem(REFRESH_KEY, refresh);
}
export function clearTokens() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  retry = true
): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`/api/v1${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });

  if (res.status === 401 && retry && typeof window !== "undefined") {
    const refreshed = await tryRefresh();
    if (refreshed) return request<T>(method, path, body, false);
    clearTokens();
    if (!path.startsWith("/auth")) window.location.href = "/login";
  }

  if (!res.ok) {
    let payload: Record<string, unknown> = {};
    try {
      payload = await res.json();
    } catch {
      /* non-JSON error */
    }
    const err: ApiError = {
      status: res.status,
      error: (payload.error as string) || "error",
      message: (payload.message as string) || res.statusText,
      detail: payload.detail,
      request_id: payload.request_id as string,
    };
    throw err;
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return text ? (JSON.parse(text) as T) : (undefined as T);
}

async function tryRefresh(): Promise<boolean> {
  const refresh = localStorage.getItem(REFRESH_KEY);
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
}

export const api = {
  get: <T,>(path: string) => request<T>("GET", path),
  post: <T,>(path: string, body?: unknown) => request<T>("POST", path, body),
  put: <T,>(path: string, body?: unknown) => request<T>("PUT", path, body),
  patch: <T,>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  del: <T,>(path: string) => request<T>("DELETE", path),
};

export function qs(params: Record<string, string | number | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}
