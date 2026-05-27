import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useLabelingStore } from "@/stores/labeling";

interface SseEvent {
  type: string;
  clip_id?: string;
  frame_id?: string;
  frame_count?: number;
  training_run_id?: string;
  track_id?: string;
  new_track_id?: string;
  absorbed_track_id?: string;
}

export function useLiveEvents() {
  const qc = useQueryClient();

  useEffect(() => {
    const es = new EventSource("/api/stream/events");

    es.onmessage = (ev: MessageEvent<string>) => {
      try {
        const e = JSON.parse(ev.data) as SseEvent;
        switch (e.type) {
          case "clip.created":
            void qc.invalidateQueries({ queryKey: ["clips"] });
            break;
          case "clip.status":
            void qc.invalidateQueries({ queryKey: ["clips"] });
            if (e.clip_id) {
              void qc.invalidateQueries({ queryKey: ["clips", e.clip_id] });
              // Cover the re-extract path: the old frames must drop from the
              // grid the moment status flips back to `extracting`.
              void qc.invalidateQueries({
                queryKey: ["clips", e.clip_id, "frames"],
              });
            }
            break;
          case "clip.done":
            void qc.invalidateQueries({ queryKey: ["clips"] });
            if (e.clip_id) {
              void qc.invalidateQueries({ queryKey: ["clips", e.clip_id] });
              void qc.invalidateQueries({ queryKey: ["clips", e.clip_id, "frames"] });
            }
            break;
          case "clip.deleted":
            void qc.invalidateQueries({ queryKey: ["clips"] });
            void qc.invalidateQueries({ queryKey: ["system", "disk"] });
            break;
          case "frame.detect.done":
            if (e.clip_id) void qc.invalidateQueries({ queryKey: ["clips", e.clip_id, "frames"] });
            if (e.frame_id) void qc.invalidateQueries({ queryKey: ["frames", e.frame_id] });
            break;
          case "frame.updated": {
            if (e.clip_id) void qc.invalidateQueries({ queryKey: ["clips", e.clip_id, "frames"] });
            // The frame open in the labeling UI is kept current by eager-save;
            // refetching it here would clobber edits still in flight. Other
            // frames still refresh so their review badges stay accurate.
            const activeFrame = useLabelingStore.getState().activeFrameId;
            if (e.frame_id && e.frame_id !== activeFrame) {
              void qc.invalidateQueries({ queryKey: ["frames", e.frame_id] });
            }
            void qc.invalidateQueries({ queryKey: ["labeling-queue"] });
            void qc.invalidateQueries({ queryKey: ["metrics"] });
            break;
          }
          case "training_run.update":
            // The list query is infinite-paged via useCursorInfiniteQuery; this
            // invalidation refetches every loaded page so visible row badges
            // catch the status transition. Keyset cursors are stable across
            // inserts, so this is correct even when a new run lands at the
            // top mid-scroll. With maxPages=10 and infrequent status events,
            // the refetch volume is small enough to not warrant page-1-only
            // surgery (which TanStack v5 doesn't support cleanly anyway).
            void qc.invalidateQueries({ queryKey: ["trainingRuns"] });
            if (e.training_run_id) {
              void qc.invalidateQueries({
                queryKey: ["trainingRuns", e.training_run_id],
              });
            }
            void qc.invalidateQueries({ queryKey: ["metrics"] });
            break;
          case "model.active_changed":
            void qc.invalidateQueries({ queryKey: ["models"] });
            void qc.invalidateQueries({ queryKey: ["classes"] });
            void qc.invalidateQueries({ queryKey: ["metrics"] });
            break;
          case "clip.tracks_updated":
            // Stage A worker publishes this when a track-level vote changes;
            // Stage B uses it as the catch-all "tracks in this clip moved" hint.
            if (e.clip_id) {
              void qc.invalidateQueries({ queryKey: ["clip-tracks", e.clip_id] });
            }
            void qc.invalidateQueries({ queryKey: ["tracks"] });
            void qc.invalidateQueries({ queryKey: ["metrics"] });
            break;
          case "track.updated":
          case "track.split":
          case "track.merged":
          case "track.deleted":
            if (e.clip_id) {
              void qc.invalidateQueries({ queryKey: ["clip-tracks", e.clip_id] });
            }
            void qc.invalidateQueries({ queryKey: ["tracks"] });
            if (e.track_id) {
              void qc.invalidateQueries({ queryKey: ["tracks", e.track_id] });
            }
            if (e.new_track_id) {
              void qc.invalidateQueries({ queryKey: ["tracks", e.new_track_id] });
            }
            if (e.absorbed_track_id) {
              void qc.invalidateQueries({
                queryKey: ["tracks", e.absorbed_track_id],
              });
            }
            void qc.invalidateQueries({ queryKey: ["metrics"] });
            break;
        }
      } catch {
        // ignore parse errors
      }
    };

    es.onerror = () => {
      // EventSource auto-reconnects
    };

    return () => {
      es.close();
    };
  }, [qc]);
}
