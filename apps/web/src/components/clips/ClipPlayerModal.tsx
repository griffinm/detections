import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useClasses, type VdClass } from "@/hooks/useClasses";
import {
  useClipFrames,
  useClipOverlay,
  type ClipOverlayDetection,
  type Frame,
} from "@/hooks/useFrames";
import { cn } from "@/lib/utils";

const FALLBACK_COLOR = "#888888";

interface PlayingClip {
  id: string;
  name: string;
  width: number | null;
  height: number | null;
}

export function ClipPlayerModal({
  clip,
  onOpenChange,
}: {
  clip: PlayingClip | null;
  onOpenChange: (open: boolean) => void;
}) {
  const open = clip !== null;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        // Override the default `max-w-md` from the shared DialogContent so the
        // player has room. p-0 lets the video sit edge-to-edge under the
        // header.
        className="max-w-5xl gap-0 p-0"
      >
        {clip && <PlayerBody clip={clip} />}
      </DialogContent>
    </Dialog>
  );
}

function PlayerBody({ clip }: { clip: PlayingClip }) {
  const frames = useClipFrames(clip.id);
  const overlay = useClipOverlay(clip.id);
  const classes = useClasses();

  const classById = useMemo(() => {
    const m = new Map<string, VdClass>();
    (classes.data ?? []).forEach((c) => m.set(c.id, c));
    return m;
  }, [classes.data]);

  // Which classes appear in this clip — these populate the filter chips.
  // Ordered by total detection count, descending (most prominent first).
  const classesInClip = useMemo(() => {
    const counts = new Map<string | null, number>();
    (overlay.data ?? []).forEach((d) => {
      counts.set(d.class_id, (counts.get(d.class_id) ?? 0) + 1);
    });
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([id, count]) => ({ id, count }));
  }, [overlay.data]);

  // Default: all classes active. Toggling a chip flips its membership.
  const [activeClassIds, setActiveClassIds] = useState<Set<string | null>>(
    new Set(),
  );
  const [activeInitialized, setActiveInitialized] = useState(false);
  useEffect(() => {
    if (!activeInitialized && classesInClip.length > 0) {
      setActiveClassIds(new Set(classesInClip.map((c) => c.id)));
      setActiveInitialized(true);
    }
  }, [classesInClip, activeInitialized]);

  const toggleClass = (id: string | null) => {
    setActiveClassIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Group detections by frame_index for O(1) per-tick lookup.
  const detsByFrame = useMemo(() => {
    const m = new Map<number, ClipOverlayDetection[]>();
    (overlay.data ?? []).forEach((d) => {
      const arr = m.get(d.frame_index);
      if (arr) arr.push(d);
      else m.set(d.frame_index, [d]);
    });
    return m;
  }, [overlay.data]);

  // Sort frames by timestamp so binary-search finds the active frame.
  const framesByTime = useMemo(() => {
    return [...(frames.data ?? [])].sort(
      (a, b) => a.timestamp_sec - b.timestamp_sec,
    );
  }, [frames.data]);

  return (
    <>
      <DialogHeader className="border-b border-border px-6 py-4">
        <DialogTitle className="truncate">{clip.name}</DialogTitle>
        <DialogDescription>
          {overlay.isPending
            ? "Loading detections…"
            : `${overlay.data?.length ?? 0} detections across ${framesByTime.length} frames`}
        </DialogDescription>
        {classesInClip.length > 0 && (
          <div className="flex flex-wrap gap-2 pt-2">
            {classesInClip.map(({ id, count }) => {
              const meta = id ? classById.get(id) : null;
              const name = meta?.name ?? (id ? "unknown" : "unclassified");
              const color = meta?.color_hex ?? FALLBACK_COLOR;
              const active = activeClassIds.has(id);
              return (
                <button
                  key={id ?? "_null"}
                  type="button"
                  onClick={() => toggleClass(id)}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs transition-colors",
                    active
                      ? "border-border bg-muted text-foreground"
                      : "border-border/50 bg-transparent text-muted-foreground opacity-60 hover:opacity-100",
                  )}
                >
                  <span
                    className="h-2.5 w-2.5 rounded-sm border border-border"
                    style={{ backgroundColor: color }}
                  />
                  <span>{name}</span>
                  <span className="text-muted-foreground">{count}</span>
                </button>
              );
            })}
          </div>
        )}
      </DialogHeader>
      <PlayerStage
        clipId={clip.id}
        clipWidth={clip.width}
        clipHeight={clip.height}
        framesByTime={framesByTime}
        detsByFrame={detsByFrame}
        activeClassIds={activeClassIds}
        classById={classById}
      />
    </>
  );
}

