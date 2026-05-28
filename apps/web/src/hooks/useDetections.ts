import { useMemo } from "react";
import {
  useMutation,
  useQueryClient,
  type InfiniteData,
  type QueryClient,
  type QueryKey,
} from "@tanstack/react-query";
import { toast } from "sonner";
import {
  createDetection,
  deleteDetection,
  predictDetection,
  promoteExample,
  restoreDetection,
  reviewFrame,
  updateDetection,
} from "@/lib/apiDetections";
import { useLabelingStore, type DetectionPatch } from "@/stores/labeling";
import type { Bbox, Detection, FrameDetail } from "@/hooks/useFrame";
import { useCursorInfiniteQuery, type Paginated } from "./usePaginated";
import type {
  DetectionGalleryItem,
  GalleryInclude,
  GallerySort,
} from "./useSubclasses";

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

      /** Ask the backend to guess this user-drawn box's class via YOLO.
       *  Fire-and-forget — the prediction arrives over SSE and invalidates
       *  this frame's cache. Errors are silent: a missed guess is fine. */
      predict: async (id: string): Promise<void> => {
        try {
          await predictDetection(id);
        } catch {
          // Swallow — the box is already saved; a failed predict is benign.
        }
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

// ---------------------------------------------------------------------------
// Gallery-level detection mutations
//
// Used by the per-tile actions on `/classes/:id` (Untag / Delete + undo).
// These work against the infinite-paged caches keyed by
// ["subclass-detections", …] and ["class-detections", …]. The labeling-UI
// hooks above operate on a single frame cache and aren't relevant here.
// ---------------------------------------------------------------------------

type GalleryCache = InfiniteData<Paginated<DetectionGalleryItem>, string | null>;
type GallerySnapshot = Array<[QueryKey, GalleryCache | undefined]>;

const GALLERY_FAMILIES: ReadonlyArray<QueryKey> = [
  ["subclass-detections"],
  ["class-detections"],
  // The Quick-review queue at `/labeling/quick` shares the same item shape and
  // benefits from the same optimistic splice.
  ["detections-queue"],
];

function spliceDetectionFromGalleries(
  qc: QueryClient,
  detectionId: string,
): GallerySnapshot {
  const snapshots: GallerySnapshot = [];
  for (const family of GALLERY_FAMILIES) {
    for (const [key, data] of qc.getQueriesData<GalleryCache>({
      queryKey: family,
    })) {
      snapshots.push([key, data]);
      if (!data) continue;
      let removed = 0;
      const pages = data.pages.map((p) => {
        const items = p.items.filter((it) => it.id !== detectionId);
        const drop = p.items.length - items.length;
        if (!drop) return p;
        removed += drop;
        return { ...p, items, total: Math.max(0, p.total - drop) };
      });
      if (removed > 0) qc.setQueryData<GalleryCache>(key, { ...data, pages });
    }
  }
  return snapshots;
}

function restoreGalleries(qc: QueryClient, snapshot: GallerySnapshot): void {
  for (const [key, data] of snapshot) qc.setQueryData(key, data);
}

async function invalidateDetectionGalleries(qc: QueryClient): Promise<void> {
  await Promise.all([
    qc.invalidateQueries({ queryKey: ["subclass-detections"] }),
    qc.invalidateQueries({ queryKey: ["class-detections"] }),
    qc.invalidateQueries({ queryKey: ["detections-queue"] }),
    // Soft-delete + untag both change what shows on the Examples tab too
    // (deleted_at filter + sub-class membership), so refresh those caches.
    qc.invalidateQueries({ queryKey: ["subclass-examples"] }),
    qc.invalidateQueries({ queryKey: ["class-examples"] }),
  ]);
}

// ---------------------------------------------------------------------------
// Quick-review queue + on-screen edits
// ---------------------------------------------------------------------------

export interface DetectionQueueParams {
  include?: GalleryInclude;
  sort?: GallerySort;
  classId?: string;
}

/** Paginated infinite-scroll of detections — drives the `/labeling/quick`
 *  one-at-a-time review screen. Default `include=auto` mirrors the backend. */
export function useDetectionsQueue(params: DetectionQueueParams = {}) {
  const { include = "auto", sort = "created_desc", classId } = params;
  return useCursorInfiniteQuery<DetectionGalleryItem>({
    queryKey: ["detections-queue", { include, sort, classId: classId ?? null }],
    url: "/api/detections",
    params: { include, sort, class_id: classId },
    limit: 60,
  });
}

/** Generic PATCH used by the Quick-review screen's class/subclass dropdowns
 *  and the Confirm button. Optimistically splices the row out of gallery
 *  caches *only when* `reviewed: true` is in the patch — otherwise the row
 *  should stay visible while the user keeps tweaking the same detection. */
export function usePatchDetection() {
  const qc = useQueryClient();
  return useMutation<
    void,
    Error,
    { id: string; patch: Parameters<typeof updateDetection>[1] },
    { snapshot: GallerySnapshot | null }
  >({
    mutationFn: async ({ id, patch }) => {
      await updateDetection(id, patch);
    },
    onMutate: ({ id, patch }) => ({
      snapshot: patch.reviewed === true
        ? spliceDetectionFromGalleries(qc, id)
        : null,
    }),
    onError: (_err, _vars, ctx) => {
      if (ctx?.snapshot) restoreGalleries(qc, ctx.snapshot);
    },
    onSettled: () => invalidateDetectionGalleries(qc),
  });
}

/** Clear `subclass_id` and mark `reviewed=true` so the next kNN sweep can't
 *  re-tag the detection. Optimistically removes the tile from every loaded
 *  gallery and rolls back on error. */
export function useUntagDetection() {
  const qc = useQueryClient();
  return useMutation<void, Error, { id: string }, { snapshot: GallerySnapshot }>(
    {
      mutationFn: async ({ id }) => {
        await updateDetection(id, { subclass_id: null, reviewed: true });
      },
      onMutate: ({ id }) => ({ snapshot: spliceDetectionFromGalleries(qc, id) }),
      onError: (_err, _vars, ctx) => {
        if (ctx) restoreGalleries(qc, ctx.snapshot);
      },
      onSettled: () => invalidateDetectionGalleries(qc),
    },
  );
}

/** Soft-delete the detection (sets `deleted_at`). Optimistic gallery splice. */
export function useDeleteDetectionGallery() {
  const qc = useQueryClient();
  return useMutation<void, Error, { id: string }, { snapshot: GallerySnapshot }>(
    {
      mutationFn: async ({ id }) => deleteDetection(id),
      onMutate: ({ id }) => ({ snapshot: spliceDetectionFromGalleries(qc, id) }),
      onError: (_err, _vars, ctx) => {
        if (ctx) restoreGalleries(qc, ctx.snapshot);
      },
      onSettled: () => invalidateDetectionGalleries(qc),
    },
  );
}

/** Undo a gallery delete. Caches are refetched rather than surgically
 *  reinserted — the row's sort position depends on `created_at` /
 *  `reviewed_at` and is cheaper to re-query than to recompute client-side. */
export function useRestoreDetectionGallery() {
  const qc = useQueryClient();
  return useMutation<void, Error, { id: string }>({
    mutationFn: async ({ id }) => {
      await restoreDetection(id);
    },
    onSettled: () => invalidateDetectionGalleries(qc),
  });
}

/** Undo an untag: re-assigns the prior sub-class and prior `reviewed` flag.
 *  Same refetch-rather-than-reinsert rationale as
 *  {@link useRestoreDetectionGallery}. */
export function useRetagDetectionGallery() {
  const qc = useQueryClient();
  return useMutation<
    void,
    Error,
    { id: string; subclass_id: string; reviewed: boolean }
  >({
    mutationFn: async ({ id, subclass_id, reviewed }) => {
      await updateDetection(id, { subclass_id, reviewed });
    },
    onSettled: () => invalidateDetectionGalleries(qc),
  });
}
