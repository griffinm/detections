import { useCallback, useState } from "react";
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

export function useReextractClip() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string): Promise<void> => {
      const res = await fetch(`/api/clips/${id}/reextract`, { method: "POST" });
      if (!res.ok) {
        let detail = "Failed to re-extract clip";
        try {
          detail = ((await res.json()) as { detail?: string }).detail ?? detail;
        } catch {
          // non-JSON body — keep the generic message
        }
        throw new Error(detail);
      }
    },
    onSuccess: (_, id) => {
      void qc.invalidateQueries({ queryKey: ["clips"] });
      void qc.invalidateQueries({ queryKey: ["clips", id] });
      void qc.invalidateQueries({ queryKey: ["clips", id, "frames"] });
    },
  });
}

export type UploadStatus = "uploading" | "done" | "error";

export interface ClipUpload {
  id: string;
  name: string;
  size: number;
  /** Bytes sent to the server, 0..100. */
  progress: number;
  status: UploadStatus;
  error?: string;
}

/**
 * Tracks one or more concurrent video uploads, each with its own progress.
 *
 * Uses `XMLHttpRequest` rather than `fetch` because only XHR exposes
 * `upload.onprogress`. Each file is its own request so the progress bars are
 * independent. The server drops the file into the watched inbox; the clip row
 * itself arrives later via the `clip.created` SSE event (see useLiveEvents).
 */
// Monotonic id for upload rows. Not `crypto.randomUUID()` — that is
// secure-context-only and the app is served over plain HTTP on the LAN. These
// ids are only local React keys, so a session counter is sufficient.
let _uploadSeq = 0;

export function useClipUploads() {
  const [uploads, setUploads] = useState<ClipUpload[]>([]);

  const patch = useCallback((id: string, next: Partial<ClipUpload>) => {
    setUploads((prev) => prev.map((u) => (u.id === id ? { ...u, ...next } : u)));
  }, []);

  const dismiss = useCallback((id: string) => {
    setUploads((prev) => prev.filter((u) => u.id !== id));
  }, []);

  const start = useCallback(
    (files: File[]) => {
      for (const file of files) {
        const id = `upload-${++_uploadSeq}`;
        setUploads((prev) => [
          { id, name: file.name, size: file.size, progress: 0, status: "uploading" },
          ...prev,
        ]);

        const form = new FormData();
        form.append("file", file);

        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/api/clips/upload");
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) {
            patch(id, { progress: Math.round((e.loaded / e.total) * 100) });
          }
        };
        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            patch(id, { status: "done", progress: 100 });
            // The clip appears in the table on the clip.created SSE event;
            // clear the finished upload row shortly after.
            window.setTimeout(() => dismiss(id), 5000);
          } else {
            let detail = `Upload failed (${xhr.status})`;
            try {
              detail =
                (JSON.parse(xhr.responseText) as { detail?: string }).detail ?? detail;
            } catch {
              // non-JSON error body — keep the generic message
            }
            patch(id, { status: "error", error: detail });
          }
        };
        xhr.onerror = () => patch(id, { status: "error", error: "Network error" });
        xhr.send(form);
      }
    },
    [patch, dismiss],
  );

  return { uploads, start, dismiss };
}
