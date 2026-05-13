import type { Metadata, Viewport } from "next";

import "./globals.css";

import { Shell } from "@/components/layout/shell";
import { fontVariableClassName } from "@/lib/fonts";

import { Providers } from "./providers";

export const metadata: Metadata = {
  title: {
    default: "ALPHA",
    template: "%s · ALPHA",
  },
  description:
    "Multi-agent financial analysis. Deterministic scoring, narrative-only LLMs.",
};

export const viewport: Viewport = {
  themeColor: "#0a0c0f",
  colorScheme: "dark",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`dark ${fontVariableClassName}`} suppressHydrationWarning>
      {/*
        `suppressHydrationWarning` here only silences attribute mismatches
        on the body itself — not its React children. Browser extensions
        (Grammarly, ColorZilla, Dark Reader, …) inject `data-gr-*` and
        similar attributes before React hydrates, which would otherwise
        spam a console error on every page load. Children still validate
        normally so real hydration bugs surface.
      */}
      <body
        className="bg-background font-sans text-foreground antialiased"
        suppressHydrationWarning
      >
        <Providers>
          <Shell>{children}</Shell>
        </Providers>
      </body>
    </html>
  );
}
