"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Eye,
  History,
  LayoutDashboard,
  type LucideIcon,
  Settings,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import { motion } from "framer-motion";

import { cn } from "@/lib/utils";
import { useUIStore } from "@/lib/store";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** When set, the nav item highlights for any path that startsWith. */
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
        "flex h-screen flex-col border-r border-border bg-card/40 backdrop-blur-sm transition-[width] duration-200",
        collapsed ? "w-16" : "w-60",
      )}
    >
      <div className="flex h-14 items-center gap-2 border-b border-border px-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-md bg-gold/15 ring-1 ring-inset ring-gold/40">
          <Sparkles className="h-4 w-4 text-gold" />
        </div>
        {!collapsed && (
          <span className="font-display text-lg font-semibold tracking-[0.12em] text-foreground">
            ALPHA
          </span>
        )}
      </div>

      <nav className="flex flex-1 flex-col gap-1 p-2">
        {NAV_ITEMS.map((item) => {
          const isActive = item.matchPrefix
            ? pathname.startsWith(item.matchPrefix)
            : pathname === item.href;

          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "group relative flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                isActive
                  ? "text-foreground"
                  : "text-muted-foreground hover:bg-accent/40 hover:text-foreground",
              )}
            >
              {isActive && (
                <motion.span
                  layoutId="sidebar-active"
                  className="absolute inset-0 rounded-md bg-accent/60 ring-1 ring-inset ring-border"
                  transition={{ type: "spring", stiffness: 400, damping: 32 }}
                />
              )}
              <item.icon className="relative z-10 h-4 w-4 shrink-0" />
              {!collapsed && (
                <span className="relative z-10 truncate">{item.label}</span>
              )}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-border p-2">
        <Link
          href="/settings"
          className={cn(
            "flex items-center gap-3 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent/40 hover:text-foreground",
          )}
        >
          <Settings className="h-4 w-4 shrink-0" />
          {!collapsed && <span>Settings</span>}
        </Link>
      </div>
    </aside>
  );
}
