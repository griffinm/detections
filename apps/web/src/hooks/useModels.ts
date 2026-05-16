import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export interface ModelVersion {
  id: string;
  kind: string;
  name: string;
  weights_path: string;
  target_class_id: string | null;
  trained_on: number | null;
  metrics: Record<string, unknown> | null;
  is_active: boolean;
  created_at: string;
}

export function useModels() {
  return useQuery<ModelVersion[]>({
    queryKey: ["models"],
    queryFn: async () => {
      const res = await fetch("/api/models");
      if (!res.ok) throw new Error("Failed to fetch models");
      return res.json() as Promise<ModelVersion[]>;
    },
  });
}

export function useActivateModel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string): Promise<ModelVersion> => {
      const res = await fetch(`/api/models/${id}/activate`, { method: "POST" });
      if (!res.ok) throw new Error("Failed to activate model");
      return res.json() as Promise<ModelVersion>;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["models"] });
      void qc.invalidateQueries({ queryKey: ["classes"] });
    },
  });
}
