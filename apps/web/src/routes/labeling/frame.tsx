import { useCallback, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { ClassPicker } from "@/components/labeling/ClassPicker";
import { DetectionList } from "@/components/labeling/DetectionList";
import { KeymapModal } from "@/components/labeling/KeymapModal";
import { LabelingCanvas } from "@/components/labeling/LabelingCanvas";
import { useClasses } from "@/hooks/useClasses";
import { useSubclasses } from "@/hooks/useSubclasses";
import { useDetectionActions } from "@/hooks/useDetections";
import { fetchFrame, useFrame } from "@/hooks/useFrame";
import { useClip } from "@/hooks/useFrames";
import { useLabelingHotkeys } from "@/hooks/useLabelingHotkeys";
import { useLabelingStore } from "@/stores/labeling";

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

  useEffect(() => {
    resetFrame();
    // Tell SSE which frame is being edited so it won't refetch under us.
    setActiveFrame(fid);
    return () => setActiveFrame(null);
  }, [fid, resetFrame, setActiveFrame]);

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
  const onToggleKeymap = useCallback(() => setKeymapOpen((v) => !v), []);

  useLabelingHotkeys({
    actions,
    classes,
    subclasses,
    onPrev,
    onNext,
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
    <div className="flex h-[calc(100vh-7rem)] flex-col">
      <div className="flex items-center gap-3 border-b border-border pb-3">
        <button
          onClick={() => navigate("/labeling")}
          className="text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          ← Queue
        </button>
        <span className="truncate text-sm font-medium">
          {clip?.filename ?? "clip"}
        </span>
        <span className="text-sm text-muted-foreground">
          frame {frame.frame_index}
          {hasQueue && ` · ${queueIndex + 1}/${queueIds.length}`}
        </span>
        <div className="ml-auto flex gap-2">
          <Button size="sm" onClick={() => void actions.reviewFrame()}>
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
          <Button size="sm" variant="outline" onClick={() => navigate("/labeling")}>
            End
          </Button>
          <Button size="sm" variant="ghost" onClick={onToggleKeymap}>
            ?
          </Button>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 gap-3 pt-3">
        <aside className="w-56 shrink-0 overflow-y-auto">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Detections
          </h2>
          <DetectionList
            frame={frame}
            classes={classes}
            subclasses={subclasses}
          />
        </aside>
        <main className="min-w-0 flex-1 overflow-auto">
          <LabelingCanvas
            frame={frame}
            classes={classes}
            subclasses={subclasses}
            actions={actions}
          />
        </main>
        <aside className="w-52 shrink-0 overflow-y-auto">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Classes
          </h2>
          <ClassPicker
            classes={classes}
            subclasses={subclasses}
            frame={frame}
            actions={actions}
          />
        </aside>
      </div>

      <KeymapModal open={keymapOpen} onOpenChange={setKeymapOpen} />
    </div>
  );
}
