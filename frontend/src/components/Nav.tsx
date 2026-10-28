"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/", label: "Research" },
  { href: "/search", label: "Search filings" },
  { href: "/changes", label: "What changed" },
  { href: "/companies", label: "Companies" },
  { href: "/reports", label: "Reports" },
];

export default function Nav() {
  const path = usePathname();
  return (
    <nav className="flex flex-wrap gap-1 border-b border-line px-4 pt-3 sm:px-6">
      {TABS.map((t) => {
        const active = t.href === "/" ? path === "/" : path.startsWith(t.href);
        return (
          <Link
            key={t.href}
            href={t.href}
            aria-current={active ? "page" : undefined}
            className={`border-b-2 px-3 py-2 ${active ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink"}`}
          >
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}
