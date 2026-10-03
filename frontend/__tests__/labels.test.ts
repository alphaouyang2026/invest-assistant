import { describe, expect, it } from "vitest";

import { reason, reasonTone } from "@/lib/labels";

describe("理由的文字和颜色", () => {
  it("TOPIX 均线：在均线之上偏买，在缓冲带内不着色，在均线之下偏卖", () => {
    expect(["topix_above_ma", "topix_near_ma", "topix_below_ma"].map((code) => [reason(code), reasonTone(code)]))
      .toEqual([
        ["TOPIX 在均线之上", "up"],
        ["TOPIX 在均线附近（缓冲带内）", ""],
        ["TOPIX 在均线之下", "down"],
      ]);
  });

  it("TOPIX 动量：过去收益为正偏买，为 0 和不是判断日不着色，为负偏卖", () => {
    expect(["topix_momentum_up", "topix_momentum_flat", "topix_momentum_down", "not_check_day"]
      .map((code) => [reason(code), reasonTone(code)]))
      .toEqual([
        ["TOPIX 过去收益为正", "up"],
        ["TOPIX 过去收益为 0", ""],
        ["TOPIX 过去收益为负", "down"],
        ["不是每月判断日", ""],
      ]);
  });
});
