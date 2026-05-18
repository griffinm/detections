import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export interface Clip {
  id: string;
  filename: string;
  sha256: string;
  size_bytes: number;
  duration_sec: number | null;
  fps: number | null;
  width: number | null;
  height: number | null;
  codec: string | null;
  status: string;
  error: string | null;
  ingested_at: string | null;
  processed_at: string | null;
  created_at: string;
  updated_at: string;
  thumbnail_url: string | null;
}

export interface ClipDetail extends Clip {
  frame_count: number;
}

interface Paginated<T> {
  items: T[];
  total: number;
  next_cursor: string | null;
}

export function useClipsList(params?: { status?: string }) {
  const search = params?.status ? `?status=${params.status}` : "";
  return useQuery<Paginated<Clip>>({
    queryKey: ["clips", params],
    queryFn: async () => {
      const res = await fetch(`/api/clips${search}`);
      if (!res.ok) throw Object.assign(new Error("Failed to fetch clips"), { status: res.status });
      return res.json() as Promise<Paginated<Clip>>;
    },
    staleTime: 5_000,
  });
}

export function useDeleteClip() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string): Promise<void> => {
      const res = await fetch(`/api/clips/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Failed to delete clip");
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["clips"] }),
  });
}