interface VisibleRect {
  // The rect of the *visible* video pixels within the <video> element's
  // bounding box. With object-fit: contain the visible content is letterboxed
  // — bboxes need to land on top of the visible pixels, not the whole box.
  offsetX: number;
  offsetY: number;
  width: number;
  height: number;
}

function PlayerStage({
  clipId,
  clipWidth,
  clipHeight,
  framesByTime,
  detsByFrame,
  activeClassIds,
  classById,
}: {
  clipId: string;
  clipWidth: number | null;
  clipHeight: number | null;
  framesByTime: Frame[];
  detsByFrame: Map<number, ClipOverlayDetection[]>;
  activeClassIds: Set<string | null>;
  classById: Map<string, VdClass>;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [rect, setRect] = useState<VisibleRect>({
    offsetX: 0,
    offsetY: 0,
    width: 0,
    height: 0,
  });
  const [currentFrameIdx, setCurrentFrameIdx] = useState<number | null>(null);
  const [videoError, setVideoError] = useState(false);
  const [showTrackIds, setShowTrackIds] = useState(true);
  const [showClassLabels, setShowClassLabels] = useState(true);

  // Compute the letterboxed inner rect from the element bounding box plus
  // the video's intrinsic aspect ratio (falls back to the clip metadata).
  const recomputeRect = () => {
    const v = videoRef.current;
    if (!v) return;
    const r = v.getBoundingClientRect();
    const vw = v.videoWidth || clipWidth || 0;
    const vh = v.videoHeight || clipHeight || 0;
    if (r.width <= 0 || r.height <= 0 || vw <= 0 || vh <= 0) {
      setRect({ offsetX: 0, offsetY: 0, width: r.width, height: r.height });
      return;
    }
    const elementAspect = r.width / r.height;
    const videoAspect = vw / vh;
    let renderedW = r.width;
    let renderedH = r.height;
    let offX = 0;
    let offY = 0;
    if (videoAspect > elementAspect) {
      renderedH = r.width / videoAspect;
      offY = (r.height - renderedH) / 2;
    } else {
      renderedW = r.height * videoAspect;
      offX = (r.width - renderedW) / 2;
    }
    setRect({
      offsetX: offX,
      offsetY: offY,
      width: renderedW,
      height: renderedH,
    });
  };

  // Find the latest frame whose timestamp_sec <= t (binary search). Robust
  // to non-1.0 VD_FRAME_FPS since we don't assume the mapping is integer.
  const frameAt = (t: number): number | null => {
    if (framesByTime.length === 0) return null;
    let lo = 0;
    let hi = framesByTime.length - 1;
    let best: Frame | null = null;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (framesByTime[mid].timestamp_sec <= t) {
        best = framesByTime[mid];
        lo = mid + 1;
      } else {
        hi = mid - 1;
      }
    }
    return best?.frame_index ?? framesByTime[0].frame_index;
  };

  // Drive the overlay: a rAF loop while playing, plus one-shot updates on
  // seek/pause/loadedmetadata so the boxes are right even when paused.
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    let raf: number | null = null;
    const tick = () => {
      setCurrentFrameIdx(frameAt(v.currentTime));
    };
    const loop = () => {
      tick();
      raf = requestAnimationFrame(loop);
    };
    const onPlay = () => {
      if (raf === null) raf = requestAnimationFrame(loop);
    };
    const stopLoop = () => {
      if (raf !== null) {
        cancelAnimationFrame(raf);
        raf = null;
      }
      tick();
    };
    const onLoaded = () => {
      recomputeRect();
      tick();
    };
    v.addEventListener("play", onPlay);
    v.addEventListener("pause", stopLoop);
    v.addEventListener("seeked", tick);
    v.addEventListener("ended", stopLoop);
    v.addEventListener("loadedmetadata", onLoaded);
    return () => {
      if (raf !== null) cancelAnimationFrame(raf);
      v.removeEventListener("play", onPlay);
      v.removeEventListener("pause", stopLoop);
      v.removeEventListener("seeked", tick);
      v.removeEventListener("ended", stopLoop);
      v.removeEventListener("loadedmetadata", onLoaded);
    };
    // framesByTime is intentionally a dep so a fresh frames load re-binds
    // the closure with up-to-date lookup data.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [framesByTime]);

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const ro = new ResizeObserver(() => recomputeRect());
    ro.observe(v);
    return () => ro.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clipWidth, clipHeight]);

  const visibleDetections = useMemo(() => {
    if (currentFrameIdx == null) return [];
    const all = detsByFrame.get(currentFrameIdx) ?? [];
    return all.filter((d) => activeClassIds.has(d.class_id));
  }, [currentFrameIdx, detsByFrame, activeClassIds]);

  return (
    <div className="space-y-3 p-6 pt-4">
      <div className="relative bg-black">
        <video
          ref={videoRef}
          src={`/api/clips/${clipId}/video`}
          controls
          preload="metadata"
          playsInline
          className="block max-h-[70vh] w-full"
          onError={() => setVideoError(true)}
        />
        {videoError ? (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-black/70 text-sm text-white">
            <div className="flex items-center gap-2 rounded bg-black/80 px-3 py-2">
              <AlertTriangle className="h-4 w-4" />
              <span>
                Browser can&apos;t play this video — likely an unsupported
                codec (HEVC).
              </span>
            </div>
          </div>
        ) : (
          <div
            className="pointer-events-none absolute"
            style={{
              left: rect.offsetX,
              top: rect.offsetY,
              width: rect.width,
              height: rect.height,
            }}
          >
            {visibleDetections.map((d, i) => (
              <BboxOverlay
                key={`${d.track_id ?? "_"}-${d.class_id ?? "_"}-${i}`}
                d={d}
                width={rect.width}
                height={rect.height}
                classMeta={d.class_id ? classById.get(d.class_id) ?? null : null}
                showTrackId={showTrackIds}
                showClassLabel={showClassLabels}
              />
            ))}
          </div>
        )}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground">
        <div>
          Frame{" "}
          <span className="font-mono text-foreground">
            {currentFrameIdx ?? "—"}
          </span>
          <span className="px-1">/</span>
          <span className="font-mono">{framesByTime.length}</span>
          <span className="px-2">·</span>
          <span>{visibleDetections.length} boxes</span>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex cursor-pointer items-center gap-1.5 select-none">
            <input
              type="checkbox"
              checked={showClassLabels}
              onChange={(e) => setShowClassLabels(e.target.checked)}
            />
            Class labels
          </label>
          <label className="flex cursor-pointer items-center gap-1.5 select-none">
            <input
              type="checkbox"
              checked={showTrackIds}
              onChange={(e) => setShowTrackIds(e.target.checked)}
            />
            Track IDs
          </label>
        </div>
      </div>
    </div>
  );
}

