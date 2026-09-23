import Link from "next/link";

const ENTRIES = [
  { href: "/data", label: "数据" },
  { href: "/signals", label: "信号" },
  { href: "/accounts", label: "账户" },
] as const;

export function Nav() {
  return (
    <nav>
      <ul>
        {ENTRIES.map((entry) => (
          <li key={entry.href}>
            <Link href={entry.href}>{entry.label}</Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
