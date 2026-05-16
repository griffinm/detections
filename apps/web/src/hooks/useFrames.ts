import { useQuery } from "@tanstack/react-query";
import { type ClipDetail } from "./useClips";

export interface Frame {
  id: string;
  clip_id: string;
  frame_index: number;
  timestamp_sec: number;
  path: string | null;
  image_url: string | null;
  width: number;
  height: number;
  kept: boolean;
  detect_status: string;
  created_at: string;
}

export function useClip(id: string) {
  return useQuery<ClipDetail>({
    queryKey: ["clips", id],
    queryFn: async () => {
      const res = await fetch(`/api/clips/${id}`);
      if (!res.ok) throw Object.assign(new Error("Clip not found"), { status: res.status });
      return res.json() as Promise<ClipDetail>;
    },
    enabled: Boolean(id),
  });
}

export function useClipFrames(id: string) {
  return useQuery<Frame[]>({
    queryKey: ["clips", id, "frames"],
    queryFn: async () => {
      const res = await fetch(`/api/clips/${id}/frames`);
      if (!res.ok) throw Object.assign(new Error("Failed to fetch frames"), { status: res.status });
      return res.json() as Promise<Frame[]>;
    },
    enabled: Boolean(id),
    staleTime: 30_000,
  });
}
