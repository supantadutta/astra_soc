"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import * as Icons from "lucide-react";
import {
  Bell, Building2, Check, ChevronDown, ChevronLeft, Command, Home, LogOut, Maximize2, Menu, Radio,
  Search, ShieldAlert, Sparkles, X, Zap,
} from "lucide-react";
import { api, takeFlash } from "@/lib/api";
import { NAV, NAV_GROUPS } from "@/lib/nav";
import { emitLive, useApp, useEventStream } from "@/lib/store";
import type { AccessibleTenant, Notification } from "@/lib/types";
import { cx, timeAgo, titleCase } from "@/lib/ui";
import { CommandPalette } from "./CommandPalette";
import { Loading } from "./ui";

export function AppShell({ children }: { children: React.ReactNode }) {
  const { me, mode, loading, logout, can, canHome, tenantKey } = useApp();
  const router = useRouter();
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [reduceMotion, setReduceMotion] = useState(false);
  const [connected, setConnected] = useState(false);
  const [pulse, setPulse] = useState(0);
  const [notifTick, setNotifTick] = useState(0);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [flash, setFlashState] = useState<string | null>(null);

  useEffect(() => { setFlashState(takeFlash()); }, []);

  useEffect(() => {
    if (!loading && !me) router.replace("/login");
  }, [loading, me, router]);

  // The mobile drawer closes on navigation and on Escape.
  useEffect(() => { setDrawerOpen(false); }, [pathname]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setDrawerOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute("data-reduce-motion", String(reduceMotion));
  }, [reduceMotion]);

  useEventStream(!!me, tenantKey, (ev) => {
    setPulse((p) => (p + 1) % 100000);
    if (ev.type === "notification.created") setNotifTick((t) => t + 1);
    emitLive(ev);
  }, setConnected);

  if (loading) return <div className="min-h-screen flex items-center justify-center"><Loading label="Initializing command center…" /></div>;
  if (!me) return null;

  const items = NAV.filter((n) =>
    (!n.permission || can(n.permission)) && (!n.homePermission || canHome(n.homePermission)));

  const brand = (compact: boolean) => (
    <div className="flex items-center gap-2 px-4 h-14 border-b border-white/5 shrink-0">
      <div className="w-8 h-8 rounded-lg bg-navy-800 border border-cyan/40 flex items-center justify-center shadow-glow shrink-0">
        <Sparkles className="w-4 h-4 text-cyan" />
      </div>
      {!compact && (
        <div className="leading-tight min-w-0">
          <div className="text-sm font-bold text-ink-100 tracking-wide">ASTRASOC</div>
          <div className="text-[10px] text-ink-500 uppercase tracking-wider truncate">
            {me.tenant_kind === "customer" ? "Managed Security" : "MSSP Command Center"}
          </div>
        </div>
      )}
    </div>
  );

  const navList = (compact: boolean) => (
    <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-4" aria-label="Primary">
      {NAV_GROUPS.map((group) => {
        const groupItems = items.filter((i) => i.group === group);
        if (!groupItems.length) return null;
        return (
          <div key={group}>
            {!compact && <div className="label px-2 mb-1">{group}</div>}
            <div className="space-y-0.5">
              {groupItems.map((item) => {
                const Icon = (Icons[item.icon] || Icons.Circle) as any;
                const activeRoute = item.href === "/mssp"
                  ? pathname === "/mssp"
                  : pathname === item.href || pathname.startsWith(item.href + "/");
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    title={item.label}
                    aria-current={activeRoute ? "page" : undefined}
                    className={cx(
                      "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors",
                      activeRoute
                        ? "bg-cyan/10 text-cyan border border-cyan/20"
                        : "text-ink-300 hover:bg-white/5 hover:text-ink-100 border border-transparent"
                    )}
                  >
                    <Icon className="w-4 h-4 shrink-0" />
                    {!compact && <span className="truncate">{item.label}</span>}
                  </Link>
                );
              })}
            </div>
          </div>
        );
      })}
    </nav>
  );

  return (
    <div className="flex min-h-screen relative z-10">
      {/* Desktop / tablet sidebar */}
      <aside
        className={cx(
          "hidden md:flex sticky top-0 h-screen shrink-0 border-r border-white/5 bg-navy-900/80 backdrop-blur-md transition-all duration-200 flex-col",
          collapsed ? "w-16" : "w-64"
        )}
      >
        {brand(collapsed)}
        {navList(collapsed)}
        <button
          onClick={() => setCollapsed((c) => !c)}
          className="flex items-center gap-2 px-3 h-11 border-t border-white/5 text-ink-400 hover:text-ink-100 text-sm"
        >
          <ChevronLeft className={cx("w-4 h-4 transition-transform", collapsed && "rotate-180")} />
          {!collapsed && "Collapse"}
        </button>
      </aside>

      {/* Phone: off-canvas drawer */}
      {drawerOpen && (
        <div className="md:hidden fixed inset-0 z-50 flex" role="dialog" aria-modal="true" aria-label="Navigation">
          <div className="absolute inset-0 bg-black/60" onClick={() => setDrawerOpen(false)} />
          <aside className="relative w-72 max-w-[85vw] h-full bg-navy-900 border-r border-white/10 flex flex-col">
            <div className="flex items-center">
              <div className="flex-1">{brand(false)}</div>
              <button className="btn-ghost !px-2 !py-1.5 mr-2" onClick={() => setDrawerOpen(false)} aria-label="Close navigation"><X className="w-4 h-4" /></button>
            </div>
            {navList(false)}
          </aside>
        </div>
      )}

      <div className="flex-1 flex flex-col min-w-0 overflow-x-clip">
        <header className="sticky top-0 z-40 h-14 border-b border-white/5 bg-navy-900/80 backdrop-blur-md flex items-center gap-1.5 sm:gap-2 md:gap-3 px-2 sm:px-3 md:px-4">
          <button className="md:hidden btn-ghost !px-2 !py-1.5" onClick={() => setDrawerOpen(true)} aria-label="Open navigation">
            <Menu className="w-4 h-4" />
          </button>
          <button
            onClick={() => setPaletteOpen(true)}
            aria-label="Search"
            className="flex items-center gap-2 text-sm text-ink-400 bg-navy-800/60 border border-white/5 rounded-lg px-2.5 sm:px-3 py-1.5 hover:border-cyan/30 shrink-0 lg:min-w-[160px]"
          >
            <Search className="w-3.5 h-3.5" />
            <span className="hidden lg:inline">Search / Jump…</span>
            <kbd className="ml-auto hidden lg:flex items-center gap-0.5 text-[10px] text-ink-500">
              <Command className="w-3 h-3" />K
            </kbd>
          </button>

          <TenantSwitcher />

          <div className="flex-1 min-w-0" />

          <div className="flex items-center gap-1.5 sm:gap-2 md:gap-3 shrink-0">
          <ModeIndicator />

          <div
            className={cx("hidden xl:flex items-center gap-1.5 text-xs", connected ? "text-ink-400" : "text-amber")}
            title={connected ? `Live stream connected · ${pulse} events received` : "Live stream disconnected — reconnecting"}
          >
            <Radio className={cx("w-3.5 h-3.5", connected ? "text-teal animate-pulseGlow" : "text-amber")} />
            <span className="tabular-nums">{connected ? "live" : "offline"}</span>
          </div>

          <Link href="/wallboard" className="hidden lg:inline-flex btn-ghost !px-2 !py-1.5" title="Fullscreen SOC wallboard">
            <Maximize2 className="w-4 h-4" />
          </Link>

          <button
            onClick={() => setReduceMotion((v) => !v)}
            className={cx("hidden lg:inline-flex btn-ghost !px-2 !py-1.5", reduceMotion && "text-amber")}
            title="Toggle animations (accessibility)"
            aria-pressed={reduceMotion}
          >
            <Zap className="w-4 h-4" />
          </button>

          {can("notification:read") && <NotificationBell tick={notifTick} />}

          <div className="flex items-center gap-2 pl-1 sm:pl-2 sm:border-l border-white/5 shrink-0">
            <Link href="/account" className="hidden xl:block text-right leading-tight hover:opacity-80 max-w-[180px]" title="My account">
              <div className="text-xs text-ink-100 font-medium truncate">{me.full_name}</div>
              <div className="text-[10px] text-ink-500 truncate">{me.roles.map(titleCase).join(", ")}</div>
            </Link>
            <button onClick={logout} className="btn-ghost !px-2 !py-1.5" title="Sign out" aria-label="Sign out">
              <LogOut className="w-4 h-4" />
            </button>
          </div>
          </div>
        </header>

        <DelegationBanner />

        {flash && (
          <div role="status" className="bg-cyan/10 border-b border-cyan/30 text-cyan text-xs px-4 py-1.5 flex items-center gap-2">
            <Icons.Info className="w-3.5 h-3.5 shrink-0" />
            <span className="flex-1">{flash}</span>
            <button onClick={() => setFlashState(null)} className="underline hover:no-underline">Dismiss</button>
          </div>
        )}

        {mode?.degraded && (
          <div className="bg-amber/10 border-b border-amber/30 text-amber text-xs px-4 py-1.5 flex items-center gap-2">
            <Icons.AlertTriangle className="w-3.5 h-3.5" />
            Degraded operation: {mode.degraded_reasons.join("; ")}
          </div>
        )}

        {/* Keyed on the acting tenant: switching tenants remounts every page,
            so no data from the previous tenant can linger on screen. */}
        <main key={tenantKey} className="flex-1 p-3 sm:p-4 md:p-6 max-w-[1600px] w-full mx-auto min-w-0">{children}</main>
      </div>

      <CommandPalette open={paletteOpen} setOpen={setPaletteOpen} />
    </div>
  );
}

