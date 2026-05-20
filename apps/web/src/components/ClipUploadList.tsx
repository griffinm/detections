import { AlertCircle, CheckCircle2, Loader2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { ClipUpload } from "@/hooks/useClips";

function UploadRow({
  upload,
  onDismiss,
}: {
  upload: ClipUpload;
  onDismiss: () => void;
}) {
  return (
    <div className="flex items-center gap-3 px-3 py-2.5">
      <span className="shrink-0" aria-hidden>
        {upload.status === "uploading" && (
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        )}
        {upload.status === "done" && (
          <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-500" />
        )}
        {upload.status === "error" && (
          <AlertCircle className="h-4 w-4 text-destructive" />
        )}
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-3">
          <span className="truncate text-sm font-medium">{upload.name}</span>
          <span className="shrink-0 text-xs text-muted-foreground">
            {upload.status === "uploading" && `${upload.progress}%`}
            {upload.status === "done" && "Queued for processing"}
            {upload.status === "error" && formatBytes(upload.size)}
          </span>
        </div>

        {upload.status === "error" ? (
          <p className="mt-0.5 text-xs text-destructive">{upload.error}</p>
        ) : (
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted">
            <div
              className={cn(
                "h-full rounded-full transition-all duration-200",
                upload.status === "done" ? "bg-green-600" : "bg-primary",
              )}
              style={{ width: `${upload.progress}%` }}
            />
          </div>
        )}
      </div>

      <Button
        variant="ghost"
        size="icon"
        className="h-7 w-7 shrink-0"
        aria-label={`Dismiss ${upload.name}`}
        onClick={onDismiss}
      >
        <X className="h-4 w-4 text-muted-foreground" />
      </Button>
    </div>
  );
}

/** Per-file progress for in-flight and recently finished clip uploads. */
export function ClipUploadList({
  uploads,
  onDismiss,
}: {
  uploads: ClipUpload[];
  onDismiss: (id: string) => void;
}) {
  if (uploads.length === 0) return null;
  return (
    <div className="divide-y divide-border rounded-lg border border-border">
      {uploads.map((u) => (
        <UploadRow key={u.id} upload={u} onDismiss={() => onDismiss(u.id)} />
      ))}
    </div>
  );
}
