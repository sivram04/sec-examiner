"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowUpRight } from "@/components/Icons";

const TABS = [
  { href: "/", label: "Overview" },
  { href: "/examiner", label: "Examine a filing" },
  { href: "/loop", label: "Self-improvement" },
];

export default function Nav() {
  const path = usePathname();
  const [today, setToday] = useState("");
  useEffect(() => {
    setToday(new Date().toLocaleDateString("en-US", { weekday: "long", year: "numeric", month: "long", day: "numeric" }));
  }, []);
  const isActive = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));

  return (
    <header className="mx-auto max-w-6xl px-4 pt-4 sm:px-6">
      <div className="caps flex flex-wrap items-center justify-between gap-x-6 gap-y-1 border-b border-line pb-1.5 text-muted">
        <span>Vol. 1 · Public edition</span>
        <span className="min-h-[1em]">{today}</span>
      </div>
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-2 pt-3 pb-2">
        <Link href="/" className="head text-[2.2rem] font-black leading-none tracking-tight sm:text-[3rem]">
          SEC&nbsp;Examiner
        </Link>
        <nav aria-label="Main" className="-mx-2.5 -mb-2 flex max-w-[calc(100%+1.25rem)] gap-x-1 overflow-x-auto whitespace-nowrap [scrollbar-width:none]">
          {TABS.map((t) => (
            <Link key={t.href} href={t.href} aria-current={isActive(t.href) ? "page" : undefined}
              className={`caps border-b-[3px] px-2.5 py-2 text-[0.78rem] transition-colors ${isActive(t.href) ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink"}`}>
              {t.label}
            </Link>
          ))}
          <a href="https://github.com/sivram04/sec-examiner" className="caps hidden sm:inline-flex items-center gap-1 border-b-[3px] border-transparent px-2.5 py-2 text-[0.78rem] text-muted hover:text-ink">
            GitHub <ArrowUpRight />
          </a>
        </nav>
      </div>
      <div className="rule-heavy" />
    </header>
  );
}
