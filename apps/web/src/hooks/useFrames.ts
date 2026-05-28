import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type Bbox } from "./useFrame";
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

export interface ClipOverlayDetection {
  frame_index: number;
  bbox: Bbox;
  class_id: string | null;
  subclass_id: string | null;
  track_id: string | null;
  confidence_class: number | null;
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

export function useClipFrames(id: string, enabled = true) {
  return useQuery<Frame[]>({
    queryKey: ["clips", id, "frames"],
    queryFn: async () => {
      const res = await fetch(`/api/clips/${id}/frames`);
      if (!res.ok) throw Object.assign(new Error("Failed to fetch frames"), { status: res.status });
      return res.json() as Promise<Frame[]>;
    },
    enabled: enabled && Boolean(id),
    staleTime: 30_000,
  });
}

export function useClipOverlay(id: string, enabled = true) {
  return useQuery<ClipOverlayDetection[]>({
    queryKey: ["clips", id, "overlay"],
    queryFn: async () => {
      const res = await fetch(`/api/clips/${id}/overlay`);
      if (!res.ok)
        throw Object.assign(new Error("Failed to fetch overlay detections"), {
          status: res.status,
        });
      return res.json() as Promise<ClipOverlayDetection[]>;
    },
    enabled: enabled && Boolean(id),
    staleTime: 30_000,
  });
}

export function useDeleteFrame() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id }: { id: string; clipId: string }): Promise<void> => {
      const res = await fetch(`/api/frames/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Failed to delete frame");
    },
    onSuccess: (_data, { clipId }) => {
      void qc.invalidateQueries({ queryKey: ["clips", clipId, "frames"] });
      void qc.invalidateQueries({ queryKey: ["clips", clipId] });
    },
  });
}
