"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { Quartz } from "@/components/mascot/Quartz";
import { NAV_LINK } from "@/lib/ui";
import { useAuthStore } from "@/stores/useAuthStore";

const NAV_ITEMS = [
  { href: "/courses", label: "Courses", icon: "▦" },
  { href: "/quests", label: "Quests", icon: "✦" },
  { href: "/video-analysis", label: "Video", icon: "◉" },
  { href: "/character", label: "Character", icon: "◇" },
];

function isActivePath(pathname: string | null, href: string): boolean {
  return pathname === href || (href !== "/courses" && pathname?.startsWith(`${href}/`) === true);
}

/**
 * The persistent HUD. Visible on every screen on purpose -- the dopamine loop
 * only works if progress is always in view.
 *
 * Styled in app/globals.css rather than in shared classes: this is one
 * composition used once, not a pattern used many times.
 *
 * @spec UI-SHELL-001, UI-SHELL-002, UI-SHELL-003, UI-SHELL-004
 * @spec UI-MASCOT-001, UI-MASCOT-002, LAND-ROUTE-004
 */
export function ExpBar() {
  const pathname = usePathname();
  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);

  // The HUD reports a progress a stranger does not have, so it stays off the
  // public landing page even for a signed-in reader (`LAND-ROUTE-004`).
  if (!user || pathname === "/") return null;

  const pct = user.exp_for_next_level > 0
    ? Math.min(100, Math.round((user.exp_into_level / user.exp_for_next_level) * 100))
    : 0;

  return (
    <header className="hud-header sticky top-0 z-20">
      <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5 sm:py-3">
        {/* The wordmark goes home, which is the landing page -- `/courses` is the
            first nav item and does not need to be the brand link as well. */}
        <Link href="/" className={`hud-wordmark ${NAV_LINK}`}>
          {/* The mascot sits left of the wordmark and faces into it. It carries
              no name: the link's own text already says where this goes, and a
              second tab stop for a decoration would make the reader press Tab
              twice to pass one link. */}
          <span className="hud-wordmark-mark">
            <Quartz size={38} rest="idle-r" greet="blink" react="cheer" />
          </span>
          <span><strong>Learn Any</strong><em>Instrument</em></span>
        </Link>

        <div className="hud-level-pill" title={`${user.total_exp.toLocaleString()} total EXP`}>
          <span className="hud-level-icon" aria-hidden>↗</span>
          <span><small>LEVEL</small><strong>{user.level}</strong></span>
        </div>

        <div className="hud-exp-track min-w-0 flex-1">
          <div className="flex items-center justify-between gap-3">
            <span className="hud-exp-label">Experience</span>
            <span className="hud-exp-value">{user.exp_into_level} <span>/ {user.exp_for_next_level} EXP</span></span>
          </div>
          <div className="hud-progress-bar" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={`Account level ${user.level} progress`}>
            <div className="hud-progress-fill" style={{ width: `${pct}%` }} />
          </div>
        </div>

        <div className="hud-streak" title="Current study streak">
          <span aria-hidden>🔥</span>
          <span><strong>{user.streak_days}</strong><small>streak</small></span>
        </div>

        <nav className="hud-nav flex items-center gap-1" aria-label="Primary navigation">
          {NAV_ITEMS.map((item) => {
            const active = isActivePath(pathname, item.href);
            return (
              <Link key={item.href} href={item.href} className={`hud-nav-link ${active ? "hud-nav-link-active" : ""} ${NAV_LINK}`} aria-current={active ? "page" : undefined}>
                <span aria-hidden>{item.icon}</span><span>{item.label}</span>
              </Link>
            );
          })}
          <button type="button" onClick={logout} className={`hud-nav-link hud-signout ${NAV_LINK}`}>
            <span aria-hidden>↪</span><span>Sign out</span>
          </button>
        </nav>
      </div>
    </header>
  );
}