function DelegationBanner() {
  const { me, switchTenant } = useApp();
  if (!me?.delegated_via) return null;
  const breakGlass = me.delegated_via === "break_glass";
  return (
    <div
      role="status"
      className={cx(
        "border-b text-xs px-4 py-1.5 flex flex-wrap items-center gap-2",
        breakGlass ? "bg-crit/15 border-crit/40 text-crit" : "bg-violet/10 border-violet/30 text-violet"
      )}
    >
      {breakGlass ? <ShieldAlert className="w-3.5 h-3.5" /> : <Building2 className="w-3.5 h-3.5" />}
      <span>
        {breakGlass ? "BREAK-GLASS access to " : "Acting in "}
        <b>{me.tenant_name}</b> as <b>{me.roles.map(titleCase).join(", ")}</b> (via {titleCase(me.delegated_via)}
        {" "}from {me.home_tenant_slug}). Every action is recorded in the customer&apos;s audit trail.
      </span>
      <button onClick={() => switchTenant(null)} className="ml-auto underline hover:no-underline">
        Return to {me.home_tenant_slug}
      </button>
    </div>
  );
}

const VIA_LABEL: Record<string, string> = {
  home: "Home", platform: "Platform", break_glass: "Break-glass", provider: "Managed", grant: "Grant",
};

