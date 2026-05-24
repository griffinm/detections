import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Trash2, Upload } from "lucide-react";
import { toast } from "sonner";
import { ClipUploadList } from "@/components/ClipUploadList";
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
import { formatBytes, formatClipName, formatDuration } from "@/lib/format";
import {
  type Clip,
  useClipsList,
  useClipUploads,
  useDeleteClip,
} from "@/hooks/useClips";

// Mirrors the API's accepted video extensions. `video/*` alone misses some
// container types (notably .mkv) in OS file pickers, so list them explicitly.
const UPLOAD_ACCEPT = "video/*,.mp4,.mkv,.avi,.mov,.m4v,.webm";

function DeleteClipButton({ clip }: { clip: Clip }) {
  const del = useDeleteClip();
  const [open, setOpen] = useState(false);
  const name = formatClipName(clip.created_at);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label={`Delete ${name}`}
          onClick={(e) => e.stopPropagation()}
        >
          <Trash2 className="h-4 w-4 text-muted-foreground" />
        </Button>
      </DialogTrigger>
      <DialogContent onClick={(e) => e.stopPropagation()}>
        <DialogHeader>
          <DialogTitle>Delete clip?</DialogTitle>
          <DialogDescription>
            “{name}” and all of its frames and detections will be
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
        {formatClipName(clip.created_at)}
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
  const { uploads, start, dismiss } = useClipUploads();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const onFilesPicked = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) start([...files]);
    // Reset so picking the same file again still fires `change`.
    e.target.value = "";
  };

  return (
    <div className="space-y-4">
      <input
        ref={fileInputRef}
        type="file"
        accept={UPLOAD_ACCEPT}
        multiple
        className="hidden"
        onChange={onFilesPicked}
      />
      <PageHeader
        title="Clips"
        meta={
          data && (
            <span className="text-sm text-muted-foreground">
              {data.total} total
            </span>
          )
        }
        actions={
          <Button onClick={() => fileInputRef.current?.click()}>
            <Upload className="h-4 w-4" />
            Upload videos
          </Button>
        }
      />

      <ClipUploadList uploads={uploads} onDismiss={dismiss} />

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
              <th className="px-4 py-3">Name</th>
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
                  No clips yet. Use{" "}
                  <span className="font-medium">Upload videos</span> above, or
                  drop a video into <code className="font-mono">inbox/</code> to
                  get started.
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
