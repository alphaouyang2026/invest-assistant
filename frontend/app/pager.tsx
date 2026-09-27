"use client";

const GROUP = 10;

/** 首页 · 上一页 · a group of ten page numbers, with … to the group before
 * and after · 下一页 · 末页. Nothing when everything fits on one page. */
export function Pager({ page, pages, onPage }: { page: number; pages: number; onPage: (page: number) => void }) {
  if (pages <= 1) return null;
  const first = Math.floor((page - 1) / GROUP) * GROUP + 1;
  const last = Math.min(first + GROUP - 1, pages);
  const numbers = Array.from({ length: last - first + 1 }, (_, n) => first + n);

  const button = (text: string, label: string, to: number, disabled = false, className = "btn") => (
    <button type="button" className={className} aria-label={label} disabled={disabled} onClick={() => onPage(to)}>
      {text}
    </button>
  );

  return (
    <nav className="pager" aria-label="分页">
      {button("首页", "首页", 1, page === 1)}
      {button("上一页", "上一页", page - 1, page === 1)}
      <span className="sep" />
      {first > 1 && button("…", `上一组（${first - GROUP}–${first - 1} 页）`, first - 1, false, "btn pg gap")}
      {numbers.map((n) => (
        <button key={n} type="button" className={n === page ? "btn pg on" : "btn pg"} aria-label={`第 ${n} 页`}
                aria-current={n === page ? "page" : undefined} onClick={() => onPage(n)}>
          {n}
        </button>
      ))}
      {last < pages && button("…", `下一组（${last + 1}–${Math.min(last + GROUP, pages)} 页）`, last + 1, false, "btn pg gap")}
      <span className="sep" />
      {button("下一页", "下一页", page + 1, page === pages)}
      {button("末页", "末页", pages, page === pages)}
    </nav>
  );
}

/** "第 51–100 条，共 594 条" */
export const range = (page: number, size: number, total: number, unit: string) =>
  total === 0 ? `共 0 ${unit}` : `第 ${(page - 1) * size + 1}–${Math.min(page * size, total)} ${unit}，共 ${total} ${unit}`;
