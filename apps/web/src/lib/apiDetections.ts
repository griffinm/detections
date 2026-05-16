import type { Bbox, Detection, FrameDetail } from "@/hooks/useFrame";

const JSON_HEADERS = { "Content-Type": "application/json" };

async function parse(res: Response): Promise<unknown> {
  if (!res.ok) {
    throw Object.assign(new Error(`Request failed (${res.status})`), {
      status: res.status,
    });
  }
  return res.status === 204 ? null : res.json();
}

export interface NewDetection {
  frame_id: string;
  bbox: Bbox;
  class_id?: string | null;
}

export interface DetectionPatchBody {
  bbox?: Bbox;
  class_id?: string | null;
  subclass_id?: string | null;
  reviewed?: boolean;
}

export async function createDetection(body: NewDetection): Promise<Detection> {
  return parse(
    await fetch("/api/detections", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(body),
    }),
  ) as Promise<Detection>;
}

export async function updateDetection(
  id: string,
  patch: DetectionPatchBody,
): Promise<Detection> {
  return parse(
    await fetch(`/api/detections/${id}`, {
      method: "PATCH",
      headers: JSON_HEADERS,
      body: JSON.stringify(patch),
    }),
  ) as Promise<Detection>;
}

export async function deleteDetection(id: string): Promise<void> {
  await parse(await fetch(`/api/detections/${id}`, { method: "DELETE" }));
}

export async function restoreDetection(id: string): Promise<Detection> {
  return parse(
    await fetch(`/api/detections/${id}/restore`, { method: "POST" }),
  ) as Promise<Detection>;
}

export async function reviewFrame(frameId: string): Promise<FrameDetail> {
  return parse(
    await fetch(`/api/frames/${frameId}/review`, { method: "POST" }),
  ) as Promise<FrameDetail>;
}

export async function promoteExample(
  id: string,
  subclassId: string,
): Promise<Detection> {
  return parse(
    await fetch(`/api/detections/${id}/promote-example`, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ subclass_id: subclassId }),
    }),
  ) as Promise<Detection>;
}
