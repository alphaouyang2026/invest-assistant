"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const ENTRIES = [
  { href: "/data", label: "数据" },
  { href: "/signals", label: "信号" },
  { href: "/accounts", label: "账户" },
] as const;

export function Nav() {
  const pathname = usePathname() ?? "";
  return (
    <nav className="nav" aria-label="主导航">
      <ul>
        {ENTRIES.map((entry) => {
          const here = pathname === entry.href || pathname.startsWith(`${entry.href}/`);
          return (
            <li key={entry.href}>
              <Link href={entry.href} className={here ? "on" : undefined} aria-current={here ? "page" : undefined}>
                {entry.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