function TenantSwitcher() {
  const { me, tenants, switchTenant } = useApp();
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  const router = useRouter();

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  if (!me || tenants.length <= 1) {
    return me ? (
      <div className="hidden lg:flex items-center gap-1.5 text-xs text-ink-300 min-w-0">
        <Building2 className="w-3.5 h-3.5 text-ink-500 shrink-0" />
        <span className="truncate">{me.tenant_name}</span>
      </div>
    ) : null;
  }

  const shown = tenants.filter((t) =>
    !filter || t.name.toLowerCase().includes(filter.toLowerCase()) || t.slug.includes(filter.toLowerCase()));

  const choose = async (t: AccessibleTenant) => {
    setOpen(false);
    setFilter("");
    await switchTenant(t.via === "home" ? null : t.id);
    router.push(t.via === "home" && t.kind !== "customer" ? "/mssp" : "/dashboard");
  };

  return (
    <div className="relative min-w-0" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className={cx(
          "flex items-center gap-2 text-xs rounded-lg px-2.5 py-1.5 border max-w-[104px] sm:max-w-[260px]",
          me.delegated_via ? "border-violet/40 bg-violet/10 text-violet" : "border-white/10 bg-navy-800/60 text-ink-200"
        )}
        aria-haspopup="listbox"
        aria-expanded={open}
        title="Switch tenant"
      >
        <Building2 className="w-3.5 h-3.5 shrink-0" />
        <span className="truncate font-medium">{me.tenant_name}</span>
        <ChevronDown className="w-3.5 h-3.5 shrink-0" />
      </button>
      {open && (
        <div className="absolute left-0 mt-2 w-80 max-w-[calc(100vw-1.5rem)] panel p-0 overflow-hidden z-50" role="listbox">
          <div className="p-2 border-b border-white/5">
            <input
              autoFocus
              className="input w-full !py-1.5 text-xs"
              placeholder={`Filter ${tenants.length} tenants…`}
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
          </div>
          <div className="max-h-80 overflow-y-auto">
            {shown.map((t) => {
              const active = t.id === me.tenant_id;
              return (
                <button
                  key={t.id}
                  role="option"
                  aria-selected={active}
                  onClick={() => choose(t)}
                  className={cx(
                    "w-full text-left px-3 py-2 flex items-center gap-2 text-sm border-b border-white/5 last:border-0",
                    active ? "bg-cyan/10" : "hover:bg-white/5"
                  )}
                >
                  {t.via === "home" ? <Home className="w-3.5 h-3.5 text-cyan shrink-0" /> : <Building2 className="w-3.5 h-3.5 text-ink-500 shrink-0" />}
                  <div className="min-w-0 flex-1">
                    <div className="text-ink-100 truncate">{t.name}</div>
                    <div className="text-[10px] text-ink-500">
                      {titleCase(t.kind)} · {titleCase(t.service_tier || "")} · {t.region} · {titleCase(t.role)}
                    </div>
                  </div>
                  <span className={cx("chip !text-[9px]", t.via === "break_glass" ? "text-crit border-crit/40" : "text-ink-400 border-white/10")}>
                    {VIA_LABEL[t.via] || t.via}
                  </span>
                  {t.requires_mfa && (
                    <span title={me.mfa_verified ? "Requires two-step verification" : "Requires two-step verification: sign in with MFA to enter"}>
                      <Icons.Lock className={cx("w-3.5 h-3.5", me.mfa_verified ? "text-ink-500" : "text-amber")} />
                    </span>
                  )}
                  {t.status !== "active" && <span className="chip !text-[9px] text-amber border-amber/40">{t.status}</span>}
                  {active && <Check className="w-3.5 h-3.5 text-cyan" />}
                </button>
              );
            })}
            {!shown.length && <div className="px-3 py-6 text-center text-xs text-ink-500">No match.</div>}
          </div>
        </div>
      )}
    </div>
  );
}

