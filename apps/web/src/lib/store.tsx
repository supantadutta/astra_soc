"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, clearTokens, getToken, setTokens } from "./api";
import type { Me, ModeState } from "./types";

interface AppState {
  me: Me | null;
  mode: ModeState | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  refreshMode: () => Promise<void>;
  can: (perm: string) => boolean;
}

const Ctx = createContext<AppState | null>(null);

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [mode, setMode] = useState<ModeState | null>(null);
  const [loading, setLoading] = useState(true);

  const loadMe = useCallback(async () => {
    if (!getToken()) {
      setLoading(false);
      return;
    }
    try {
      const [meRes, modeRes] = await Promise.all([
        api.get<Me>("/auth/me"),
        api.get<ModeState>("/mode"),
      ]);
      setMe(meRes);
      setMode(modeRes);
    } catch {
      clearTokens();
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
    setTokens(res.access_token, res.refresh_token);
    await loadMe();
  }, [loadMe]);

  const logout = useCallback(() => {
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

  const can = useCallback(
    (perm: string) => {
      if (!me) return false;
      if (me.permissions.includes("*")) return true;
      if (me.permissions.includes(perm)) return true;
      const resource = perm.split(":")[0];
      return me.permissions.includes(`${resource}:*`);
    },
    [me]
  );

  return (
    <Ctx.Provider value={{ me, mode, loading, login, logout, refreshMode, can }}>
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
  const [error, setError] = useState<{ message: string } | null>(null);
  const [loading, setLoading] = useState(!!path);

  const reload = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    setError(null);
    try {
      setData(await api.get<T>(path));
    } catch (e: any) {
      setError({ message: e?.message || "Request failed" });
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path]);

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);

  return { data, error, loading, reload };
}

/** Subscribe to the backend SSE stream for the given scope. */
export function useEventStream(
  scope: string | undefined,
  onEvent: (ev: any) => void
) {
  const cb = useRef(onEvent);
  cb.current = onEvent;
  useEffect(() => {
    if (!scope) return;
    const es = new EventSource(`/api/v1/stream?scope=${scope}`);
    const handler = (e: MessageEvent) => {
      try {
        cb.current(JSON.parse(e.data));
      } catch {
        /* ignore */
      }
    };
    const types = [
      "event.ingested", "alert.created", "incident.created", "agent.started",
      "agent.finished", "action.created", "action.executed", "action.verified",
      "approval.decided", "workflow.started", "workflow.completed",
      "workflow.waiting_approval", "demo.reset", "audit.recorded",
    ];
    types.forEach((t) => es.addEventListener(t, handler as EventListener));
    es.onerror = () => { /* browser auto-reconnects */ };
    return () => es.close();
  }, [scope]);
}
