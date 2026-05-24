import { ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";
import type { DetectionGalleryItem } from "@/hooks/useSubclasses";

interface Props {
  item: DetectionGalleryItem | null;
  /** Optional accent for the bbox overlay (typically the predicted/current
   *  subclass colour). */
  bboxColor?: string;
}

const LARGE_CROP_SIZE = 512;

/**
 * Side-rail preview for the bulk-labeling pages: the focused detection
 * rendered both as a large crop (the cached `/crop?size=` JPEG) and as the
 * full frame with the bbox drawn over it. The "Open frame" link is the way
 * out to the single-detection editor when the user wants to fix the box.
 */
export function DetectionPreview({ item, bboxColor }: Props) {
  if (!item) {
    return (
      <aside className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
        Click a tile to preview the detection here.
      </aside>
    );
  }

  const { bbox } = item;
  const accent = bboxColor ?? "#facc15"; // amber fallback — visible on any frame

  return (
    <aside className="space-y-4">
      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Crop
        </h3>
        <div className="overflow-hidden rounded border border-border bg-muted">
          <img
            // Cache-busting on every focus change is unnecessary — bbox-hashed
            // filename guarantees the same URL maps to the same bytes.
            src={`/api/detections/${item.id}/crop?size=${LARGE_CROP_SIZE}`}
            alt="Detection crop"
            className="block h-auto w-full"
          />
        </div>
      </div>

      <div>
        <div className="mb-2 flex items-baseline justify-between gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            In frame
          </h3>
          <Link
            to={`/labeling/${item.frame_id}`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
          >
            Open frame <ExternalLink className="h-3 w-3" />
          </Link>
        </div>
        <div className="relative overflow-hidden rounded border border-border bg-muted">
          {item.image_url ? (
            <img
              src={item.image_url}
              alt="Source frame"
              className="block h-auto w-full"
            />
          ) : (
            <div className="flex h-40 items-center justify-center text-xs text-muted-foreground">
              Frame image unavailable
            </div>
          )}
          {item.image_url && (
            <div
              className="pointer-events-none absolute border-2"
              style={{
                left: `${bbox.x * 100}%`,
                top: `${bbox.y * 100}%`,
                width: `${bbox.w * 100}%`,
                height: `${bbox.h * 100}%`,
                borderColor: accent,
                boxShadow: "0 0 0 1px rgba(0,0,0,0.6)",
              }}
              aria-hidden
            />
          )}
        </div>
      </div>

      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <dt>Status</dt>
        <dd className="text-foreground">
          {item.reviewed ? "Reviewed" : "Auto-assigned"}
        </dd>
        <dt>Source</dt>
        <dd className="text-foreground">{item.source}</dd>
      </dl>
    </aside>
  );
}
