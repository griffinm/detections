import { useRef } from "react";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";
import type { DetectionGalleryItem } from "@/hooks/useSubclasses";

interface Props {
  items: DetectionGalleryItem[];
  selectedIds: Set<string>;
  onSelectionChange: (next: Set<string>) => void;
  /** Optional per-id border colour — typically the predicted/current subclass swatch. */
  borderColorByItem?: (item: DetectionGalleryItem) => string | undefined;
  /** The tile that drives the side preview, if any. */
  focusedId?: string | null;
  onFocusChange?: (id: string) => void;
}

/**
 * Selectable tile grid backed by the server's cached bbox crops. Plain click
 * on a tile moves focus (drives the side preview); the corner checkbox is the
 * deliberate selection affordance. Shift-click anywhere on the tile body adds
 * the range between the focus anchor and the click target to the selection.
 */
export function DetectionTileGrid({
  items,
  selectedIds,
  onSelectionChange,
  borderColorByItem,
  focusedId,
  onFocusChange,
}: Props) {
  // Anchor for shift-click range select. Persists across renders (a plain
  // `let` resets every render and silently breaks the muscle memory).
  const anchorIndex = useRef<number | null>(null);

  const toggle = (id: string): Set<string> => {
    const next = new Set(selectedIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  };

  const handleTileClick = (
    e: React.MouseEvent<HTMLButtonElement>,
    index: number,
  ): void => {
    const item = items[index];
    if (e.shiftKey && anchorIndex.current !== null) {
      const lo = Math.min(anchorIndex.current, index);
      const hi = Math.max(anchorIndex.current, index);
      const next = new Set(selectedIds);
      for (let i = lo; i <= hi; i++) next.add(items[i].id);
      onSelectionChange(next);
    }
    // Plain click: focus only. The corner checkbox is the explicit
    // selection toggle so users can click to view without losing the
    // current selection set.
    onFocusChange?.(item.id);
    anchorIndex.current = index;
  };

  const handleCheckClick = (
    e: React.MouseEvent<HTMLButtonElement>,
    id: string,
  ): void => {
    e.stopPropagation();
    onSelectionChange(toggle(id));
  };

  if (items.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">No detections in this group.</p>
    );
  }

  return (
    <div className="flex flex-wrap gap-2">
      {items.map((item, index) => {
        const selected = selectedIds.has(item.id);
        const focused = item.id === focusedId;
        const borderColor = borderColorByItem?.(item);
        return (
          <div key={item.id} className="group relative">
            <button
              type="button"
              onClick={(e) => handleTileClick(e, index)}
              className={cn(
                "h-24 w-24 overflow-hidden rounded border-2 bg-muted transition-shadow",
                focused
                  ? "ring-2 ring-ring ring-offset-2 ring-offset-background"
                  : "hover:ring-1 hover:ring-ring",
              )}
              style={{ borderColor: borderColor ?? "var(--border)" }}
              aria-label="Open in preview"
            >
              {item.crop_url ? (
                <img
                  src={item.crop_url}
                  alt=""
                  loading="lazy"
                  decoding="async"
                  className="h-full w-full object-cover"
                />
              ) : null}
            </button>

            {/* Selection toggle — corner click, deliberate. */}
            <button
              type="button"
              onClick={(e) => handleCheckClick(e, item.id)}
              aria-pressed={selected}
              aria-label={selected ? "Deselect detection" : "Select detection"}
              className={cn(
                "absolute right-1 top-1 flex h-5 w-5 items-center justify-center rounded-full border border-background shadow",
                selected
                  ? "bg-foreground text-background"
                  : "bg-background/90 text-transparent hover:text-muted-foreground",
              )}
            >
              <Check className="h-3 w-3" />
            </button>

            <span
              className={cn(
                "pointer-events-none absolute left-1 top-1 h-2.5 w-2.5 rounded-full border border-background",
                item.reviewed ? "bg-emerald-500" : "bg-amber-500",
              )}
              aria-label={item.reviewed ? "Reviewed" : "Auto-assigned"}
            />
          </div>
        );
      })}
    </div>
  );
}

/**
 * Read-only thumbnail strip — the predicted-group cards show the 9 sample ids
 * inline as a preview before the user expands the group.
 */
export function DetectionThumbStrip({
  detectionIds,
  size = 48,
}: {
  detectionIds: string[];
  size?: number;
}) {
  if (detectionIds.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {detectionIds.map((id) => (
        <div
          key={id}
          className="overflow-hidden rounded border border-border bg-muted"
          style={{ width: size, height: size }}
        >
          <img
            src={`/api/detections/${id}/crop?size=${size * 2}`}
            alt=""
            loading="lazy"
            decoding="async"
            className="h-full w-full object-cover"
          />
        </div>
      ))}
    </div>
  );
}
