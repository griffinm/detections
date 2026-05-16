import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { type Clip, useClipsList, useDeleteClip } from "@/hooks/useClips";

const STATUS_STYLES: Record<string, string> = {
  pending: "bg-muted text-muted-foreground",
  extracting: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200 animate-pulse",
  detecting: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200 animate-pulse",
  done: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  failed: "bg-destructive/20 text-destructive",
};

function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_STYLES[status] ?? "bg-muted text-muted-foreground";
  return (
    <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${cls}`}>
      {status}
    </span>
  );
}

function formatDuration(sec: number | null): string {
  if (sec == null) return "—";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

function DeleteClipButton({ clip }: { clip: Clip }) {
  const del = useDeleteClip();
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label={`Delete ${clip.filename}`}
          onClick={(e) => e.stopPropagation()}
        >
          <Trash2 className="h-4 w-4 text-muted-foreground" />
        </Button>
      </DialogTrigger>
      <DialogContent onClick={(e) => e.stopPropagation()}>
        <DialogHeader>
          <DialogTitle>Delete clip?</DialogTitle>
          <DialogDescription>
            “{clip.filename}” and all of its frames and detections will be
            permanently removed. This cannot be undone.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            disabled={del.isPending}
            onClick={() =>
              del.mutate(clip.id, {
                onSuccess: () => {
                  toast.success("Clip deletion queued");
                  setOpen(false);
                },
                onError: () => toast.error("Failed to delete clip"),
              })
            }
          >
            Delete
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ClipRow({ clip, onClick }: { clip: Clip; onClick: () => void }) {
  const ingestedAt = clip.ingested_at
    ? new Date(clip.ingested_at).toLocaleString()
    : "—";

  return (
    <tr
      className="border-b border-border hover:bg-muted/50 cursor-pointer transition-colors"
      onClick={onClick}
    >
      <td className="px-4 py-3 font-medium text-sm truncate max-w-[280px]">{clip.filename}</td>
      <td className="px-4 py-3">
        <StatusBadge status={clip.status} />
      </td>
      <td className="px-4 py-3 text-sm text-muted-foreground">{formatDuration(clip.duration_sec)}</td>
      <td className="px-4 py-3 text-sm text-muted-foreground">{formatBytes(clip.size_bytes)}</td>
      <td className="px-4 py-3 text-sm text-muted-foreground">{ingestedAt}</td>
      <td className="px-4 py-3 text-right" onClick={(e) => e.stopPropagation()}>
        <DeleteClipButton clip={clip} />
      </td>
    </tr>
  );
}

function SkeletonRow() {
  return (
    <tr className="border-b border-border">
      {[...Array(6)].map((_, i) => (
        <td key={i} className="px-4 py-3">
          <div className="h-4 bg-muted rounded animate-pulse" />
        </td>
      ))}
    </tr>
  );
}

export function ClipsList() {
  const navigate = useNavigate();
  const { data, isPending, isError } = useClipsList();

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Clips</h1>
        {data && (
          <span className="text-sm text-muted-foreground">{data.total} total</span>
        )}
      </div>

      {isError && (
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
          Failed to load clips.
        </div>
      )}

      <div className="rounded-lg border border-border overflow-hidden">
        <table className="w-full text-left">
          <thead className="bg-muted/50 text-xs font-medium text-muted-foreground uppercase tracking-wide">
            <tr>
              <th className="px-4 py-3">Filename</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Duration</th>
              <th className="px-4 py-3">Size</th>
              <th className="px-4 py-3">Ingested</th>
              <th className="px-4 py-3 w-12" aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {isPending && [...Array(5)].map((_, i) => <SkeletonRow key={i} />)}
            {data?.items.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-12 text-center text-sm text-muted-foreground">
                  No clips yet. Drop a video into <code className="font-mono">inbox/</code> to get started.
                </td>
              </tr>
            )}
            {data?.items.map((clip) => (
              <ClipRow key={clip.id} clip={clip} onClick={() => navigate(`/clips/${clip.id}`)} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
