import { describe, expect, it } from "vitest";

import { displayCode, signedPercent, signedYen, tone, yen } from "@/lib/format";

describe("数字与代码的写法", () => {
  it("收益带正负号，负号是真正的减号", () => {
    expect(signedPercent(0.24918)).toBe("+24.92%");
    expect(signedPercent(-0.1112)).toBe("−11.12%");
    expect(signedPercent(0)).toBe("0.00%");
    expect(signedPercent(0.3679, 1)).toBe("+36.8%");
    expect(signedPercent(null)).toBe("—");
  });

  it("金额取整、千分位；需要时带正负号", () => {
    expect(yen(900300.4)).toBe("900,300");
    expect(signedYen(-900300)).toBe("−900,300");
    expect(signedYen(7200)).toBe("+7,200");
    expect(signedYen(0)).toBe("0");
  });

  it("正数用涨的颜色，负数用跌的颜色", () => {
    expect([tone(0.1), tone(-0.1), tone(0), tone(null)]).toEqual(["up", "down", "", ""]);
  });

  it("证券代码显示成 4 位：J-Quants 在末尾多补的 0 去掉", () => {
    expect(displayCode("72030")).toBe("7203");
    expect(displayCode("256A0")).toBe("256A");
    expect(displayCode("72031")).toBe("72031"); // 末位不是补的 0，原样
  });
});
