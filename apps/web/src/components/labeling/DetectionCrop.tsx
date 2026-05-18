import { useLabelingStore } from "@/stores/labeling";
import type { FrameDetail } from "@/hooks/useFrame";

interface Props {
  frame: FrameDetail;
}

// Magnified preview of the selected detection, shown under the canvas. The
// crop fills a fixed-height box (capped in width) so a small box still reads.
const PANEL_H = 220;
const MAX_W = 480;

export function DetectionCrop({ frame }: Props) {
  const selectedId = useLabelingStore((s) => s.selectedId);
  const det = selectedId
    ? frame.detections.find((d) => d.id === selectedId)
    : undefined;
  if (!det || frame.width <= 0 || frame.height <= 0) return null;

  const { x, y, w, h } = det.bbox;
  if (w <= 0 || h <= 0) return null;

  const cropW = w * frame.width;
  const cropH = h * frame.height;

  let dispH = PANEL_H;
  let dispW = dispH * (cropW / cropH);
  if (dispW > MAX_W) {
    dispW = MAX_W;
    dispH = dispW * (cropH / cropW);
  }

  // Scale the whole frame image so the crop fills the display box, then offset
  // the background to bring the detection's region into view.
  const scale = dispW / cropW;

  return (
    <div className="mt-3 border-t border-border pt-3">
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Selected detection
      </h2>
      <div
        className="rounded border border-border bg-muted"
        style={{
          width: dispW,
          height: dispH,
          backgroundImage: `url(${frame.image_url})`,
          backgroundSize: `${frame.width * scale}px ${frame.height * scale}px`,
          backgroundPosition: `-${x * frame.width * scale}px -${y * frame.height * scale}px`,
          backgroundRepeat: "no-repeat",
        }}
      />
    </div>
  );
}