function NotificationBell({ tick }: { tick: number }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Notification[]>([]);
  const [unread, setUnread] = useState(0);
  const ref = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try {
      const res = await api.get<{ items: Notification[]; unread: number }>("/notifications?limit=30");
      setItems(res.items);
      setUnread(res.unread);
    } catch {
      /* keep the last known state */
    }
  }, []);

  useEffect(() => {
    load();
  }, [load, tick]);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const markAll = async () => {
    await api.post("/notifications/read-all").catch(() => undefined);
    load();
  };
  const markOne = async (n: Notification) => {
    if (!n.read_at) await api.post(`/notifications/${n.id}/read`).catch(() => undefined);
    setOpen(false);
    load();
  };

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="btn-ghost !px-2 !py-1.5 relative"
        title="Notifications"
        aria-label={`Notifications (${unread} unread)`}
      >
        <Bell className="w-4 h-4" />
        {unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-4 h-4 px-0.5 rounded-full bg-crit text-white text-[9px] flex items-center justify-center">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>
      {open && (
        <div className="fixed sm:absolute right-2 sm:right-0 left-2 sm:left-auto top-14 sm:top-auto sm:mt-2 sm:w-96 panel p-0 overflow-hidden z-50">
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-white/5">
            <span className="card-title">Notifications</span>
            <div className="flex items-center gap-3">
              <button onClick={markAll} className="text-xs text-ink-400 hover:text-cyan">Mark all read</button>
              <Link href="/notifications" onClick={() => setOpen(false)} className="text-xs text-ink-400 hover:text-cyan">View all</Link>
            </div>
          </div>
          <div className="max-h-96 overflow-y-auto">
            {!items.length && <div className="px-4 py-8 text-center text-ink-500 text-sm">No notifications.</div>}
            {items.map((n) => {
              const body = (
                <>
                  <div className="flex items-center gap-2">
                    {!n.read_at && <span className="w-1.5 h-1.5 rounded-full bg-cyan shrink-0" />}
                    <span className={cx("text-ink-200", n.level === "critical" && "text-crit")}>{n.title}</span>
                  </div>
                  {n.body && <div className="text-xs text-ink-400 mt-0.5 line-clamp-2">{n.body}</div>}
                  <div className="text-[10px] text-ink-500 mt-0.5">
                    {titleCase(n.category)} · {timeAgo(n.created_at)}
                  </div>
                </>
              );
              const cls = "block px-4 py-2.5 border-b border-white/5 last:border-0 text-sm hover:bg-white/5 w-full text-left";
              return n.link && n.link.startsWith("/") ? (
                <Link key={n.id} href={n.link} onClick={() => markOne(n)} className={cls}>{body}</Link>
              ) : (
                <button key={n.id} onClick={() => markOne(n)} className={cls}>{body}</button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export function ModeIndicator() {
  const { mode } = useApp();
  if (!mode) return null;
  const live = mode.is_live;
  return (
    <Link
      href="/settings"
      className={cx(
        "flex items-center gap-1.5 rounded-lg px-2 sm:px-2.5 py-1.5 text-xs font-semibold border whitespace-nowrap shrink-0",
        live
          ? "text-crit border-crit/50 bg-crit/10 shadow-glow-crit"
          : "text-cyan border-cyan/40 bg-cyan/10"
      )}
      title={live ? "LIVE mode — production actions are enabled for this tenant" : "DEMO mode — all results for this tenant are simulated"}
    >
      <span className={cx("w-2 h-2 rounded-full", live ? "bg-crit animate-pulseGlow" : "bg-cyan")} />
      {live ? "LIVE" : "DEMO"}
      <span className="hidden lg:inline text-ink-400 font-normal">· {mode.llm_strategy}</span>
    </Link>
  );
}
