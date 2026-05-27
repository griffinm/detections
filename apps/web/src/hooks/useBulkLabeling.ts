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

export type EmbeddingKind = "face" | "object" | "mixed";

export interface SimilarityCluster {
  seed_id: string;
  avg_distance: number;
  members: DetectionGalleryItem[];
}

export interface SimilarityClustersResponse {
  clusters: SimilarityCluster[];
  embedding_kind: EmbeddingKind;
  pool_size: number;
  pool_truncated: boolean;
  remaining: number;
}

export function useSimilarityClusters(opts: {
  classId: string | undefined;
  clusterSize?: number;
  maxClusters?: number;
}) {
  const { classId, clusterSize, maxClusters } = opts;
  return useQuery<SimilarityClustersResponse>({
    queryKey: [
      "similarity-clusters",
      classId ?? null,
      clusterSize ?? null,
      maxClusters ?? null,
    ],
    queryFn: async () => {
      const qs = new URLSearchParams({ class_id: classId as string });
      if (clusterSize !== undefined) qs.set("cluster_size", String(clusterSize));
      if (maxClusters !== undefined) qs.set("max_clusters", String(maxClusters));
      const res = await fetch(`/api/labeling/similarity-clusters?${qs}`);
      if (!res.ok) throw new Error("Failed to fetch similarity clusters");
      return res.json() as Promise<SimilarityClustersResponse>;
    },
    enabled: Boolean(classId),
    staleTime: 5_000,
  });
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
      qc.invalidateQueries({ queryKey: ["similarity-clusters"] });
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

export interface TrackRead {
  id: string;
  clip_id: string;
  class_id: string | null;
  subclass_id: string | null;
  predicted_class_id: string | null;
  predicted_subclass_id: string | null;
  confidence_class: number | null;
  confidence_subclass: number | null;
  n_detections: number;
  first_frame_index: number;
  last_frame_index: number;
  source: "tracker" | "user";
  model_version_id: string | null;
  reviewed: boolean;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface TrackMember {
  id: string;
  frame_id: string;
  frame_index: number;
  bbox: { x: number; y: number; w: number; h: number };
  class_id: string | null;
  subclass_id: string | null;
  confidence_class: number | null;
  confidence_subclass: number | null;
  source: "model" | "user";
  reviewed: boolean;
}

export interface TrackDetail {
  track: TrackRead;
  members: TrackMember[];
}

export interface BulkReviewTracksPayload {
  track_ids: string[];
  class_id?: string | null;
  subclass_id?: string | null;
  reviewed?: boolean;
}

export interface BulkReviewTracksResult {
  updated_tracks: number;
  updated_detections: number;
  skipped_tracks: number;
  audits_written: number;
  affected_frame_ids: string[];
  affected_track_ids: string[];
}

export function useClipTracks(clipId: string | undefined) {
  return useQuery<TrackRead[]>({
    queryKey: ["clip-tracks", clipId ?? null],
    queryFn: async () => {
      const res = await fetch(`/api/clips/${clipId}/tracks`);
      if (!res.ok) throw new Error("Failed to fetch clip tracks");
      return res.json() as Promise<TrackRead[]>;
    },
    enabled: Boolean(clipId),
    staleTime: 5_000,
  });
}

export function useTrack(trackId: string | undefined) {
  return useQuery<TrackDetail>({
    queryKey: ["tracks", trackId ?? null],
    queryFn: async () => {
      const res = await fetch(`/api/tracks/${trackId}`);
      if (!res.ok) throw new Error("Failed to fetch track");
      return res.json() as Promise<TrackDetail>;
    },
    enabled: Boolean(trackId),
    staleTime: 5_000,
  });
}

function _invalidateTrackCaches(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["clip-tracks"] });
  qc.invalidateQueries({ queryKey: ["tracks"] });
  qc.invalidateQueries({ queryKey: ["clip-detections"] });
  qc.invalidateQueries({ queryKey: ["clip-class-summary"] });
  qc.invalidateQueries({ queryKey: ["labeling-queue"] });
  qc.invalidateQueries({ queryKey: ["metrics"] });
}

export function useTrackPatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (args: {
      trackId: string;
      patch: { class_id?: string | null; subclass_id?: string | null; reviewed?: boolean };
    }) => {
      const res = await fetch(`/api/tracks/${args.trackId}`, {
        method: "PATCH",
        headers: JSON_HEADERS,
        body: JSON.stringify(args.patch),
      });
      if (!res.ok) throw new Error("Failed to update track");
      return res.json() as Promise<{
        track: TrackRead;
        updated_detections: number;
        audits_written: number;
        affected_frame_ids: string[];
      }>;
    },
    onSuccess: (result) => {
      _invalidateTrackCaches(qc);
      for (const fid of result.affected_frame_ids) {
        qc.invalidateQueries({ queryKey: ["frames", fid] });
      }
    },
  });
}

export function useTrackSplit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (args: { trackId: string; pivot_frame_index: number }) => {
      const res = await fetch(`/api/tracks/${args.trackId}/split`, {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify({ pivot_frame_index: args.pivot_frame_index }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail ?? "Split failed");
      }
      return res.json() as Promise<TrackDetail>;
    },
    onSuccess: () => _invalidateTrackCaches(qc),
  });
}

export function useTrackMerge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (args: { trackId: string; other_track_id: string }) => {
      const res = await fetch(`/api/tracks/${args.trackId}/merge`, {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify({ other_track_id: args.other_track_id }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail ?? "Merge failed");
      }
      return res.json() as Promise<TrackDetail>;
    },
    onSuccess: () => _invalidateTrackCaches(qc),
  });
}

export function useTrackDelete() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (trackId: string) => {
      const res = await fetch(`/api/tracks/${trackId}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Failed to delete track");
    },
    onSuccess: () => _invalidateTrackCaches(qc),
  });
}

export function useBulkApplyTracks() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (
      payload: BulkReviewTracksPayload,
    ): Promise<BulkReviewTracksResult> => {
      const res = await fetch("/api/labeling/bulk-review-tracks", {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        throw Object.assign(new Error("Bulk apply failed"), { status: res.status });
      }
      return res.json() as Promise<BulkReviewTracksResult>;
    },
    onSuccess: (result) => {
      _invalidateTrackCaches(qc);
      for (const fid of result.affected_frame_ids) {
        qc.invalidateQueries({ queryKey: ["frames", fid] });
      }
    },
  });
}
