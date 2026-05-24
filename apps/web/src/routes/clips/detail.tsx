import { type ReactNode, useState } from "react";
import { CheckCircle2, RefreshCw } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button, buttonVariants } from "@/components/ui/button";
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
import { DeleteFrameButton } from "@/components/DeleteFrameButton";
import { formatBytes, formatClipName, formatDuration } from "@/lib/format";
import { useDeleteClip, useReextractClip } from "@/hooks/useClips";
import { useClip, useClipFrames, type Frame } from "@/hooks/useFrames";

function ReextractButton({ id, name }: { id: string; name: string }) {
  const reextract = useReextractClip();
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <RefreshCw className="h-4 w-4" /> Re-extract frames
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Re-extract frames?</DialogTitle>
          <DialogDescription>
            All existing frames and detections for “{name}” will be
            deleted, then frames will be re-extracted from the source video
            and detection will run again. Any examples promoted from this
            clip will also be lost. The source video itself is untouched.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button
            disabled={reextract.isPending}
            onClick={() =>
              reextract.mutate(id, {
                onSuccess: () => {
                  toast.success("Re-extraction queued");
                  setOpen(false);
                },
                onError: (err) =>
                  toast.error(
                    err instanceof Error
                      ? err.message
                      : "Failed to re-extract clip",
                  ),
              })
            }
          >
            Re-extract
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function DeleteClipButton({ id, name }: { id: string; name: string }) {
  const navigate = useNavigate();
  const del = useDeleteClip();
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="destructive" size="sm">
          Delete
        </Button>
      </DialogTrigger>
      <DialogContent>
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
    <div className="flex gap-3 border-b border-border py-1.5 last:border-0">
      <dt className="w-32 shrink-0 text-sm text-muted-foreground sm:w-36">
        {label}
      </dt>
      <dd className="break-all text-sm font-medium">{value ?? "—"}</dd>
    </div>
  );
}

function FrameGrid({ frames }: { frames: Frame[] }) {
  if (frames.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">No frames extracted yet.</p>
    );
  }
  return (
    <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8">
      {frames.map((f) => (
        <Link
          key={f.id}
          to={`/clips/${f.clip_id}/frames/${f.id}`}
          className="group relative aspect-video overflow-hidden rounded bg-muted hover:ring-2 hover:ring-ring"
        >
          {f.image_url ? (
            <img
              src={f.image_url}
              alt={`Frame ${f.frame_index}`}
              loading="lazy"
              className="h-full w-full object-cover"
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center text-xs text-muted-foreground">
              {f.frame_index}
            </div>
          )}
          <div className="absolute inset-x-0 bottom-0 bg-black/60 px-1 py-0.5 text-[10px] text-white opacity-0 transition-opacity group-hover:opacity-100">
            {f.timestamp_sec.toFixed(1)}s
          </div>
          <DeleteFrameButton
            variant="icon"
            frameId={f.id}
            clipId={f.clip_id}
            frameIndex={f.frame_index}
            className="absolute right-1 top-1 h-7 w-7 bg-black/60 text-white opacity-0 transition-opacity hover:bg-black/80 group-hover:opacity-100"
          />
        </Link>
      ))}
    </div>
  );
}

function SkeletonGrid() {
  return (
    <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8">
      {[...Array(24)].map((_, i) => (
        <div key={i} className="aspect-video animate-pulse rounded bg-muted" />
      ))}
    </div>
  );
}

export function ClipDetail() {
  const { id } = useParams<{ id: string }>();

  const { data: clip, isPending: clipPending, isError: clipError } = useClip(
    id ?? "",
  );
  const { data: frames, isPending: framesPending } = useClipFrames(id ?? "");

  if (clipError) {
    return (
      <div className="space-y-4">
        <PageHeader
          title="Clip"
          breadcrumbs={[{ label: "Clips", to: "/clips" }]}
        />
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
          Clip not found.
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={[{ label: "Clips", to: "/clips" }]}
        title={
          clipPending ? (
            <span className="inline-block h-6 w-48 animate-pulse rounded bg-muted align-middle" />
          ) : (
            <span className="break-all">{formatClipName(clip?.created_at)}</span>
          )
        }
        meta={clip && <StatusBadge status={clip.status} />}
        actions={
          clip && (
            <>
              <Link
                to={`/labeling/clips/${clip.id}`}
                className={buttonVariants({ variant: "outline", size: "sm" })}
              >
                <CheckCircle2 className="h-4 w-4" /> Bulk-label
              </Link>
              <ReextractButton id={clip.id} name={formatClipName(clip.created_at)} />
              <DeleteClipButton id={clip.id} name={formatClipName(clip.created_at)} />
            </>
          )
        }
      />

      {/* Metadata */}
      <div className="rounded-lg border border-border p-4">
        {clipPending ? (
          <div className="space-y-2">
            {[...Array(8)].map((_, i) => (
              <div key={i} className="h-4 animate-pulse rounded bg-muted" />
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
              value={
                clip.width && clip.height
                  ? `${clip.width}×${clip.height}`
                  : null
              }
            />
            <MetaRow
              label="FPS"
              value={clip.fps != null ? clip.fps.toFixed(2) : null}
            />
            <MetaRow label="Codec" value={clip.codec} />
            <MetaRow label="Frames" value={clip.frame_count} />
            <MetaRow
              label="SHA-256"
              value={
                <span className="font-mono text-xs">
                  {clip.sha256.slice(0, 16)}…
                </span>
              }
            />
            <MetaRow
              label="Ingested"
              value={
                clip.ingested_at
                  ? new Date(clip.ingested_at).toLocaleString()
                  : null
              }
            />
            <MetaRow
              label="Processed"
              value={
                clip.processed_at
                  ? new Date(clip.processed_at).toLocaleString()
                  : null
              }
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
