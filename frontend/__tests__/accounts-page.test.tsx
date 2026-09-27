import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AccountList } from "@/app/accounts/account-list";

const ACCOUNTS = [
  { id: 1, name: "技术评级三年", strategy: "technical_rating_v1", start_date: "2023-09-19", advanced_through: "2026-09-18",
    status: "active", total_return: 0.24918, annualised_return: 0.07709, max_drawdown: 0.21868,
    excess_annualised_return: -0.1112 },
  { id: 2, name: "旧的", strategy: "trend_pullback_v1", start_date: "2025-01-06", advanced_through: null,
    status: "stopped", total_return: null, annualised_return: null, max_drawdown: null, excess_annualised_return: null },
];

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(ACCOUNTS), { headers: { "Content-Type": "application/json" } })));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("账户列表", () => {
  it("每个账户一行：策略、起始日、推进到哪天、收益、回撤、相对 TOPIX、状态", async () => {
    render(<AccountList />);

    const table = await screen.findByRole("table", { name: "模拟账户" });
    const [, first, second] = within(table).getAllByRole("row");
    expect(within(first).getByRole("link", { name: "技术评级三年" })).toHaveAttribute("href", "/accounts/1");
    expect(within(first).getByText("技术评级 v1")).toBeInTheDocument();
    expect(within(first).getByText("2026-09-18")).toBeInTheDocument();
    expect(within(first).getByText("+24.92%")).toHaveClass("up");
    expect(within(first).getByText("+7.71%")).toBeInTheDocument();
    expect(within(first).getByText("−21.87%")).toHaveClass("down");
    expect(within(first).getByText("−11.12%")).toHaveClass("down");
    expect(within(first).getByText("运行中")).toBeInTheDocument();
    expect(within(second).getByText("尚未推进")).toBeInTheDocument();
    expect(within(second).getByText("已停用")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "新建账户" })).toHaveAttribute("href", "/accounts/new");
  });
});
