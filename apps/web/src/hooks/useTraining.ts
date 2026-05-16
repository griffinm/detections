import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

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

export function useTrainingRuns() {
  return useQuery<TrainingRun[]>({
    queryKey: ["trainingRuns"],
    queryFn: async () => {
      const res = await fetch("/api/training-runs");
      if (!res.ok) throw new Error("Failed to fetch training runs");
      return res.json() as Promise<TrainingRun[]>;
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
