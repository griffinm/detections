import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

const JSON_HEADERS = { "Content-Type": "application/json" };

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
