import { describe, expect, it } from "vitest";

import nextConfig from "../next.config";

describe("Next.js proxy configuration", () => {
  it("allows research API requests to run for five minutes", () => {
    expect(nextConfig.experimental?.proxyTimeout).toBe(300_000);
  });
});
