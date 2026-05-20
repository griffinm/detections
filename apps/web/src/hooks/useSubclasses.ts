import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Bbox } from "./useFrame";

const JSON_HEADERS = { "Content-Type": "application/json" };

export interface VdSubclass {
  id: string;
  class_id: string;
  name: string;
  color_hex: string;
  is_active: boolean;
  created_at: string;
}

export interface SubclassExample {
  id: string;
  subclass_id: string;
  detection_id: string;
  starred: boolean;
  created_at: string;
  bbox: Bbox;
  frame_id: string;
  image_url: string | null;
  crop_url: string | null;
}

export type GalleryInclude = "all" | "auto" | "reviewed";
export type GallerySort = "created_desc" | "reviewed_desc";

export interface DetectionGalleryItem {
  id: string;
  frame_id: string;
  clip_id: string;
  class_id: string | null;
  subclass_id: string | null;
  bbox: Bbox;
  image_url: string | null;
  crop_url: string | null;
  source: string;
  reviewed: boolean;
  reviewed_at: string | null;
  created_at: string;
}

export interface GalleryParams {
  include?: GalleryInclude;
  sort?: GallerySort;
  limit?: number;
}

function galleryQS(params: GalleryParams = {}): string {
  const qs = new URLSearchParams();
  if (params.include) qs.set("include", params.include);
  if (params.sort) qs.set("sort", params.sort);
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  const s = qs.toString();
  return s ? `?${s}` : "";
}

export interface SubclassInput {
  name: string;
  color_hex?: string;
  is_active?: boolean;
}

/** All sub-classes, or only those of `classId` when given. */
export function useSubclasses(classId?: string) {
  return useQuery<VdSubclass[]>({
    queryKey: classId ? ["subclasses", { classId }] : ["subclasses"],
    queryFn: async () => {
      const url = classId
        ? `/api/classes/${classId}/subclasses`
        : "/api/subclasses";
      const res = await fetch(url);
      if (!res.ok) throw new Error("Failed to fetch sub-classes");
      return res.json() as Promise<VdSubclass[]>;
    },
    staleTime: 5 * 60_000,
  });
}

export function useCreateSubclass(classId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: SubclassInput): Promise<VdSubclass> => {
      const res = await fetch(`/api/classes/${classId}/subclasses`, {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        throw Object.assign(new Error("Failed to create sub-class"), {
          status: res.status,
        });
      }
      return res.json() as Promise<VdSubclass>;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["subclasses"] }),
  });
}

export function useUpdateSubclass() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      id,
      ...body
    }: SubclassInput & { id: string }): Promise<VdSubclass> => {
      const res = await fetch(`/api/subclasses/${id}`, {
        method: "PATCH",
        headers: JSON_HEADERS,
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error("Failed to update sub-class");
      return res.json() as Promise<VdSubclass>;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["subclasses"] }),
  });
}

export function useDeleteSubclass() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string): Promise<void> => {
      const res = await fetch(`/api/subclasses/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Failed to deactivate sub-class");
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["subclasses"] }),
  });
}

export function useSubclassExamples(subclassId: string) {
  return useQuery<SubclassExample[]>({
    queryKey: ["subclass-examples", subclassId],
    queryFn: async () => {
      const res = await fetch(`/api/subclasses/${subclassId}/examples`);
      if (!res.ok) throw new Error("Failed to fetch examples");
      return res.json() as Promise<SubclassExample[]>;
    },
    enabled: Boolean(subclassId),
  });
}

export function useSubclassDetections(
  subclassId: string,
  params: GalleryParams = {},
) {
  return useQuery<DetectionGalleryItem[]>({
    queryKey: ["subclass-detections", subclassId, params],
    queryFn: async () => {
      const res = await fetch(
        `/api/subclasses/${subclassId}/detections${galleryQS(params)}`,
      );
      if (!res.ok) throw new Error("Failed to fetch tagged detections");
      return res.json() as Promise<DetectionGalleryItem[]>;
    },
    enabled: Boolean(subclassId),
  });
}

export function useDeleteExample(subclassId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (exampleId: string): Promise<void> => {
      const res = await fetch(
        `/api/subclasses/${subclassId}/examples/${exampleId}`,
        { method: "DELETE" },
      );
      if (!res.ok) throw new Error("Failed to remove example");
    },
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["subclass-examples", subclassId] }),
  });
}

export function useRescanSubclasses() {
  return useMutation({
    mutationFn: async (classId: string): Promise<void> => {
      const res = await fetch(`/api/classes/${classId}/rescan-subclasses`, {
        method: "POST",
      });
      if (!res.ok) throw new Error("Failed to start re-scan");
    },
  });
}
