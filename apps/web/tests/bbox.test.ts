import { describe, expect, it } from "vitest";
import { clamp01, toNormalizedBbox, toPixelRect } from "@/lib/bbox";

describe("toNormalizedBbox", () => {
  it("normalizes a pixel rect against the display size", () => {
    expect(toNormalizedBbox({ x: 100, y: 50, w: 200, h: 200 }, 400, 500)).toEqual({
      x: 0.25,
      y: 0.1,
      w: 0.5,
      h: 0.4,
    });
  });

  it("clamps a rect that spills outside the frame", () => {
    const b = toNormalizedBbox({ x: -20, y: -10, w: 1000, h: 1000 }, 400, 500);
    expect(b.x).toBe(0);
    expect(b.y).toBe(0);
    expect(b.x + b.w).toBeLessThanOrEqual(1);
    expect(b.y + b.h).toBeLessThanOrEqual(1);
  });

  it("round-trips through toPixelRect", () => {
    const rect = { x: 40, y: 30, w: 120, h: 90 };
    expect(toPixelRect(toNormalizedBbox(rect, 400, 300), 400, 300)).toEqual(rect);
  });
});

describe("clamp01", () => {
  it("clamps into the 0..1 range", () => {
    expect(clamp01(-1)).toBe(0);
    expect(clamp01(2)).toBe(1);
    expect(clamp01(0.5)).toBe(0.5);
  });
});
