import { describe, expect, it } from "vitest";
import { cropBackgroundStyle } from "./cropStyle";

describe("cropBackgroundStyle", () => {
  it("returns undefined without an image", () => {
    expect(cropBackgroundStyle({ x: 0, y: 0, w: 1, h: 1 }, null)).toBeUndefined();
  });

  it("scales and positions a centered half-size bbox onto the tile", () => {
    const style = cropBackgroundStyle(
      { x: 0.25, y: 0.25, w: 0.5, h: 0.5 },
      "/files/frames/c/f.jpg",
    );
    expect(style?.backgroundImage).toBe("url(/files/frames/c/f.jpg)");
    // A half-width bbox must be scaled 2× to fill the tile.
    expect(style?.backgroundSize).toBe("200% 200%");
    // Its top-left sits halfway through the remaining image.
    expect(style?.backgroundPosition).toBe("50% 50%");
  });

  it("anchors a top-left bbox at the tile origin", () => {
    const style = cropBackgroundStyle(
      { x: 0, y: 0, w: 0.5, h: 0.5 },
      "/f.jpg",
    );
    expect(style?.backgroundPosition).toBe("0% 0%");
  });
});
