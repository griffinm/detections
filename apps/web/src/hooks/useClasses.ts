import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  DetectionGalleryItem,
  GalleryParams,
  SubclassExample,
} from "./useSubclasses";

const JSON_HEADERS = { "Content-Type": "application/json" };

function galleryQS(params: GalleryParams = {}): string {
  const qs = new URLSearchParams();
  if (params.include) qs.set("include", params.include);
  if (params.sort) qs.set("sort", params.sort);
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  const s = qs.toString();
  return s ? `?${s}` : "";
}

export interface VdClass {
  id: string;
  name: string;
  source: string;
  yolo_class_index: number | null;
  color_hex: string;
  is_active: boolean;
  created_at: string;
}

export function useClasses() {
  return useQuery<VdClass[]>({
    queryKey: ["classes"],
    queryFn: async () => {
      const res = await fetch("/api/classes");
      if (!res.ok) throw new Error("Failed to fetch classes");
      return res.json() as Promise<VdClass[]>;
    },
    staleTime: 5 * 60_000,
  });
}

export interface ClassInput {
  name: string;
  color_hex?: string;
  is_active?: boolean;
}

export function useCreateClass() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: ClassInput): Promise<VdClass> => {
      const res = await fetch("/api/classes", {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        throw Object.assign(new Error("Failed to create class"), {
          status: res.status,
        });
      }
      return res.json() as Promise<VdClass>;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["classes"] }),
  });
}

export function useUpdateClass() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      id,
      ...body
    }: ClassInput & { id: string }): Promise<VdClass> => {
      const res = await fetch(`/api/classes/${id}`, {
        method: "PATCH",
        headers: JSON_HEADERS,
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error("Failed to update class");
      return res.json() as Promise<VdClass>;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["classes"] }),
  });
}

export function useDeleteClass() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string): Promise<void> => {
      const res = await fetch(`/api/classes/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Failed to deactivate class");
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["classes"] }),
  });
}

export function useClassDetections(classId: string, params: GalleryParams = {}) {
  return useQuery<DetectionGalleryItem[]>({
    queryKey: ["class-detections", classId, params],
    queryFn: async () => {
      const res = await fetch(
        `/api/classes/${classId}/detections${galleryQS(params)}`,
      );
      if (!res.ok) throw new Error("Failed to fetch tagged detections");
      return res.json() as Promise<DetectionGalleryItem[]>;
    },
    enabled: Boolean(classId),
  });
}

export function useClassExamples(classId: string) {
  return useQuery<SubclassExample[]>({
    queryKey: ["class-examples", classId],
    queryFn: async () => {
      const res = await fetch(`/api/classes/${classId}/examples`);
      if (!res.ok) throw new Error("Failed to fetch examples");
      return res.json() as Promise<SubclassExample[]>;
    },
    enabled: Boolean(classId),
  });
}
