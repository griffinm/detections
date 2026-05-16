import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  useStartTraining,
  useTrainingRun,
  useTrainingRuns,
} from "@/hooks/useTraining";

const STATUS_STYLES: Record<string, string> = {
  queued: "bg-muted text-muted-foreground",
  running:
    "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200 animate-pulse",
  succeeded: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  failed: "bg-destructive/20 text-destructive",
  cancelled: "bg-muted text-muted-foreground",
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={cn(
        "rounded px-1.5 py-0.5 text-xs font-medium",
        STATUS_STYLES[status] ?? "bg-muted",
      )}
    >
      {status}
    </span>
  );
}

function RunDetail({ runId }: { runId: string }) {
  const { data: run } = useTrainingRun(runId);
  if (!run) {
    return <p className="text-sm text-muted-foreground">Loading run…</p>;
  }
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <StatusBadge status={run.status} />
        <span className="text-sm text-muted-foreground">{run.kind}</span>
      </div>
      {run.error && <p className="text-sm text-destructive">{run.error}</p>}
      {run.metrics && (
        <pre className="overflow-x-auto rounded bg-muted p-2 text-xs">
          {JSON.stringify(run.metrics, null, 2)}
        </pre>
      )}
      {run.log_tail && (
        <pre className="max-h-64 overflow-auto rounded bg-muted p-2 text-[11px] leading-tight">
          {run.log_tail}
        </pre>
      )}
    </div>
  );
}

export function TrainingPage() {
  const { data: runs = [], isPending } = useTrainingRuns();
  const startTraining = useStartTraining();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const startFinetune = async (): Promise<void> => {
    try {
      const run = await startTraining.mutateAsync({ kind: "yolo" });
      setSelectedId(run.id);
      toast.success("YOLO fine-tune queued");
    } catch {
      toast.error("Could not start training");
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-bold tracking-tight">Training</h1>
        <Button
          className="ml-auto"
          onClick={() => void startFinetune()}
          disabled={startTraining.isPending}
        >
          Start YOLO fine-tune
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">
        Fine-tune the detector on reviewed labels. Sub-class classifiers are
        trained from a class page.
      </p>

      {isPending ? (
        <div className="h-11 animate-pulse rounded bg-muted" />
      ) : runs.length === 0 ? (
        <p className="text-sm text-muted-foreground">No training runs yet.</p>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          <div className="overflow-hidden rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-left text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium">Kind</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Started</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr
                    key={run.id}
                    onClick={() => setSelectedId(run.id)}
                    className={cn(
                      "cursor-pointer border-t border-border",
                      selectedId === run.id ? "bg-accent" : "hover:bg-muted",
                    )}
                  >
                    <td className="px-3 py-2">{run.kind}</td>
                    <td className="px-3 py-2">
                      <StatusBadge status={run.status} />
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">
                      {run.started_at
                        ? new Date(run.started_at).toLocaleString()
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="rounded-lg border border-border p-3">
            {selectedId ? (
              <RunDetail runId={selectedId} />
            ) : (
              <p className="text-sm text-muted-foreground">
                Select a run to see its metrics and log.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
