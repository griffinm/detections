import { useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useDiskUsage, usePurgeFrames } from "@/hooks/useSystem";
import { formatBytes } from "@/lib/format";

export function SystemPage() {
  const { data, isPending, isError } = useDiskUsage();
  const purge = usePurgeFrames();
  const [days, setDays] = useState(30);

  const used = data ? data.dirs.reduce((sum, d) => sum + d.bytes, 0) : 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="System"
        description="Disk usage and frame retention."
      />

      {isError && (
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
          Failed to load disk usage.
        </div>
      )}
      {isPending && <div className="h-40 animate-pulse rounded-lg bg-muted" />}

      {data && (
        <>
          <div className="space-y-3 rounded-lg border border-border p-4">
            <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1 text-sm">
              <span className="font-semibold">Data directories</span>
              <span className="text-muted-foreground">
                {formatBytes(data.free_bytes)} free of{" "}
                {formatBytes(data.total_bytes)}
              </span>
            </div>
            {data.dirs.map((d) => (
              <div key={d.name} className="space-y-1">
                <div className="flex flex-wrap items-center justify-between gap-x-2 text-sm">
                  <span className="font-medium capitalize">{d.name}</span>
                  <span className="text-muted-foreground">
                    {formatBytes(d.bytes)} · {d.file_count.toLocaleString()}{" "}
                    files
                  </span>
                </div>
                <div className="h-2 overflow-hidden rounded bg-muted">
                  <div
                    className="h-full bg-primary"
                    style={{
                      width: `${
                        data.total_bytes
                          ? Math.min(100, (d.bytes / data.total_bytes) * 100)
                          : 0
                      }%`,
                    }}
                  />
                </div>
                <div className="break-all font-mono text-xs text-muted-foreground">
                  {d.path}
                </div>
              </div>
            ))}
            <div className="pt-1 text-xs text-muted-foreground">
              {formatBytes(used)} used by managed directories.
            </div>
          </div>

          <div className="space-y-3 rounded-lg border border-border p-4">
            <div>
              <h2 className="text-base font-semibold">Purge old frames</h2>
              <p className="text-sm text-muted-foreground">
                Delete frame JPEGs from clips older than the cutoff. Frame and
                detection records are kept — only the images are removed.
              </p>
            </div>
            <div className="flex flex-wrap items-end gap-2">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">
                  Older than (days)
                </label>
                <Input
                  type="number"
                  min={1}
                  value={days}
                  className="w-32"
                  onChange={(e) =>
                    setDays(Math.max(1, parseInt(e.target.value, 10) || 1))
                  }
                />
              </div>
              <Button
                variant="destructive"
                disabled={purge.isPending}
                onClick={() =>
                  purge.mutate(days, {
                    onSuccess: () =>
                      toast.success(
                        `Purge queued for frames older than ${days} days`,
                      ),
                    onError: () => toast.error("Failed to queue purge"),
                  })
                }
              >
                Purge frames
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
