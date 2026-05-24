import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCursorInfiniteQuery } from "./usePaginated";

const JSON_HEADERS = { "Content-Type": "application/json" };

export interface TrainingRun {
  id: string;
  kind: string;
  target_class_id: string | null;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  metrics: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
}

export interface TrainingRunDetail extends TrainingRun {
  log_tail: string | null;
}

/** Status buckets the API speaks; mirrors `_STATUS_BUCKETS` in the router and
 *  `statusBucket()` in the training page. */
export type TrainingRunStatusBucket = "running" | "done" | "failed" | "queued";

export interface TrainingRunFilters {
  kind?: "yolo" | "classifier";
  status?: TrainingRunStatusBucket;
}

/** Cursor-paginated list. Filters become part of the query key so changing
 *  them tears down the old infinite query and starts a fresh page 1. */
export function useTrainingRunsInfinite(filters: TrainingRunFilters = {}) {
  return useCursorInfiniteQuery<TrainingRun>({
    queryKey: ["trainingRuns", filters],
    url: "/api/training-runs",
    params: { kind: filters.kind, status: filters.status },
    limit: 50,
  });
}

export interface TrainingRunCounts {
  all: number;
  running: number;
  done: number;
  failed: number;
  queued: number;
}

/** Faceted counts for the stat strip — respects `kind`, ignores `status`. */
export function useTrainingRunCounts(filters: { kind?: TrainingRunFilters["kind"] } = {}) {
  return useQuery<TrainingRunCounts>({
    queryKey: ["trainingRuns", "counts", filters],
    queryFn: async () => {
      const qs = filters.kind ? `?kind=${filters.kind}` : "";
      const res = await fetch(`/api/training-runs/counts${qs}`);
      if (!res.ok) throw new Error("Failed to fetch training run counts");
      return res.json() as Promise<TrainingRunCounts>;
    },
  });
}

export function useTrainingRun(id: string | null) {
  return useQuery<TrainingRunDetail>({
    queryKey: ["trainingRuns", id],
    queryFn: async () => {
      const res = await fetch(`/api/training-runs/${id}`);
      if (!res.ok) throw new Error("Failed to fetch training run");
      return res.json() as Promise<TrainingRunDetail>;
    },
    enabled: Boolean(id),
  });
}

export interface StartTrainingBody {
  kind: "yolo" | "classifier";
  target_class_id?: string;
}

export function useStartTraining() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: StartTrainingBody): Promise<TrainingRun> => {
      const res = await fetch("/api/training-runs", {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error("Failed to start training");
      return res.json() as Promise<TrainingRun>;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["trainingRuns"] }),
  });
}

export function useCancelTraining() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (runId: string): Promise<TrainingRun> => {
      const res = await fetch(`/api/training-runs/${runId}/cancel`, {
        method: "POST",
      });
      if (!res.ok) throw new Error("Failed to cancel training run");
      return res.json() as Promise<TrainingRun>;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["trainingRuns"] }),
  });
}
