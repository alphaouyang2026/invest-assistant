import Link from "next/link";

const PAGES = [
  { href: "/data", title: "数据", text: "J-Quants 日线同步到哪一天，最近任务的结果，数据质量警告" },
  { href: "/signals", title: "信号", text: "每个交易日收盘后，按策略可以买入的证券；单只证券的 K 线与指标" },
  { href: "/accounts", title: "账户", text: "模拟账户：从起始日回测到今天，之后随每日同步继续推进" },
] as const;

export default function Home() {
  return (
    <section className="page">
      <div>
        <h1>投资助手</h1>
        <div className="meta">
          <span>日本股票行情、信号与模拟交易</span>
        </div>
      </div>
      <ul className="card list">
        {PAGES.map((page) => (
          <li key={page.href}>
            <Link href={page.href} className="code strong">
              {page.title}
            </Link>
            <p className="sub">{page.text}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
