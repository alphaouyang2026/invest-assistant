import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Pager } from "@/app/pager";

const numbers = () =>
  within(screen.getByRole("navigation", { name: "分页" }))
    .getAllByRole("button", { name: /^第 \d+ 页$/ })
    .map((button) => button.textContent);

describe("分页", () => {
  it("第 1 页：首页、上一页不能点，显示第一组页码和去下一组的按钮", () => {
    render(<Pager page={1} pages={12} onPage={() => {}} />);

    expect(numbers()).toEqual(["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]);
    expect(screen.getByRole("button", { name: "第 1 页" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "首页" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "上一页" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "下一组（11–12 页）" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: /上一组/ })).toBeNull();
  });

  it("中间一组：前后两组都能跳，每个按钮翻到对应的页", async () => {
    const onPage = vi.fn();
    const user = userEvent.setup();
    render(<Pager page={17} pages={40} onPage={onPage} />);

    expect(numbers()).toEqual(["11", "12", "13", "14", "15", "16", "17", "18", "19", "20"]);
    for (const [name, page] of [
      ["首页", 1], ["上一页", 16], ["上一组（1–10 页）", 10], ["第 13 页", 13],
      ["下一组（21–30 页）", 21], ["下一页", 18], ["末页", 40],
    ] as const) {
      await user.click(screen.getByRole("button", { name }));
      expect(onPage).toHaveBeenLastCalledWith(page);
    }
  });

  it("最后一页：下一页、末页不能点", () => {
    render(<Pager page={12} pages={12} onPage={() => {}} />);

    expect(numbers()).toEqual(["11", "12"]);
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "末页" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /下一组/ })).toBeNull();
  });

  it("只有一页时不显示", () => {
    render(<Pager page={1} pages={1} onPage={() => {}} />);

    expect(screen.queryByRole("navigation", { name: "分页" })).toBeNull();
  });
});
