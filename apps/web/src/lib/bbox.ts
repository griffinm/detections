import type { Bbox } from "@/hooks/useFrame";

export interface PixelRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Smallest box (in display pixels) a draw/resize is allowed to produce. */
export const MIN_BOX_PX = 6;

export const clamp01 = (v: number): number => Math.min(Math.max(v, 0), 1);

/**
 * Convert a pixel-space rect on a `dispW`×`dispH` display into a normalized
 * 0..1 bbox, clamped so it always stays inside the frame.
 */
export function toNormalizedBbox(
  rect: PixelRect,
  dispW: number,
  dispH: number,
): Bbox {
  const x = clamp01(rect.x / dispW);
  const y = clamp01(rect.y / dispH);
  const w = Math.min(Math.max(rect.w / dispW, 0), 1 - x);
  const h = Math.min(Math.max(rect.h / dispH, 0), 1 - y);
  return { x, y, w, h };
}

/** Inverse of {@link toNormalizedBbox}. */
export function toPixelRect(bbox: Bbox, dispW: number, dispH: number): PixelRect {
  return {
    x: bbox.x * dispW,
    y: bbox.y * dispH,
    w: bbox.w * dispW,
    h: bbox.h * dispH,
  };
}
