import type { Metadata } from "next";

import { Nav } from "./nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "投资助手",
  description: "日本股票行情、信号与模拟交易",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <header>
          <strong>投资助手</strong>
          <Nav />
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
