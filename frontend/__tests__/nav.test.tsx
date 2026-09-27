import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Nav } from "@/app/nav";

vi.mock("next/navigation", () => ({ usePathname: () => "/accounts/3" }));

describe("导航", () => {
  it("三个入口都在，链到各自的页面", () => {
    render(<Nav />);

    expect(screen.getByRole("link", { name: "数据" })).toHaveAttribute("href", "/data");
    expect(screen.getByRole("link", { name: "信号" })).toHaveAttribute("href", "/signals");
    expect(screen.getByRole("link", { name: "账户" })).toHaveAttribute("href", "/accounts");
  });

  it("标出当前所在的入口，子页面也算", () => {
    render(<Nav />);

    expect(screen.getByRole("link", { name: "账户" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "信号" })).not.toHaveAttribute("aria-current");
  });
});
