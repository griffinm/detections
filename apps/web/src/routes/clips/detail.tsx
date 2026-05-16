import { type ReactNode, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
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
import { useDeleteClip } from "@/hooks/useClips";
import { useClip, useClipFrames, type Frame } from "@/hooks/useFrames";

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

function DeleteClipButton({ id, filename }: { id: string; filename: string }) {
  const navigate = useNavigate();
  const del = useDeleteClip();
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="destructive" size="sm" className="ml-auto">
          Delete
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete clip?</DialogTitle>
          <DialogDescription>
            “{filename}” and all of its frames and detections will be
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
              del.mutate(id, {
                onSuccess: () => {
                  toast.success("Clip deletion queued");
                  navigate("/clips");
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

function MetaRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex gap-3 py-1.5 border-b border-border last:border-0">
      <dt className="w-36 shrink-0 text-sm text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium break-all">{value ?? "—"}</dd>
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

function formatDuration(sec: number | null): string {
  if (sec == null) return "—";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}m ${s}s`;
}

function FrameGrid({ frames }: { frames: Frame[] }) {
  if (frames.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">No frames extracted yet.</p>
    );
  }
  return (
    <div className="grid grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-1.5">
      {frames.map((f) => (
        <Link
          key={f.id}
          to={`/clips/${f.clip_id}/frames/${f.id}`}
          className="relative aspect-video bg-muted rounded overflow-hidden group hover:ring-2 hover:ring-ring"
        >
          {f.image_url ? (
            <img
              src={f.image_url}
              alt={`Frame ${f.frame_index}`}
              loading="lazy"
              className="w-full h-full object-cover"
            />
          ) : (
            <div className="flex items-center justify-center w-full h-full text-xs text-muted-foreground">
              {f.frame_index}
            </div>
          )}
          <div className="absolute inset-x-0 bottom-0 bg-black/60 text-white text-[10px] px-1 py-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
            {f.timestamp_sec.toFixed(1)}s
          </div>
        </Link>
      ))}
    </div>
  );
}

function SkeletonGrid() {
  return (
    <div className="grid grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-1.5">
      {[...Array(24)].map((_, i) => (
        <div key={i} className="aspect-video bg-muted rounded animate-pulse" />
      ))}
    </div>
  );
}

export function ClipDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const { data: clip, isPending: clipPending, isError: clipError } = useClip(id ?? "");
  const { data: frames, isPending: framesPending } = useClipFrames(id ?? "");

  if (clipError) {
    return (
      <div className="space-y-4">
        <button
          onClick={() => navigate("/clips")}
          className="text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          ← Back to clips
        </button>
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
          Clip not found.
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <button
          onClick={() => navigate("/clips")}
          className="text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          ← Clips
        </button>
        <span className="text-muted-foreground">/</span>
        {clipPending ? (
          <div className="h-4 w-48 bg-muted rounded animate-pulse" />
        ) : (
          <h1 className="text-lg font-semibold truncate">{clip?.filename}</h1>
        )}
        {clip && <StatusBadge status={clip.status} />}
        {clip && <DeleteClipButton id={clip.id} filename={clip.filename} />}
      </div>

      {/* Metadata */}
      <div className="rounded-lg border border-border p-4">
        {clipPending ? (
          <div className="space-y-2">
            {[...Array(8)].map((_, i) => (
              <div key={i} className="h-4 bg-muted rounded animate-pulse" />
            ))}
          </div>
        ) : clip ? (
          <dl>
            <MetaRow label="Filename" value={clip.filename} />
            <MetaRow label="Status" value={<StatusBadge status={clip.status} />} />
            <MetaRow label="Size" value={formatBytes(clip.size_bytes)} />
            <MetaRow label="Duration" value={formatDuration(clip.duration_sec)} />
            <MetaRow
              label="Resolution"
              value={clip.width && clip.height ? `${clip.width}×${clip.height}` : null}
            />
            <MetaRow label="FPS" value={clip.fps != null ? clip.fps.toFixed(2) : null} />
            <MetaRow label="Codec" value={clip.codec} />
            <MetaRow label="Frames" value={clip.frame_count} />
            <MetaRow
              label="SHA-256"
              value={
                <span className="font-mono text-xs">{clip.sha256.slice(0, 16)}…</span>
              }
            />
            <MetaRow
              label="Ingested"
              value={clip.ingested_at ? new Date(clip.ingested_at).toLocaleString() : null}
            />
            <MetaRow
              label="Processed"
              value={clip.processed_at ? new Date(clip.processed_at).toLocaleString() : null}
            />
            {clip.error && (
              <MetaRow
                label="Error"
                value={<span className="text-destructive">{clip.error}</span>}
              />
            )}
          </dl>
        ) : null}
      </div>

      {/* Frame grid */}
      <div className="space-y-3">
        <h2 className="text-base font-semibold">
          Frames{frames ? ` (${frames.length})` : ""}
        </h2>
        {framesPending ? <SkeletonGrid /> : <FrameGrid frames={frames ?? []} />}
      </div>
    </div>
  );
}
