import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ClassPicker } from "@/components/labeling/ClassPicker";
import { DetectionCrop } from "@/components/labeling/DetectionCrop";
import { DetectionList } from "@/components/labeling/DetectionList";
import { KeymapModal } from "@/components/labeling/KeymapModal";
import { LabelingCanvas } from "@/components/labeling/LabelingCanvas";
import { cn } from "@/lib/utils";
import { useClasses } from "@/hooks/useClasses";
import { useSubclasses } from "@/hooks/useSubclasses";
import { useDetectionActions } from "@/hooks/useDetections";
import { fetchFrame, useFrame } from "@/hooks/useFrame";
import { useClip } from "@/hooks/useFrames";
import { useLabelingHotkeys } from "@/hooks/useLabelingHotkeys";
import { useLabelingStore } from "@/stores/labeling";

const PANEL_HEADING =
  "mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground";

export function LabelingFrame() {
  const { fid = "" } = useParams<{ fid: string }>();
  const navigate = useNavigate();

  const { data: frame, isPending, isError } = useFrame(fid);
  const { data: classes = [] } = useClasses();
  const { data: subclasses = [] } = useSubclasses();
  const { data: clip } = useClip(frame?.clip_id ?? "");
  const actions = useDetectionActions(fid);

  const queueIds = useLabelingStore((s) => s.queueIds);
  const resetFrame = useLabelingStore((s) => s.resetFrame);
  const setActiveFrame = useLabelingStore((s) => s.setActiveFrame);
  const [keymapOpen, setKeymapOpen] = useState(false);
  // Which panel the stacked (mobile) layout shows below the canvas.
  const [mobileTab, setMobileTab] = useState<"detections" | "classes">(
    "detections",
  );

  useEffect(() => {
    resetFrame();
    // Tell SSE which frame is being edited so it won't refetch under us.
    setActiveFrame(fid);
    return () => setActiveFrame(null);
  }, [fid, resetFrame, setActiveFrame]);

  // Select the first detection once per frame load. Keyed on fid (not `frame`)
  // so eager-save cache updates don't yank selection back to the top.
  const initializedFid = useRef<string | null>(null);
  useEffect(() => {
    if (!frame || initializedFid.current === fid) return;
    initializedFid.current = fid;
    if (frame.detections.length > 0) {
      useLabelingStore.getState().select(frame.detections[0].id);
    }
  }, [fid, frame]);

  const queueIndex = queueIds.indexOf(fid);

  // Warm the next queued frame so J-navigation lands instantly.
  const qc = useQueryClient();
  useEffect(() => {
    const nextId = queueIndex >= 0 ? queueIds[queueIndex + 1] : undefined;
    if (!nextId) return;
    void qc.prefetchQuery({
      queryKey: ["frames", nextId],
      queryFn: () => fetchFrame(nextId),
    });
  }, [qc, queueIds, queueIndex]);

  const goTo = useCallback(
    (index: number) => {
      if (index >= 0 && index < queueIds.length) {
        navigate(`/labeling/${queueIds[index]}`);
      }
    },
    [queueIds, navigate],
  );
  const onPrev = useCallback(() => goTo(queueIndex - 1), [goTo, queueIndex]);
  const onNext = useCallback(() => goTo(queueIndex + 1), [goTo, queueIndex]);
  const onSaveNext = useCallback(async () => {
    await actions.reviewFrame();
    onNext();
  }, [actions, onNext]);
  const onToggleKeymap = useCallback(() => setKeymapOpen((v) => !v), []);

  const detectionIds = useMemo(
    () => frame?.detections.map((d) => d.id) ?? [],
    [frame],
  );

  useLabelingHotkeys({
    actions,
    classes,
    subclasses,
    detectionIds,
    onPrev,
    onNext,
    onSaveNext,
    onToggleKeymap,
  });

  if (isError) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
        Frame not found.
      </div>
    );
  }
  if (isPending || !frame) {
    return <div className="text-sm text-muted-foreground">Loading frame…</div>;
  }

  const hasQueue = queueIndex >= 0;

  return (
    <div className="flex flex-col lg:h-[calc(100vh-7rem)]">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border pb-3">
        <button
          onClick={() => navigate("/labeling")}
          className="flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ChevronLeft className="h-4 w-4" /> Queue
        </button>
        <span className="min-w-0 max-w-[40vw] truncate text-sm font-medium">
          {clip?.filename ?? "clip"}
        </span>
        <span className="text-sm text-muted-foreground">
          frame {frame.frame_index}
          {hasQueue && ` · ${queueIndex + 1}/${queueIds.length}`}
        </span>
        <div className="ml-auto flex flex-wrap gap-2">
          <Button size="sm" onClick={() => void onSaveNext()}>
            Save &amp; Next
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => void actions.reviewFrame()}
          >
            Save
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={onNext}
            disabled={!hasQueue || queueIndex >= queueIds.length - 1}
          >
            Skip
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => navigate("/labeling")}
          >
            End
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="hidden sm:inline-flex"
            onClick={onToggleKeymap}
            aria-label="Keyboard shortcuts"
          >
            ?
          </Button>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-3 pt-3 lg:flex-row">
        {/* Detections — fixed left panel on desktop. */}
        <aside className="hidden w-56 shrink-0 overflow-y-auto lg:block">
          <h2 className={PANEL_HEADING}>Detections</h2>
          <DetectionList
            frame={frame}
            classes={classes}
            subclasses={subclasses}
          />
        </aside>

        <main className="min-w-0 flex-1 lg:overflow-auto">
          <LabelingCanvas
            frame={frame}
            classes={classes}
            subclasses={subclasses}
            actions={actions}
          />
          <DetectionCrop frame={frame} />
        </main>

        {/* Classes — fixed right panel on desktop. */}
        <aside className="hidden w-52 shrink-0 overflow-y-auto lg:block">
          <h2 className={PANEL_HEADING}>Classes</h2>
          <ClassPicker
            classes={classes}
            subclasses={subclasses}
            frame={frame}
            actions={actions}
          />
        </aside>

        {/* Stacked, tabbed panels below the canvas on small screens. */}
        <div className="lg:hidden">
          <div className="flex border-b border-border">
            {(["detections", "classes"] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setMobileTab(tab)}
                className={cn(
                  "-mb-px border-b-2 px-3 py-2 text-sm font-medium capitalize transition-colors",
                  mobileTab === tab
                    ? "border-primary text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground",
                )}
              >
                {tab}
              </button>
            ))}
          </div>
          <div className="pt-3">
            {mobileTab === "detections" ? (
              <DetectionList
                frame={frame}
                classes={classes}
                subclasses={subclasses}
              />
            ) : (
              <ClassPicker
                classes={classes}
                subclasses={subclasses}
                frame={frame}
                actions={actions}
              />
            )}
          </div>
        </div>
      </div>

      <KeymapModal open={keymapOpen} onOpenChange={setKeymapOpen} />
    </div>
  );
}
