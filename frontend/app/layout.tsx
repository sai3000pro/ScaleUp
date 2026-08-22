import type { Metadata } from "next";
import { Sora, Space_Grotesk } from "next/font/google";

import "@/app/globals.css";
import { AuthGate } from "@/components/AuthGate";
import { ExpBar } from "@/components/ExpBar";

/**
 * Sora for display, Space Grotesk for body -- matching portfolio-site.
 *
 * Loaded through `next/font` rather than a Google Fonts <link>: the files are
 * self-hosted at build time, so there is no render-blocking request to a third
 * party and no flash of fallback text. `display: swap` plus the CSS-variable
 * handoff below means the same two families are available to Tailwind as
 * `font-display` / `font-body`.
 */
const sora = Sora({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
  variable: "--font-sora",
  display: "swap",
});

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-space-grotesk",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Learn-Any-Instrument",
  description: "Pick a skill, play it, and get coached on what you actually played.",
  icons: {
    icon: "/icon.svg",
  },
};

/**
 * The document shell: fonts, language, skip link, and the persistent HUD.
 *
 * @spec UI-TYPE-001, UI-A11Y-003, UI-A11Y-004
 */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sora.variable} ${spaceGrotesk.variable}`}>
      <body className="min-h-screen bg-slate-950 font-body antialiased">
        <a
          href="#main-content"
          className="absolute left-2 top-2 z-50 -translate-y-20 rounded-md bg-sky-400 px-3 py-2 text-sm font-semibold text-slate-950 transition focus:translate-y-0 focus:outline-none focus:ring-2 focus:ring-sky-200"
        >
          Skip to main content
        </a>
        <AuthGate>
          <ExpBar />
          {children}
        </AuthGate>
      </body>
    </html>
  );
}
