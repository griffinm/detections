import { useMutation, useQuery } from "@tanstack/react-query";

const JSON_HEADERS = { "Content-Type": "application/json" };

export interface DirUsage {
  name: string;
  path: string;
  bytes: number;
  file_count: number;
}

export interface DiskUsage {
  dirs: DirUsage[];
  total_bytes: number;
  free_bytes: number;
}

export function useDiskUsage() {
  return useQuery<DiskUsage>({
    queryKey: ["system", "disk"],
    queryFn: async () => {
      const res = await fetch("/api/system/disk");
      if (!res.ok) throw new Error("Failed to fetch disk usage");
      return res.json() as Promise<DiskUsage>;
    },
    staleTime: 30_000,
  });
}

export interface PurgeResult {
  enqueued: boolean;
  older_than_days: number;
}

export function usePurgeFrames() {
  return useMutation({
    mutationFn: async (olderThanDays: number): Promise<PurgeResult> => {
      const res = await fetch("/api/system/purge-frames", {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify({ older_than_days: olderThanDays }),
      });
      if (!res.ok) throw new Error("Failed to enqueue purge");
      return res.json() as Promise<PurgeResult>;
    },
  });
}
