import { IBM_Plex_Mono, IBM_Plex_Sans, Playfair_Display } from "next/font/google";

/**
 * Three families, one role each:
 *   - IBM Plex Sans      -> body / UI
 *   - IBM Plex Mono      -> any digit, ticker, code
 *   - Playfair Display   -> page headings, brand surfaces
 *
 * `next/font` loads these locally at build time and hands us a `variable`
 * we attach to <html> — globals.css then references those vars from
 * `--font-sans` / `--font-mono` / `--font-display`.
 */
export const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-plex-sans",
  display: "swap",
});

export const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-mono",
  display: "swap",
});

export const playfair = Playfair_Display({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-playfair",
  display: "swap",
});

/** Convenience — apply to <html className={...}> in the root layout. */
export const fontVariableClassName = [
  plexSans.variable,
  plexMono.variable,
  playfair.variable,
].join(" ");
