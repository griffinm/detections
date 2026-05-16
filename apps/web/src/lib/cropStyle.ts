import type { CSSProperties } from "react";
import type { Bbox } from "@/hooks/useFrame";

/**
 * CSS that shows only `bbox` of a full frame image inside a fixed-size tile —
 * a zero-cost client-side crop for the sub-class examples gallery (no server
 * cropping, no extra requests). `bbox` is normalized 0..1.
 */
export function cropBackgroundStyle(
  bbox: Bbox,
  imageUrl: string | null,
): CSSProperties | undefined {
  if (!imageUrl) return undefined;
  const fw = Math.max(bbox.w, 1e-4);
  const fh = Math.max(bbox.h, 1e-4);
  return {
    backgroundImage: `url(${imageUrl})`,
    backgroundSize: `${100 / fw}% ${100 / fh}%`,
    backgroundPosition: `${(bbox.x / Math.max(1 - fw, 1e-4)) * 100}% ${
      (bbox.y / Math.max(1 - fh, 1e-4)) * 100
    }%`,
  };
}
