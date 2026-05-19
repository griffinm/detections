import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Trash2 } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { formatBytes, formatDuration } from "@/lib/format";
import { type Clip, useClipsList, useDeleteClip } from "@/hooks/useClips";

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
      className="cursor-pointer border-b border-border transition-colors hover:bg-muted/50"
      onClick={onClick}
    >
      <td className="px-4 py-3">
        {clip.thumbnail_url ? (
          <img
            src={clip.thumbnail_url}
            alt=""
            loading="lazy"
            className="h-10 w-16 rounded bg-muted object-cover"
          />
        ) : (
          <div className="h-10 w-16 rounded bg-muted" aria-hidden />
        )}
      </td>
      <td className="max-w-[280px] truncate px-4 py-3 text-sm font-medium">
        {clip.filename}
      </td>
      <td className="px-4 py-3">
        <StatusBadge status={clip.status} />
      </td>
      <td className="px-4 py-3 text-sm text-muted-foreground">
        {formatDuration(clip.duration_sec)}
      </td>
      <td className="px-4 py-3 text-sm text-muted-foreground">
        {formatBytes(clip.size_bytes)}
      </td>
      <td className="whitespace-nowrap px-4 py-3 text-sm text-muted-foreground">
        {ingestedAt}
      </td>
      <td className="px-4 py-3 text-right" onClick={(e) => e.stopPropagation()}>
        <DeleteClipButton clip={clip} />
      </td>
    </tr>
  );
}

function SkeletonRow() {
  return (
    <tr className="border-b border-border">
      {[...Array(7)].map((_, i) => (
        <td key={i} className="px-4 py-3">
          <div className="h-4 animate-pulse rounded bg-muted" />
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
      <PageHeader
        title="Clips"
        meta={
          data && (
            <span className="text-sm text-muted-foreground">
              {data.total} total
            </span>
          )
        }
      />

      {isError && (
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
          Failed to load clips.
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full min-w-[680px] text-left">
          <thead className="bg-muted/50 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="w-20 px-4 py-3" aria-label="Preview" />
              <th className="px-4 py-3">Filename</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Duration</th>
              <th className="px-4 py-3">Size</th>
              <th className="px-4 py-3">Ingested</th>
              <th className="w-12 px-4 py-3" aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {isPending && [...Array(5)].map((_, i) => <SkeletonRow key={i} />)}
            {data?.items.length === 0 && (
              <tr>
                <td
                  colSpan={7}
                  className="px-4 py-12 text-center text-sm text-muted-foreground"
                >
                  No clips yet. Drop a video into{" "}
                  <code className="font-mono">inbox/</code> to get started.
                </td>
              </tr>
            )}
            {data?.items.map((clip) => (
              <ClipRow
                key={clip.id}
                clip={clip}
                onClick={() => navigate(`/clips/${clip.id}`)}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
