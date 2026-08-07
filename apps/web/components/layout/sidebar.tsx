"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Eye,
  History,
  LayoutDashboard,
  type LucideIcon,
  Settings,
  TrendingUp,
} from "lucide-react";
import { motion } from "framer-motion";

import { cn } from "@/lib/utils";
import { useUIStore } from "@/lib/store";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  matchPrefix?: string;
}

const NAV_ITEMS: ReadonlyArray<NavItem> = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/analyze", label: "Analyze", icon: TrendingUp, matchPrefix: "/analyze" },
  { href: "/runs", label: "Runs", icon: History, matchPrefix: "/runs" },
  { href: "/watchlist", label: "Watchlist", icon: Eye },
];

export function Sidebar() {
  const pathname = usePathname();
  const collapsed = useUIStore((s) => s.sidebarCollapsed);

  return (
    <aside
      className={cn(
        "glass sticky top-0 z-20 flex h-screen flex-col rounded-none border-y-0 border-l-0 transition-[width] duration-300",
        collapsed ? "w-16" : "w-60",
      )}
    >
      <div className="flex h-16 items-center gap-3 px-4">
        <div className="relative grid h-9 w-9 place-items-center rounded-xl">
          <span
            className="absolute inset-0 rounded-xl opacity-90 blur-[2px]"
            style={{
              background:
                "conic-gradient(from 140deg, var(--accent-1), var(--accent-2), var(--accent-3), var(--accent-1))",
            }}
          />
          <span className="absolute inset-[1.5px] rounded-[10px] bg-background/85" />
          <TrendingUp className="relative z-10 h-4 w-4 text-foreground" />
        </div>
        {!collapsed && (
          <div className="leading-none">
            <span className="font-display text-lg font-semibold tracking-[0.14em] text-foreground">
              ALPHA
            </span>
            <p className="mt-1 text-[9px] uppercase tracking-[0.3em] text-muted-foreground">
              NSE · BSE Intelligence
            </p>
          </div>
        )}
      </div>

      <nav className="flex flex-1 flex-col gap-1 p-3">
        {NAV_ITEMS.map((item) => {
          const isActive = item.matchPrefix
            ? pathname.startsWith(item.matchPrefix)
            : pathname === item.href;

          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-colors",
                isActive
                  ? "text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {isActive && (
                <motion.span
                  layoutId="sidebar-active"
                  className="glow-accent absolute inset-0 rounded-xl border border-white/10 bg-white/[0.04]"
                  transition={{ type: "spring", stiffness: 400, damping: 32 }}
                />
              )}
              <item.icon
                className={cn(
                  "relative z-10 h-[18px] w-[18px] shrink-0 transition-colors",
                  isActive && "text-accent1",
                )}
              />
              {!collapsed && (
                <span className="relative z-10 truncate font-medium">{item.label}</span>
              )}
              {isActive && !collapsed && (
                <span className="relative z-10 ml-auto h-1.5 w-1.5 rounded-full bg-accent1 shadow-[0_0_10px_var(--accent-1)]" />
              )}
            </Link>
          );
        })}
      </nav>

      <div className="p-3">
        <Link
          href="/settings"
          className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-muted-foreground transition-colors hover:bg-white/[0.03] hover:text-foreground"
        >
          <Settings className="h-[18px] w-[18px] shrink-0" />
          {!collapsed && <span>Settings</span>}
        </Link>
      </div>
    </aside>
  );
}
