import * as React from "react";

import { Sidebar } from "./sidebar";

/**
 * Shared chrome for every authenticated page.
 *
 *   ┌──────────────────────────────────────────────────────┐
 *   │ sidebar │  page content                              │
 *   │         │                                            │
 *   └──────────────────────────────────────────────────────┘
 */
export function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen w-full bg-background text-foreground">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-screen-2xl px-6 py-8">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
