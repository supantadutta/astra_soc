"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import * as Icons from "lucide-react";
import {
  Bell, ChevronLeft, Command, LogOut, Maximize2, Radio, Search, Sparkles, Zap,
} from "lucide-react";
import { NAV, NAV_GROUPS } from "@/lib/nav";
import { useApp, useEventStream } from "@/lib/store";
import { cx } from "@/lib/ui";
import { CommandPalette } from "./CommandPalette";
import { Loading } from "./ui";

export function AppShell({ children }: { children: React.ReactNode }) {
  const { me, mode, loading, logout, can } = useApp();
  const router = useRouter();
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [notifOpen, setNotifOpen] = useState(false);
  const [notifs, setNotifs] = useState<any[]>([]);
  const [reduceMotion, setReduceMotion] = useState(false);
  const [pulse, setPulse] = useState(0);

  useEffect(() => {
    if (!loading && !me) router.replace("/login");
  }, [loading, me, router]);

  useEffect(() => {
    document.documentElement.setAttribute("data-reduce-motion", String(reduceMotion));
  }, [reduceMotion]);

  useEventStream(mode?.mode, (ev) => {
    setPulse((p) => (p + 1) % 1000);
    if (["incident.created", "action.created", "approval.decided", "agent.finished", "workflow.waiting_approval"].includes(ev.type)) {
      setNotifs((prev) => [{ ...ev, id: Math.random() }, ...prev].slice(0, 30));
    }
  });

  if (loading) return <div className="min-h-screen flex items-center justify-center"><Loading label="Initializing command center…" /></div>;
  if (!me) return null;

  const items = NAV.filter((n) => !n.permission || can(n.permission));

  return (
    <div className="flex min-h-screen relative z-10">
      {/* Sidebar */}
      <aside
        className={cx(
          "sticky top-0 h-screen shrink-0 border-r border-white/5 bg-navy-900/80 backdrop-blur-md transition-all duration-200 flex flex-col",
          collapsed ? "w-16" : "w-64"
        )}
      >
        <div className="flex items-center gap-2 px-4 h-14 border-b border-white/5">
          <div className="w-8 h-8 rounded-lg bg-navy-800 border border-cyan/40 flex items-center justify-center shadow-glow shrink-0">
            <Sparkles className="w-4 h-4 text-cyan" />
          </div>
          {!collapsed && (
            <div className="leading-tight">
              <div className="text-sm font-bold text-ink-100 tracking-wide">ASTRASOC</div>
              <div className="text-[10px] text-ink-500 uppercase tracking-wider">Command Center</div>
            </div>
          )}
        </div>

        <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-4">
          {NAV_GROUPS.map((group) => {
            const groupItems = items.filter((i) => i.group === group);
            if (!groupItems.length) return null;
            return (
              <div key={group}>
                {!collapsed && <div className="label px-2 mb-1">{group}</div>}
                <div className="space-y-0.5">
                  {groupItems.map((item) => {
                    const Icon = (Icons[item.icon] || Icons.Circle) as any;
                    const activeRoute = pathname === item.href || pathname.startsWith(item.href + "/");
                    return (
                      <Link
                        key={item.href}
                        href={item.href}
                        title={item.label}
                        className={cx(
                          "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors",
                          activeRoute
                            ? "bg-cyan/10 text-cyan border border-cyan/20"
                            : "text-ink-300 hover:bg-white/5 hover:text-ink-100 border border-transparent"
                        )}
                      >
                        <Icon className="w-4 h-4 shrink-0" />
                        {!collapsed && <span className="truncate">{item.label}</span>}
                      </Link>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </nav>

        <button
          onClick={() => setCollapsed((c) => !c)}
          className="flex items-center gap-2 px-3 h-11 border-t border-white/5 text-ink-400 hover:text-ink-100 text-sm"
        >
          <ChevronLeft className={cx("w-4 h-4 transition-transform", collapsed && "rotate-180")} />
          {!collapsed && "Collapse"}
        </button>
      </aside>

      {/* Main column */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="sticky top-0 z-40 h-14 border-b border-white/5 bg-navy-900/80 backdrop-blur-md flex items-center gap-3 px-4">
          <button
            onClick={() => setPaletteOpen(true)}
            className="flex items-center gap-2 text-sm text-ink-400 bg-navy-800/60 border border-white/5 rounded-lg px-3 py-1.5 hover:border-cyan/30 min-w-[180px]"
          >
            <Search className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Search / Jump…</span>
            <kbd className="ml-auto hidden md:flex items-center gap-0.5 text-[10px] text-ink-500">
              <Command className="w-3 h-3" />K
            </kbd>
          </button>

          <div className="flex-1" />

          {/* Mode indicator */}
          <ModeIndicator />

          {/* Live pulse */}
          <div className="hidden md:flex items-center gap-1.5 text-xs text-ink-400" title={`${pulse} live events received`}>
            <Radio className="w-3.5 h-3.5 text-teal animate-pulseGlow" />
            <span className="tabular-nums">live</span>
          </div>

          {/* Wallboard */}
          <Link href="/wallboard" className="btn-ghost !px-2 !py-1.5" title="Fullscreen SOC wallboard">
            <Maximize2 className="w-4 h-4" />
          </Link>

          {/* Reduce motion */}
          <button
            onClick={() => setReduceMotion((v) => !v)}
            className={cx("btn-ghost !px-2 !py-1.5", reduceMotion && "text-amber")}
            title="Toggle animations (accessibility)"
          >
            <Zap className="w-4 h-4" />
          </button>

          {/* Notifications */}
          <div className="relative">
            <button onClick={() => setNotifOpen((v) => !v)} className="btn-ghost !px-2 !py-1.5 relative" title="Notifications">
              <Bell className="w-4 h-4" />
              {notifs.length > 0 && (
                <span className="absolute -top-0.5 -right-0.5 w-4 h-4 rounded-full bg-crit text-white text-[9px] flex items-center justify-center">
                  {notifs.length > 9 ? "9+" : notifs.length}
                </span>
              )}
            </button>
            {notifOpen && <NotifPanel notifs={notifs} onClear={() => setNotifs([])} />}
          </div>

          {/* User */}
          <div className="flex items-center gap-2 pl-2 border-l border-white/5">
            <div className="hidden sm:block text-right leading-tight">
              <div className="text-xs text-ink-100 font-medium">{me.full_name}</div>
              <div className="text-[10px] text-ink-500">{me.roles[0]}</div>
            </div>
            <button onClick={logout} className="btn-ghost !px-2 !py-1.5" title="Sign out">
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </header>

        {mode?.degraded && (
          <div className="bg-amber/10 border-b border-amber/30 text-amber text-xs px-4 py-1.5 flex items-center gap-2">
            <Icons.AlertTriangle className="w-3.5 h-3.5" />
            Degraded operation: {mode.degraded_reasons.join("; ")}
          </div>
        )}

        <main className="flex-1 p-4 md:p-6 max-w-[1600px] w-full mx-auto">{children}</main>
      </div>

      <CommandPalette open={paletteOpen} setOpen={setPaletteOpen} />
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
        "flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold border",
        live
          ? "text-crit border-crit/50 bg-crit/10 shadow-glow-crit"
          : "text-cyan border-cyan/40 bg-cyan/10"
      )}
      title={live ? "LIVE mode — production actions are enabled" : "DEMO mode — all results are simulated"}
    >
      <span className={cx("w-2 h-2 rounded-full", live ? "bg-crit animate-pulseGlow" : "bg-cyan")} />
      {live ? "LIVE" : "DEMO"}
      <span className="hidden lg:inline text-ink-400 font-normal">· {mode.llm_strategy}</span>
    </Link>
  );
}

function NotifPanel({ notifs, onClear }: { notifs: any[]; onClear: () => void }) {
  return (
    <div className="absolute right-0 mt-2 w-80 panel p-0 overflow-hidden z-50">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-white/5">
        <span className="card-title">Notifications</span>
        <button onClick={onClear} className="text-xs text-ink-400 hover:text-cyan">Clear</button>
      </div>
      <div className="max-h-96 overflow-y-auto">
        {!notifs.length && <div className="px-4 py-8 text-center text-ink-500 text-sm">No activity yet.</div>}
        {notifs.map((n) => (
          <div key={n.id} className="px-4 py-2.5 border-b border-white/5 last:border-0 text-sm animate-streamdown">
            <div className="text-ink-200">{describe(n)}</div>
            <div className="text-[10px] text-ink-500 mt-0.5">{new Date(n.ts).toLocaleTimeString()}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function describe(n: any): string {
  switch (n.type) {
    case "incident.created": return `New incident: ${n.title || n.key}`;
    case "action.created": return `Response action requested: ${n.action_type}`;
    case "approval.decided": return `Approval ${n.decision}`;
    case "agent.finished": return `Agent ${n.agent} finished (${n.status})`;
    case "workflow.waiting_approval": return `Workflow waiting for approval`;
    default: return n.type;
  }
}
