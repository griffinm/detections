import { useQuery } from "@tanstack/react-query";

export interface AccuracyPoint {
  period: string;
  model_version_id: string | null;
  n_reviewed: number;
  class_top1: number;
  subclass_top1: number | null;
  mean_confidence: number | null;
}

export interface ClassMetric {
  class_id: string;
  class_name: string;
  n_predicted: number;
  n_actual: number;
  precision: number | null;
  recall: number | null;
}

export interface CalibrationBin {
  bucket: number;
  mean_confidence: number;
  empirical_accuracy: number;
  count: number;
}

export interface CalibrationResponse {
  bins: CalibrationBin[];
  ece: number;
}

export interface MetricsSummary {
  clips: number;
  detections: number;
  reviewed: number;
  pending_review: number;
  last7d_class_accuracy: number | null;
}

export interface ReassignmentItem {
  detection_id: string;
  frame_id: string | null;
  clip_id: string | null;
  at: string;
  reason: string;
  from_class: string | null;
  to_class: string | null;
  from_subclass: string | null;
  to_subclass: string | null;
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Request failed (${res.status})`);
  return res.json() as Promise<T>;
}

export function useAccuracy(bucket: "day" | "week") {
  return useQuery<AccuracyPoint[]>({
    queryKey: ["metrics", "accuracy", bucket],
    queryFn: () => getJson(`/api/metrics/accuracy?bucket=${bucket}`),
  });
}

export function usePerClassMetrics() {
  return useQuery<ClassMetric[]>({
    queryKey: ["metrics", "per-class"],
    queryFn: () => getJson("/api/metrics/per-class"),
  });
}

export function useCalibration() {
  return useQuery<CalibrationResponse>({
    queryKey: ["metrics", "calibration"],
    queryFn: () => getJson("/api/metrics/calibration"),
  });
}

export function useMetricsSummary() {
  return useQuery<MetricsSummary>({
    queryKey: ["metrics", "summary"],
    queryFn: () => getJson("/api/metrics/summary"),
  });
}

export function useTracksAccuracy(bucket: "day" | "week") {
  return useQuery<AccuracyPoint[]>({
    queryKey: ["metrics", "tracks", bucket],
    queryFn: () => getJson(`/api/metrics/tracks?bucket=${bucket}`),
  });
}

export function useRecentChanges() {
  return useQuery<ReassignmentItem[]>({
    queryKey: ["metrics", "changes"],
    queryFn: () => getJson("/api/metrics/changes"),
  });
}
