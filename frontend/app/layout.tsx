import type { Metadata } from "next";
import Link from "next/link";

import { DataBadge } from "./data-badge";
import { Nav } from "./nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "投资助手",
  description: "日本股票行情、信号与模拟交易",
};

const FONTS =
  "https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500" +
  "&family=IBM+Plex+Sans:wght@400;500;600&family=Noto+Sans+SC:wght@400;500;600&display=swap";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link rel="stylesheet" href={FONTS} />
      </head>
      <body>
        <header className="topbar">
          <Link href="/" className="brand">
            <Logo />
            <span>投资助手</span>
          </Link>
          <Nav />
          <div className="status">
            <DataBadge />
          </div>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}

function Logo() {
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" fill="none" aria-hidden="true">
      <rect x="1" y="1" width="20" height="20" rx="5" stroke="currentColor" strokeWidth="1.5" />
      <path d="M5 15l4-4 3 3 5-6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
