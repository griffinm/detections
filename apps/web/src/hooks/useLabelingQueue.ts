import { useQuery } from "@tanstack/react-query";

export interface QueueItem {
  frame_id: string;
  clip_id: string;
  clip_filename: string;
  frame_index: number;
  image_url: string | null;
  unreviewed_count: number;
  min_confidence: number | null;
}

export function useLabelingQueue(strategy = "lowconf", classId?: string) {
  return useQuery<QueueItem[]>({
    queryKey: ["labeling-queue", strategy, classId ?? null],
    queryFn: async () => {
      const params = new URLSearchParams({ strategy });
      if (classId) params.set("class_id", classId);
      const res = await fetch(`/api/labeling/queue?${params.toString()}`);
      if (!res.ok) throw new Error("Failed to fetch labeling queue");
      return res.json() as Promise<QueueItem[]>;
    },
    staleTime: 10_000,
  });
}
