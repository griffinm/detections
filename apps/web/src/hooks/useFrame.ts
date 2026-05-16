import { useQuery } from "@tanstack/react-query";
import { type Frame } from "./useFrames";

export interface Bbox {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Detection {
  id: string;
  frame_id: string;
  class_id: string | null;
  subclass_id: string | null;
  bbox: Bbox;
  confidence_class: number | null;
  confidence_subclass: number | null;
  source: string;
  reviewed: boolean;
  reviewed_at: string | null;
  predicted_class_id: string | null;
  predicted_subclass_id: string | null;
  model_version_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface FrameDetail extends Frame {
  detections: Detection[];
}

export async function fetchFrame(frameId: string): Promise<FrameDetail> {
  const res = await fetch(`/api/frames/${frameId}`);
  if (!res.ok)
    throw Object.assign(new Error("Frame not found"), { status: res.status });
  return res.json() as Promise<FrameDetail>;
}

export function useFrame(frameId: string) {
  return useQuery<FrameDetail>({
    queryKey: ["frames", frameId],
    queryFn: () => fetchFrame(frameId),
    enabled: Boolean(frameId),
  });
}
