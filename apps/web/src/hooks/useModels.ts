import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCursorInfiniteQuery, type Paginated } from "./usePaginated";

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

export type ModelKindFilter = "yolo" | "insightface" | "classifier";

export interface ModelFilters {
  kind?: ModelKindFilter;
  is_active?: boolean;
}

/** Cursor-paginated list. Filters are part of the query key so changing
 *  them tears down the old infinite query and starts a fresh page 1. */
export function useModelsInfinite(filters: ModelFilters = {}) {
  return useCursorInfiniteQuery<ModelVersion>({
    queryKey: ["models", filters],
    url: "/api/models",
    params: { kind: filters.kind, is_active: filters.is_active },
    limit: 50,
  });
}

/** First page of model versions (up to the API's `MAX_LIMIT` of 200), used
 *  by /metrics to resolve `model_version_id` → display name. A single-user
 *  install will never have enough versions to need to paginate this lookup;
 *  if that ever changes, swap consumers to a dedicated lookup endpoint. */
export function useModels() {
  return useQuery<ModelVersion[]>({
    queryKey: ["models", "first-page"],
    queryFn: async () => {
      const res = await fetch("/api/models?limit=200");
      if (!res.ok) throw new Error("Failed to fetch models");
      const page = (await res.json()) as Paginated<ModelVersion>;
      return page.items;
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
