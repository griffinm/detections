import { useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  createDetection,
  deleteDetection,
  promoteExample,
  restoreDetection,
  reviewFrame,
  updateDetection,
} from "@/lib/apiDetections";
import { useLabelingStore, type DetectionPatch } from "@/stores/labeling";
import type { Bbox, Detection, FrameDetail } from "@/hooks/useFrame";

/**
 * Eager-save detection editing for one frame. Every edit hits the API
 * immediately and optimistically updates the React Query cache; undo/redo
 * re-issue the inverse request (plan: milestone 09).
 */
export function useDetectionActions(frameId: string) {
  const qc = useQueryClient();

  return useMemo(() => {
    const key = ["frames", frameId];
    const store = () => useLabelingStore.getState();

    const patchCache = (fn: (frame: FrameDetail) => FrameDetail) =>
      qc.setQueryData<FrameDetail>(key, (old) => (old ? fn(old) : old));

    const detectionById = (id: string): Detection | undefined =>
      qc.getQueryData<FrameDetail>(key)?.detections.find((d) => d.id === id);

    const resync = () => void qc.invalidateQueries({ queryKey: key });

    /** Apply an update to the cache + server (no history entry). */
    async function applyUpdate(id: string, patch: DetectionPatch): Promise<void> {
      patchCache((f) => ({
        ...f,
        detections: f.detections.map((d) =>
          d.id === id ? { ...d, ...patch } : d,
        ),
      }));
      try {
        await updateDetection(id, patch);
      } catch (err) {
        resync();
        toast.error("Failed to save change");
        throw err;
      }
    }

    return {
      /** Read the cached detection (used by hotkeys for the current state). */
      get: (id: string): Detection | undefined => detectionById(id),

      /** Move/resize or reclassify a detection. */
      update: async (id: string, patch: DetectionPatch): Promise<void> => {
        const current = detectionById(id);
        if (!current) return;
        const prev: DetectionPatch = {};
        if (patch.bbox !== undefined) prev.bbox = current.bbox;
        if (patch.class_id !== undefined) prev.class_id = current.class_id;
        if (patch.subclass_id !== undefined) prev.subclass_id = current.subclass_id;
        await applyUpdate(id, patch);
        store().pushEdit({ op: "update", id, prev, next: patch });
      },

      /** Promote a detection into its sub-class's kNN example set (`S`). */
      promote: async (id: string): Promise<void> => {
        const current = detectionById(id);
        if (!current) return;
        if (!current.subclass_id) {
          toast.error("Assign a sub-class before promoting to an example");
          return;
        }
        try {
          const updated = await promoteExample(id, current.subclass_id);
          patchCache((f) => ({
            ...f,
            detections: f.detections.map((d) => (d.id === id ? updated : d)),
          }));
          toast.success("Promoted to sub-class example");
        } catch {
          toast.error("Failed to promote example");
        }
      },

      /** Create a user-drawn box. */
      create: async (bbox: Bbox, classId: string | null): Promise<Detection> => {
        const detection = await createDetection({
          frame_id: frameId,
          bbox,
          class_id: classId,
        });
        patchCache((f) => ({ ...f, detections: [...f.detections, detection] }));
        store().pushEdit({ op: "create", id: detection.id });
        return detection;
      },

      /** Soft-delete a detection. */
      remove: async (id: string): Promise<void> => {
        patchCache((f) => ({
          ...f,
          detections: f.detections.filter((d) => d.id !== id),
        }));
        try {
          await deleteDetection(id);
        } catch (err) {
          resync();
          toast.error("Failed to delete detection");
          throw err;
        }
        store().pushEdit({ op: "delete", id });
      },

      /** "Save": mark every unreviewed detection on the frame reviewed. */
      reviewFrame: async (): Promise<void> => {
        try {
          qc.setQueryData<FrameDetail>(key, await reviewFrame(frameId));
        } catch {
          toast.error("Failed to save frame");
        }
      },

      undo: async (): Promise<void> => {
        // Peek, not pop: the stack entry only moves to redo once the inverse
        // request lands, so a failed call leaves history and server consistent.
        const entry = store().peekUndo();
        if (!entry) return;
        try {
          if (entry.op === "update") {
            await applyUpdate(entry.id, entry.prev);
          } else if (entry.op === "create") {
            await deleteDetection(entry.id);
            patchCache((f) => ({
              ...f,
              detections: f.detections.filter((d) => d.id !== entry.id),
            }));
          } else {
            const restored = await restoreDetection(entry.id);
            patchCache((f) => ({ ...f, detections: [...f.detections, restored] }));
          }
          store().commitUndo();
        } catch {
          resync();
          toast.error("Failed to undo");
        }
      },

      redo: async (): Promise<void> => {
        const entry = store().peekRedo();
        if (!entry) return;
        try {
          if (entry.op === "update") {
            await applyUpdate(entry.id, entry.next);
          } else if (entry.op === "create") {
            const restored = await restoreDetection(entry.id);
            patchCache((f) => ({ ...f, detections: [...f.detections, restored] }));
          } else {
            await deleteDetection(entry.id);
            patchCache((f) => ({
              ...f,
              detections: f.detections.filter((d) => d.id !== entry.id),
            }));
          }
          store().commitRedo();
        } catch {
          resync();
          toast.error("Failed to redo");
        }
      },
    };
  }, [frameId, qc]);
}
