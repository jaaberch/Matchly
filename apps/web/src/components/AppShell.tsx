"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { useSession } from "./SessionProvider";

/**
 * Mobile-first shell: a compact top bar and a thumb-reachable bottom nav.
 * Content is capped at a phone-ish width and centred so it still looks
 * deliberate on a desktop browser.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const { user } = useSession();
  const pathname = usePathname();

  return (
    <div className="mx-auto flex min-h-dvh w-full max-w-md flex-col bg-ink-900">
      <header className="safe-top sticky top-0 z-10 border-b border-ink-700/60 bg-ink-900/90 backdrop-blur">
        <div className="flex h-14 items-center justify-between px-4">
          <Link href="/" className="flex items-center gap-2">
            <span className="grid h-7 w-7 place-items-center rounded-lg bg-pitch-500 text-sm font-black text-ink-900">
              M
            </span>
            <span className="text-base font-bold tracking-tight">Matchly</span>
          </Link>
          {user && (
            <Link
              href="/profile"
              className="grid h-8 w-8 place-items-center rounded-full bg-ink-600 text-xs font-semibold text-ink-100"
              aria-label="Profile"
            >
              {user.name.charAt(0).toUpperCase()}
            </Link>
          )}
        </div>
      </header>

      <main className="flex-1 px-4 py-5">{children}</main>

      {user && <BottomNav pathname={pathname} />}
    </div>
  );
}

const NAV = [
  { href: "/", label: "Home", icon: "⌂" },
  { href: "/highlights", label: "Highlights", icon: "▶" },
  { href: "/profile", label: "Profile", icon: "○" },
];

function BottomNav({ pathname }: { pathname: string }) {
  return (
    <nav className="safe-bottom sticky bottom-0 border-t border-ink-700/60 bg-ink-900/95 backdrop-blur">
      <ul className="flex">
        {NAV.map((item) => {
          const active = pathname === item.href;
          return (
            <li key={item.href} className="flex-1">
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`flex h-16 flex-col items-center justify-center gap-1 text-xs transition-colors ${
                  active ? "text-pitch-400" : "text-ink-300 hover:text-ink-100"
                }`}
              >
                <span aria-hidden className="text-lg leading-none">
                  {item.icon}
                </span>
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
