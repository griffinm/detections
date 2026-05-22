import { useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import { formatElapsed } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useClasses } from "@/hooks/useClasses";
import {
  useStartTraining,
  useTrainingRun,
  useTrainingRuns,
  type TrainingRun,
} from "@/hooks/useTraining";

type KindFilter = "all" | "yolo" | "classifier";

const KIND_FILTERS: { value: KindFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "yolo", label: "YOLO" },
  { value: "classifier", label: "Classifier" },
];

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Count of examples a run trained on — boxes for YOLO, labeled crops for a classifier. */
function trainingSetSize(run: TrainingRun): number | null {
  const metrics = run.metrics;
  if (!metrics) return null;
  if (run.kind === "yolo") {
    const dataset = metrics.dataset as Record<string, unknown> | undefined;
    return asNumber(dataset?.detections);
  }
  if (run.kind === "classifier") {
    const nTrain = asNumber(metrics.n_train);
    const nVal = asNumber(metrics.n_val);
    if (nTrain == null && nVal == null) return null;
    return (nTrain ?? 0) + (nVal ?? 0);
  }
  return null;
}

/** Wall-clock training time in seconds, once a run has both timestamps. */
function runDurationSec(run: TrainingRun): number | null {
  if (!run.started_at || !run.finished_at) return null;
  return (
    (new Date(run.finished_at).getTime() -
      new Date(run.started_at).getTime()) /
    1000
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
  const { data: classes = [] } = useClasses();
  const startTraining = useStartTraining();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [kindFilter, setKindFilter] = useState<KindFilter>("all");

  const classNames = new Map(classes.map((c) => [c.id, c.name]));
  const visibleRuns = runs.filter(
    (run) => kindFilter === "all" || run.kind === kindFilter,
  );

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
    <div className="flex h-full flex-col gap-4">
      <PageHeader
        title="Training"
        description="Fine-tune the detector on reviewed labels. Sub-class classifiers are trained from a class page."
        actions={
          <>
            <div className="flex items-center gap-1">
              {KIND_FILTERS.map(({ value, label }) => (
                <button
                  key={value}
                  onClick={() => setKindFilter(value)}
                  className={cn(
                    "rounded px-2 py-0.5 text-xs",
                    kindFilter === value
                      ? "bg-accent"
                      : "text-muted-foreground hover:bg-muted",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
            <Button
              onClick={() => void startFinetune()}
              disabled={startTraining.isPending}
            >
              Start YOLO fine-tune
            </Button>
          </>
        }
      />

      {isPending ? (
        <div className="h-11 animate-pulse rounded bg-muted" />
      ) : runs.length === 0 ? (
        <p className="text-sm text-muted-foreground">No training runs yet.</p>
      ) : visibleRuns.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No {kindFilter} runs.
        </p>
      ) : (
        <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-2">
          <div className="overflow-auto rounded-lg border border-border">
            <table className="w-full min-w-[680px] text-sm">
              <thead className="sticky top-0 bg-muted/95 text-left text-xs uppercase text-muted-foreground backdrop-blur">
                <tr>
                  <th className="px-3 py-2 font-medium">Kind</th>
                  <th className="px-3 py-2 font-medium">Class</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Train set</th>
                  <th className="px-3 py-2 font-medium">Duration</th>
                  <th className="px-3 py-2 font-medium">Started</th>
                </tr>
              </thead>
              <tbody>
                {visibleRuns.map((run) => {
                  const size = trainingSetSize(run);
                  const className = run.target_class_id
                    ? (classNames.get(run.target_class_id) ?? "—")
                    : "All";
                  return (
                    <tr
                      key={run.id}
                      onClick={() => setSelectedId(run.id)}
                      className={cn(
                        "cursor-pointer border-t border-border",
                        selectedId === run.id
                          ? "bg-accent"
                          : "hover:bg-muted",
                      )}
                    >
                      <td className="px-3 py-2">{run.kind}</td>
                      <td
                        className={cn(
                          "px-3 py-2",
                          run.target_class_id
                            ? ""
                            : "text-muted-foreground",
                        )}
                      >
                        {className}
                      </td>
                      <td className="px-3 py-2">
                        <StatusBadge status={run.status} />
                      </td>
                      <td className="px-3 py-2 tabular-nums">
                        {size == null ? (
                          <span className="text-muted-foreground">—</span>
                        ) : (
                          size.toLocaleString()
                        )}
                      </td>
                      <td className="px-3 py-2 tabular-nums text-muted-foreground">
                        {formatElapsed(runDurationSec(run))}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                        {run.started_at
                          ? new Date(run.started_at).toLocaleString()
                          : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="overflow-auto rounded-lg border border-border p-3">
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