function BboxOverlay({
  d,
  width,
  height,
  classMeta,
  showTrackId,
  showClassLabel,
}: {
  d: ClipOverlayDetection;
  width: number;
  height: number;
  classMeta: VdClass | null;
  showTrackId: boolean;
  showClassLabel: boolean;
}) {
  const color = d.track_id
    ? colorForTrack(d.track_id)
    : classMeta?.color_hex ?? FALLBACK_COLOR;
  const left = d.bbox.x * width;
  const top = d.bbox.y * height;
  const w = d.bbox.w * width;
  const h = d.bbox.h * height;
  const name = classMeta?.name ?? "unlabeled";
  const trackShort = d.track_id ? d.track_id.slice(0, 6) : null;

  return (
    <div
      className="absolute"
      style={{
        left,
        top,
        width: w,
        height: h,
        border: `2px solid ${color}`,
        boxShadow: "0 0 0 1px rgba(0,0,0,0.4) inset",
      }}
    >
      {(showClassLabel || (showTrackId && trackShort)) && (
        <div
          className="absolute -top-5 left-0 flex max-w-full items-center gap-1 truncate rounded-sm px-1 py-0.5 text-[10px] font-medium text-white"
          style={{ backgroundColor: color }}
        >
          {showClassLabel && <span className="truncate">{name}</span>}
          {showTrackId && trackShort && (
            <span className="font-mono opacity-90">#{trackShort}</span>
          )}
        </div>
      )}
    </div>
  );
}

// Deterministic colour from a uuid string — same track keeps the same hue
// across frames so the eye can follow a tracked object.
function colorForTrack(trackId: string): string {
  let h = 0;
  for (let i = 0; i < trackId.length; i++) {
    h = (h * 31 + trackId.charCodeAt(i)) >>> 0;
  }
  const hue = h % 360;
  return `hsl(${hue}, 75%, 55%)`;
}
