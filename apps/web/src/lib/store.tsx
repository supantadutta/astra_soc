"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, clearTokens, getActiveTenant, getToken, setActiveTenant, setTokens } from "./api";
import type { AccessibleTenant, Me, ModeState } from "./types";

interface AppState {
  me: Me | null;
  mode: ModeState | null;
  loading: boolean;
  tenants: AccessibleTenant[];
  /** Changes whenever the acting tenant changes — use as a React key. */
  tenantKey: string;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshMode: () => Promise<void>;
  switchTenant: (tenantId: string | null) => Promise<void>;
  /** Permission in the tenant the user is currently acting in. */
  can: (perm: string) => boolean;
  /** Permission in the user's HOME tenant (MSSP portfolio features). */
  canHome: (perm: string) => boolean;
}

const Ctx = createContext<AppState | null>(null);

function has(perms: string[] | undefined, perm: string): boolean {
  if (!perms) return false;
  if (perms.includes("*") || perms.includes(perm)) return true;
  return perms.includes(`${perm.split(":")[0]}:*`);
}

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [mode, setMode] = useState<ModeState | null>(null);
  const [tenants, setTenants] = useState<AccessibleTenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [tenantKey, setTenantKey] = useState("home");

  const loadMe = useCallback(async () => {
    if (!getToken()) {
      setLoading(false);
      return;
    }
    try {
      const [meRes, modeRes, tenantRes] = await Promise.all([
        api.get<Me>("/auth/me"),
        api.get<ModeState>("/mode"),
        api.get<{ items: AccessibleTenant[] }>("/tenants").catch(() => ({ items: [] })),
      ]);
      setMe(meRes);
      setMode(modeRes);
      setTenants(tenantRes.items);
      setTenantKey(meRes.tenant_id);
    } catch {
      clearTokens();
      setMe(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadMe();
  }, [loadMe]);

  const login = useCallback(async (email: string, password: string) => {
    const res = await api.post<{ access_token: string; refresh_token: string }>("/auth/login", {
      email,
      password,
    });
    setActiveTenant(null);
    setTokens(res.access_token, res.refresh_token);
    await loadMe();
  }, [loadMe]);

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout"); // revokes the server-side session
    } catch {
      /* already expired — still clear locally */
    }
    clearTokens();
    setMe(null);
    window.location.href = "/login";
  }, []);

  const refreshMode = useCallback(async () => {
    try {
      setMode(await api.get<ModeState>("/mode"));
    } catch {
      /* ignore */
    }
  }, []);

  const switchTenant = useCallback(async (tenantId: string | null) => {
    const home = me?.home_tenant_id;
    setActiveTenant(tenantId && tenantId !== home ? tenantId : null);
    setLoading(true);
    await loadMe();
  }, [loadMe, me?.home_tenant_id]);

  const can = useCallback((perm: string) => has(me?.permissions, perm), [me]);
  const canHome = useCallback(
    (perm: string) => has(me?.home_permissions?.length ? me.home_permissions : me?.permissions, perm),
    [me]
  );

  return (
    <Ctx.Provider
      value={{ me, mode, loading, tenants, tenantKey, login, logout, refreshMode, switchTenant, can, canHome }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function useApp() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useApp must be used within AppProvider");
  return ctx;
}

/** Small SWR-like fetch hook with manual refresh. */
export function useApi<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<{ message: string; status?: number } | null>(null);
  const [loading, setLoading] = useState(!!path);

  const reload = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    setError(null);
    try {
      setData(await api.get<T>(path));
    } catch (e: any) {
      setError({ message: e?.message || "Request failed", status: e?.status });
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);

  return { data, error, loading, reload };
}

const STREAM_EVENTS = [
  "event.ingested", "alert.created", "incident.created", "incident.updated", "agent.started",
  "agent.finished", "action.created", "action.executed", "action.verified", "action.rolled_back",
  "approval.decided", "workflow.started", "workflow.completed", "workflow.failed",
  "workflow.waiting_approval", "notification.created", "demo.reset", "audit.recorded",
];

/**
 * Subscribe to the tenant-isolated live stream. EventSource cannot send an
 * Authorization header, so we first exchange the session for a short-lived
 * (60 s) stream ticket. Tickets are single-connection: on any error we close
 * and reconnect with a fresh ticket, backing off up to 30 s.
 */
export function useEventStream(
  enabled: boolean,
  tenantKey: string,
  onEvent: (ev: any) => void,
  onStatus?: (connected: boolean) => void
) {
  const cb = useRef(onEvent);
  cb.current = onEvent;
  const statusCb = useRef(onStatus);
  statusCb.current = onStatus;

  useEffect(() => {
    if (!enabled) return;
    let es: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    let closed = false;

    const handler = (e: MessageEvent) => {
      try {
        cb.current(JSON.parse(e.data));
      } catch {
        /* ignore malformed frames */
      }
    };

    const connect = async () => {
      if (closed) return;
      try {
        const { ticket } = await api.post<{ ticket: string }>("/stream/ticket");
        if (closed) return;
        es = new EventSource(`/api/v1/stream?ticket=${encodeURIComponent(ticket)}`);
        es.onopen = () => {
          attempt = 0;
          statusCb.current?.(true);
        };
        STREAM_EVENTS.forEach((t) => es!.addEventListener(t, handler as EventListener));
        es.onerror = () => {
          es?.close();
          statusCb.current?.(false);
          schedule();
        };
      } catch {
        statusCb.current?.(false);
        schedule();
      }
    };
    const schedule = () => {
      if (closed) return;
      attempt += 1;
      timer = setTimeout(connect, Math.min(30_000, 1000 * 2 ** Math.min(attempt, 5)));
    };

    connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      es?.close();
    };
  }, [enabled, tenantKey]);
}

export { getActiveTenant };

// --- In-app fan-out of the single live stream owned by the AppShell --------------
type LiveListener = (ev: any) => void;
const liveListeners = new Set<LiveListener>();

export function emitLive(ev: any) {
  liveListeners.forEach((l) => {
    try {
      l(ev);
    } catch {
      /* a failing listener must not break the others */
    }
  });
}

/** Receive live events without opening another connection. */
export function useLiveEvents(onEvent: LiveListener) {
  const ref = useRef(onEvent);
  ref.current = onEvent;
  useEffect(() => {
    const l: LiveListener = (ev) => ref.current(ev);
    liveListeners.add(l);
    return () => {
      liveListeners.delete(l);
    };
  }, []);
}
