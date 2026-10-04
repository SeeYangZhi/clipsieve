import { describe, expect, it } from "vitest";
import { version } from "./version";

describe("smoke", () => {
  it("exposes the app version", () => {
    expect(version).toBe("0.1.0");
  });
});
