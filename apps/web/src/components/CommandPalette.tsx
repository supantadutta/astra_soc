"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";
import { NAV } from "@/lib/nav";
import { useApp } from "@/lib/store";

export function CommandPalette({ open, setOpen }: { open: boolean; setOpen: (v: boolean) => void }) {
  const router = useRouter();
  const { can } = useApp();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen(true);
      }
      if (e.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setOpen]);

  const results = useMemo(() => {
    const items = NAV.filter((n) => !n.permission || can(n.permission));
    if (!query) return items;
    const q = query.toLowerCase();
    return items.filter((n) => n.label.toLowerCase().includes(q) || n.group.toLowerCase().includes(q));
  }, [query, can]);

  useEffect(() => setActive(0), [query]);

  if (!open) return null;

  function go(href: string) {
    setOpen(false);
    setQuery("");
    router.push(href);
  }

  return (
    <div
      className="fixed inset-0 z-[60] bg-black/70 backdrop-blur-sm flex items-start justify-center pt-28"
      onClick={() => setOpen(false)}
    >
      <div className="panel w-full max-w-xl overflow-hidden" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 px-4 border-b border-white/5">
          <Search className="w-4 h-4 text-ink-400" />
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") setActive((a) => Math.min(a + 1, results.length - 1));
              if (e.key === "ArrowUp") setActive((a) => Math.max(a - 1, 0));
              if (e.key === "Enter" && results[active]) go(results[active].href);
            }}
            placeholder="Jump to module, search…"
            className="flex-1 bg-transparent py-3 text-sm text-ink-100 focus:outline-none placeholder:text-ink-500"
          />
          <kbd className="text-[10px] text-ink-500 border border-white/10 rounded px-1.5 py-0.5">ESC</kbd>
        </div>
        <div className="max-h-80 overflow-y-auto py-2">
          {results.map((n, i) => (
            <button
              key={n.href}
              onMouseEnter={() => setActive(i)}
              onClick={() => go(n.href)}
              className={`w-full text-left px-4 py-2 flex items-center justify-between text-sm ${
                i === active ? "bg-cyan/10 text-cyan" : "text-ink-200 hover:bg-white/5"
              }`}
            >
              <span>{n.label}</span>
              <span className="text-[10px] uppercase tracking-wide text-ink-500">{n.group}</span>
            </button>
          ))}
          {!results.length && <div className="px-4 py-6 text-center text-ink-500 text-sm">No matches.</div>}
        </div>
      </div>
    </div>
  );
}
