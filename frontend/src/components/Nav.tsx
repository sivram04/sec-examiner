"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/examiner", label: "SEC Examiner" },
  { href: "/loop", label: "Self-improvement" },
];

export default function Nav() {
  const path = usePathname();
  return (
    <nav className="flex gap-1">
      {TABS.map((t) => {
        const active = path.startsWith(t.href);
        return (
          <Link
            key={t.href}
            href={t.href}
            aria-current={active ? "page" : undefined}
            className={`border-b-2 px-3 pb-3 pt-1 text-sm ${active ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink"}`}
          >
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}
