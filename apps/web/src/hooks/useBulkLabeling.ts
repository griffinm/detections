import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { DetectionGalleryItem, GalleryInclude } from "./useSubclasses";

const JSON_HEADERS = { "Content-Type": "application/json" };

export type ConfidenceBucket = "high" | "med" | "low";

export interface PredictedGroup {
  class_id: string | null;
  class_name: string | null;
  predicted_subclass_id: string;
  predicted_subclass_name: string;
  confidence_bucket: ConfidenceBucket;
  count: number;
  sample_detection_ids: string[];
}

export interface ClipClassSummary {
  class_id: string | null;
  class_name: string | null;
  count: number;
}

export interface BulkReviewPayload {
  detection_ids: string[];
  class_id?: string | null;
  subclass_id?: string | null;
  reviewed?: boolean;
}

export interface BulkReviewResult {
  updated: number;
  skipped: number;
  audits_written: number;
  affected_frame_ids: string[];
}

export function usePredictedGroups(opts: {
  classId?: string;
  minConfidence?: number;
}) {
  const { classId, minConfidence } = opts;
  return useQuery<PredictedGroup[]>({
    queryKey: ["predicted-groups", classId ?? null, minConfidence ?? null],
    queryFn: async () => {
      const qs = new URLSearchParams();
      if (classId) qs.set("class_id", classId);
      if (minConfidence !== undefined)
        qs.set("min_confidence", String(minConfidence));
      const url = `/api/labeling/predicted-groups${qs.toString() ? `?${qs}` : ""}`;
      const res = await fetch(url);
      if (!res.ok) throw new Error("Failed to fetch predicted groups");
      return res.json() as Promise<PredictedGroup[]>;
    },
    staleTime: 5_000,
  });
}

export function usePredictedGroupDetections(opts: {
  predictedSubclassId: string | null;
  bucket?: ConfidenceBucket;
}) {
  const { predictedSubclassId, bucket } = opts;
  return useQuery<DetectionGalleryItem[]>({
    queryKey: ["predicted-group-detections", predictedSubclassId, bucket ?? null],
    queryFn: async () => {
      const qs = new URLSearchParams({
        predicted_subclass_id: predictedSubclassId as string,
      });
      if (bucket) qs.set("bucket", bucket);
      const res = await fetch(
        `/api/labeling/predicted-group-detections?${qs.toString()}`,
      );
      if (!res.ok) throw new Error("Failed to fetch group detections");
      return res.json() as Promise<DetectionGalleryItem[]>;
    },
    enabled: Boolean(predictedSubclassId),
    staleTime: 5_000,
  });
}

export function useClipDetections(opts: {
  clipId: string;
  classId?: string;
  subclassId?: string;
  include?: GalleryInclude;
}) {
  const { clipId, classId, subclassId, include } = opts;
  return useQuery<DetectionGalleryItem[]>({
    queryKey: [
      "clip-detections",
      clipId,
      classId ?? null,
      subclassId ?? null,
      include ?? "all",
    ],
    queryFn: async () => {
      const qs = new URLSearchParams();
      if (classId) qs.set("class_id", classId);
      if (subclassId) qs.set("subclass_id", subclassId);
      if (include) qs.set("include", include);
      const res = await fetch(
        `/api/clips/${clipId}/detections${qs.toString() ? `?${qs}` : ""}`,
      );
      if (!res.ok) throw new Error("Failed to fetch clip detections");
      return res.json() as Promise<DetectionGalleryItem[]>;
    },
    enabled: Boolean(clipId),
    staleTime: 5_000,
  });
}

export function useClipClassSummary(clipId: string) {
  return useQuery<ClipClassSummary[]>({
    queryKey: ["clip-class-summary", clipId],
    queryFn: async () => {
      const res = await fetch(`/api/clips/${clipId}/class-summary`);
      if (!res.ok) throw new Error("Failed to fetch class summary");
      return res.json() as Promise<ClipClassSummary[]>;
    },
    enabled: Boolean(clipId),
    staleTime: 30_000,
  });
}

export function useBulkApply() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: BulkReviewPayload): Promise<BulkReviewResult> => {
      const res = await fetch("/api/labeling/bulk-review", {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        throw Object.assign(new Error("Bulk apply failed"), {
          status: res.status,
        });
      }
      return res.json() as Promise<BulkReviewResult>;
    },
    onSuccess: (result) => {
      // Anything that lists detections, queues, or per-frame state is now stale.
      qc.invalidateQueries({ queryKey: ["predicted-groups"] });
      qc.invalidateQueries({ queryKey: ["predicted-group-detections"] });
      qc.invalidateQueries({ queryKey: ["clip-detections"] });
      qc.invalidateQueries({ queryKey: ["clip-class-summary"] });
      qc.invalidateQueries({ queryKey: ["labeling-queue"] });
      qc.invalidateQueries({ queryKey: ["class-detections"] });
      qc.invalidateQueries({ queryKey: ["subclass-detections"] });
      // SSE handles per-frame refresh, but invalidate too in case the open
      // frame isn't subscribed (e.g. tab in background).
      for (const fid of result.affected_frame_ids) {
        qc.invalidateQueries({ queryKey: ["frames", fid] });
      }
    },
  });
}
