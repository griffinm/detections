import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  CheckCircle2,
  ChevronRight,
  ExternalLink,
  Loader2,
  Sparkles,
  Tag,
  Target,
  XCircle,
} from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button, buttonVariants } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import { TableSentinelRow } from "@/components/ui/InfiniteScrollSentinel";
import { formatElapsed } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useClasses, type VdClass } from "@/hooks/useClasses";
import {
  useCancelTraining,
  useStartTraining,
  useTrainingRun,
  useTrainingRunCounts,
  useTrainingRunsInfinite,
  type TrainingRun,
  type TrainingRunDetail,
} from "@/hooks/useTraining";

type KindFilter = "all" | "yolo" | "classifier";
type StatusBucket = "running" | "done" | "failed" | "queued";
type StatusFilter = "all" | StatusBucket;

const KIND_FILTERS: { value: KindFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "yolo", label: "YOLO" },
  { value: "classifier", label: "Classifier" },
];

const STATUS_FILTERS: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "Total" },
  { value: "running", label: "Running" },
  { value: "done", label: "Done" },
  { value: "failed", label: "Failed" },
  { value: "queued", label: "Queued" },
];

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
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

/** Wall-clock duration in seconds. For running runs, elapsed since start. */
function runDurationSec(run: TrainingRun, now: number): number | null {
  if (!run.started_at) return null;
  const end = run.finished_at ? new Date(run.finished_at).getTime() : now;
  return (end - new Date(run.started_at).getTime()) / 1000;
}

/** Relative time, e.g. "12s ago", "4m ago", "2d ago". */
function formatRelative(iso: string | null, now: number): string {
  if (!iso) return "—";
  const ms = Math.max(0, now - new Date(iso).getTime());
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d}d ago`;
  return new Date(iso).toLocaleDateString();
}

function formatPercent(value: number | null, digits = 1): string {
  if (value == null) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

function isYolo(run: TrainingRun): boolean {
  return run.kind === "yolo";
}

function KindChip({ kind }: { kind: string }) {
  const yolo = kind === "yolo";
  const Icon = yolo ? Target : Tag;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
        yolo
          ? "border-blue-500/30 bg-blue-500/10 text-blue-700 dark:text-blue-300"
          : "border-violet-500/30 bg-violet-500/10 text-violet-700 dark:text-violet-300",
      )}
    >
      <Icon className="h-3 w-3" />
      {yolo ? "YOLO" : "Classifier"}
    </span>
  );
}

function ClassCell({ cls }: { cls: VdClass | undefined }) {
  if (!cls) {
    return (
      <span className="inline-flex items-center gap-1.5 text-muted-foreground">
        <span className="h-2.5 w-2.5 rounded-sm border border-dashed border-border" />
        All classes
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className="h-2.5 w-2.5 shrink-0 rounded-sm border border-border"
        style={{ backgroundColor: cls.color_hex }}
      />
      <span className="truncate">{cls.name}</span>
    </span>
  );
}

function StatChip({
  label,
  count,
  active,
  tone,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  tone: "neutral" | "running" | "done" | "failed" | "queued";
  onClick: () => void;
}) {
  const dotClass = {
    neutral: "bg-foreground/60",
    running: "bg-blue-500 animate-pulse",
    done: "bg-emerald-500",
    failed: "bg-destructive",
    queued: "bg-muted-foreground/60",
  }[tone];
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "group inline-flex items-center gap-2 rounded-md border px-2.5 py-1 text-xs transition-colors",
        active
          ? "border-foreground/30 bg-accent text-foreground"
          : "border-border bg-card text-muted-foreground hover:border-foreground/20 hover:text-foreground",
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", dotClass)} />
      <span className="font-medium">{label}</span>
      <span
        className={cn(
          "tabular-nums",
          active ? "text-foreground" : "text-foreground/80",
        )}
      >
        {count}
      </span>
    </button>
  );
}

function SegmentedFilter<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: ReadonlyArray<{ value: T; label: string }>;
  onChange: (v: T) => void;
}) {
  return (
    <div className="inline-flex rounded-md border border-input">
      {options.map((o, i) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={cn(
            "px-2.5 py-1 text-xs transition-colors",
            i === 0 && "rounded-l-md",
            i === options.length - 1 && "rounded-r-md",
            value === o.value
              ? "bg-accent text-accent-foreground"
              : "text-muted-foreground hover:bg-muted",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function MetricTile({
  label,
  value,
  sub,
  delta,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  delta?: { value: number; better: "up" | "down" };
  tone?: "default" | "muted" | "destructive";
}) {
  const toneClass =
    tone === "destructive"
      ? "text-destructive"
      : tone === "muted"
        ? "text-muted-foreground"
        : "text-foreground";
  return (
    <div className="rounded-md border border-border bg-background px-3 py-2">
      <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="mt-0.5 flex items-baseline gap-1.5">
        <span className={cn("text-base font-semibold tabular-nums", toneClass)}>
          {value}
        </span>
        {delta && Number.isFinite(delta.value) && (
          <DeltaPill value={delta.value} better={delta.better} />
        )}
      </div>
      {sub && (
        <div className="mt-0.5 text-[11px] text-muted-foreground">{sub}</div>
      )}
    </div>
  );
}

function DeltaPill({
  value,
  better,
}: {
  value: number;
  better: "up" | "down";
}) {
  const positive = value >= 0;
  const good = better === "up" ? positive : !positive;
  const Icon = positive ? ArrowUpRight : ArrowDownRight;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 rounded px-1 text-[10px] font-medium tabular-nums",
        good
          ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
          : "bg-destructive/10 text-destructive",
      )}
      title={`Δ vs previous model: ${positive ? "+" : ""}${(value * 100).toFixed(2)}pp`}
    >
      <Icon className="h-2.5 w-2.5" />
      {Math.abs(value * 100).toFixed(1)}pp
    </span>
  );
}

function YoloMetricGrid({ metrics }: { metrics: Record<string, unknown> }) {
  const map50 = asNumber(metrics.val_map50);
  const map5095 = asNumber(metrics.val_map50_95);
  const prevMap = asNumber(metrics.prev_map50_95);
  const precision = asNumber(metrics.precision);
  const recall = asNumber(metrics.recall);
  const dataset = (metrics.dataset ?? {}) as Record<string, unknown>;
  const dTrain = asNumber(dataset.train);
  const dVal = asNumber(dataset.val);
  const dTest = asNumber(dataset.test);
  const dDet = asNumber(dataset.detections);
  const dMissing = asNumber(dataset.frames_missing);

  const delta =
    map5095 != null && prevMap != null
      ? { value: map5095 - prevMap, better: "up" as const }
      : undefined;

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <MetricTile label="mAP@50" value={formatPercent(map50)} />
        <MetricTile
          label="mAP@50–95"
          value={formatPercent(map5095)}
          delta={delta}
          sub={prevMap != null ? `prev ${formatPercent(prevMap)}` : undefined}
        />
        <MetricTile label="Precision" value={formatPercent(precision)} />
        <MetricTile label="Recall" value={formatPercent(recall)} />
      </div>
      <div>
        <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
          Dataset
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          <MetricTile
            label="Train"
            value={dTrain?.toLocaleString() ?? "—"}
            sub="frames"
          />
          <MetricTile
            label="Val"
            value={dVal?.toLocaleString() ?? "—"}
            sub="frames"
          />
          <MetricTile
            label="Test"
            value={dTest?.toLocaleString() ?? "—"}
            sub="frames"
          />
          <MetricTile
            label="Detections"
            value={dDet?.toLocaleString() ?? "—"}
            sub="boxes"
          />
          <MetricTile
            label="Missing"
            value={dMissing?.toLocaleString() ?? "—"}
            sub="frames"
            tone={dMissing && dMissing > 0 ? "destructive" : "muted"}
          />
        </div>
      </div>
    </div>
  );
}

function ClassifierMetricGrid({
  metrics,
}: {
  metrics: Record<string, unknown>;
}) {
  const acc = asNumber(metrics.val_accuracy);
  const nTrain = asNumber(metrics.n_train);
  const nVal = asNumber(metrics.n_val);
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      <MetricTile label="Val accuracy" value={formatPercent(acc, 2)} />
      <MetricTile
        label="Train"
        value={nTrain?.toLocaleString() ?? "—"}
        sub="crops"
      />
      <MetricTile
        label="Val"
        value={nVal?.toLocaleString() ?? "—"}
        sub="crops"
      />
    </div>
  );
}

/** Keys we already surface in dedicated tiles — skip them in the "Other" dump. */
const YOLO_KNOWN = new Set([
  "val_map50",
  "val_map50_95",
  "prev_map50_95",
  "precision",
  "recall",
  "dataset",
  "model_version_id",
  "activated",
]);
const CLASSIFIER_KNOWN = new Set([
  "val_accuracy",
  "n_train",
  "n_val",
  "model_version_id",
]);

function RunMetricsBlock({ run }: { run: TrainingRunDetail }) {
  const metrics = run.metrics;
  if (!metrics) {
    if (run.status === "running") {
      return (
        <p className="text-sm text-muted-foreground">
          Metrics will appear once the run finishes.
        </p>
      );
    }
    if (run.status === "failed") {
      return (
        <p className="text-sm text-muted-foreground">
          No metrics — run failed before producing results.
        </p>
      );
    }
    return (
      <p className="text-sm text-muted-foreground">No metrics recorded.</p>
    );
  }

  const known = isYolo(run) ? YOLO_KNOWN : CLASSIFIER_KNOWN;
  const extra = Object.fromEntries(
    Object.entries(metrics).filter(([k]) => !known.has(k)),
  );
  const hasExtra = Object.keys(extra).length > 0;

  return (
    <div className="space-y-4">
      {isYolo(run) ? (
        <YoloMetricGrid metrics={metrics} />
      ) : (
        <ClassifierMetricGrid metrics={metrics} />
      )}
      {hasExtra && (
        <details className="group rounded-md border border-border bg-background">
          <summary className="flex cursor-pointer items-center gap-1.5 px-3 py-2 text-xs text-muted-foreground hover:text-foreground">
            <ChevronRight className="h-3.5 w-3.5 transition-transform group-open:rotate-90" />
            Other metrics
          </summary>
          <pre className="overflow-x-auto border-t border-border bg-muted/40 p-3 text-[11px] leading-snug">
            {JSON.stringify(extra, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}

function RunDetailHeader({
  run,
  cls,
}: {
  run: TrainingRunDetail;
  cls: VdClass | undefined;
}) {
  const now = Date.now();
  const duration = runDurationSec(run, now);
  const modelId = asString(run.metrics?.model_version_id);
  const activated = run.metrics?.activated === true;
  const cancel = useCancelTraining();
  const cancellable = run.status === "running" || run.status === "queued";
  const onCancel = async () => {
    if (!window.confirm("Cancel this training run?")) return;
    try {
      await cancel.mutateAsync(run.id);
      toast.success("Training run cancelled");
    } catch {
      toast.error("Could not cancel training run");
    }
  };
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <KindChip kind={run.kind} />
        <StatusBadge status={run.status} />
        {activated && (
          <span className="inline-flex items-center gap-1 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-300">
            <Sparkles className="h-3 w-3" />
            Active model
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {cancellable && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => void onCancel()}
              disabled={cancel.isPending}
              title="Mark this run as cancelled. Use to clear runs left stuck after a worker restart."
            >
              <XCircle className="h-3.5 w-3.5" />
              Cancel
            </Button>
          )}
          <div className="font-mono text-[11px] text-muted-foreground">
            {run.id.slice(0, 8)}
          </div>
        </div>
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs sm:grid-cols-4">
        <div>
          <dt className="text-muted-foreground">Target</dt>
          <dd className="mt-0.5 truncate">
            <ClassCell cls={cls} />
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Started</dt>
          <dd
            className="mt-0.5 truncate"
            title={
              run.started_at
                ? new Date(run.started_at).toLocaleString()
                : undefined
            }
          >
            {formatRelative(run.started_at, now)}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Finished</dt>
          <dd
            className="mt-0.5 truncate"
            title={
              run.finished_at
                ? new Date(run.finished_at).toLocaleString()
                : undefined
            }
          >
            {run.finished_at ? formatRelative(run.finished_at, now) : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Duration</dt>
          <dd className="mt-0.5 tabular-nums">
            {duration == null ? (
              "—"
            ) : run.status === "running" ? (
              <span className="inline-flex items-center gap-1 text-blue-600 dark:text-blue-300">
                <Activity className="h-3 w-3 animate-pulse" />
                {formatElapsed(duration)}
              </span>
            ) : (
              formatElapsed(duration)
            )}
          </dd>
        </div>
      </dl>
      {modelId && (
        <div className="text-xs">
          <Link
            to="/models"
            className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground"
            title={modelId}
          >
            View resulting model{" "}
            <span className="font-mono">{modelId.slice(0, 8)}</span>
            <ExternalLink className="h-3 w-3" />
          </Link>
        </div>
      )}
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
      {children}
    </div>
  );
}

function RunDetail({
  runId,
  classById,
}: {
  runId: string;
  classById: Map<string, VdClass>;
}) {
  const { data: run, isPending } = useTrainingRun(runId);
  if (isPending || !run) {
    return (
      <div className="space-y-3">
        <div className="h-6 w-48 animate-pulse rounded bg-muted" />
        <div className="h-20 w-full animate-pulse rounded bg-muted" />
        <div className="h-32 w-full animate-pulse rounded bg-muted" />
      </div>
    );
  }
  const cls = run.target_class_id
    ? classById.get(run.target_class_id)
    : undefined;

  return (
    <div className="space-y-5">
      <RunDetailHeader run={run} cls={cls} />

      {run.error && (
        <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="min-w-0">
            <div className="text-xs font-semibold uppercase tracking-wide">
              Error
            </div>
            <div className="mt-0.5 break-words font-mono text-[11px] leading-snug">
              {run.error}
            </div>
          </div>
        </div>
      )}

      <section className="space-y-2">
        <SectionLabel>Metrics</SectionLabel>
        <RunMetricsBlock run={run} />
      </section>

      {run.log_tail && (
        <section className="space-y-2">
          <SectionLabel>Log tail</SectionLabel>
          <pre className="max-h-72 overflow-auto rounded-md border border-border bg-muted/50 p-3 font-mono text-[11px] leading-snug">
            {run.log_tail}
          </pre>
        </section>
      )}
    </div>
  );
}

function EmptyState({
  onStart,
  busy,
}: {
  onStart: () => void;
  busy: boolean;
}) {
  return (
    <div className="flex flex-1 items-center justify-center">
      <div className="w-full max-w-md rounded-lg border border-dashed border-border bg-card p-8 text-center">
        <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-full bg-muted text-muted-foreground">
          <Target className="h-5 w-5" />
        </div>
        <h3 className="mt-3 text-base font-semibold">No training runs yet</h3>
        <p className="mx-auto mt-1 max-w-sm text-sm text-muted-foreground">
          Fine-tune the YOLO detector once you have reviewed labels, or train a
          sub-class classifier from any class page.
        </p>
        <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
          <Button onClick={onStart} disabled={busy}>
            <Target className="h-4 w-4" /> Start YOLO fine-tune
          </Button>
          <Link to="/classes" className={buttonVariants({ variant: "outline" })}>
            Browse classes
          </Link>
        </div>
      </div>
    </div>
  );
}

export function TrainingPage() {
  const { data: classes = [] } = useClasses();
  const startTraining = useStartTraining();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [kindFilter, setKindFilter] = useState<KindFilter>("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const kindParam = kindFilter === "all" ? undefined : kindFilter;
  const statusParam = statusFilter === "all" ? undefined : statusFilter;

  const {
    rows,
    total,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
    isPending,
  } = useTrainingRunsInfinite({ kind: kindParam, status: statusParam });
  const { data: counts } = useTrainingRunCounts({ kind: kindParam });

  const classById = useMemo(
    () => new Map(classes.map((c) => [c.id, c])),
    [classes],
  );

  // Re-render every second so the "running for Xs" duration ticks on both
  // the detail panel and any visible running rows.
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!rows.some((r) => r.status === "running")) return;
    const handle = window.setInterval(() => setTick((t) => t + 1), 1000);
    return () => window.clearInterval(handle);
  }, [rows]);

  const startFinetune = async (): Promise<void> => {
    try {
      const run = await startTraining.mutateAsync({ kind: "yolo" });
      setSelectedId(run.id);
      toast.success("YOLO fine-tune queued");
    } catch {
      toast.error("Could not start training");
    }
  };

  const tableScrollRef = useRef<HTMLDivElement>(null);
  const loadMore = useMemo(() => () => void fetchNextPage(), [fetchNextPage]);
  const filtersActive = kindFilter !== "all" || statusFilter !== "all";
  const showEmptyState = !isPending && !filtersActive && rows.length === 0;

  const now = Date.now();

  return (
    <div className="flex h-full flex-col gap-4">
      <PageHeader
        title="Training"
        description="Fine-tune the detector on reviewed labels. Sub-class classifiers are trained from a class page."
        actions={
          <Button
            onClick={() => void startFinetune()}
            disabled={startTraining.isPending}
          >
            <Target className="h-4 w-4" /> Start YOLO fine-tune
          </Button>
        }
      />

      {isPending ? (
        <div className="space-y-3">
          <div className="h-9 animate-pulse rounded bg-muted" />
          <div className="h-64 animate-pulse rounded bg-muted" />
        </div>
      ) : showEmptyState ? (
        <EmptyState
          onStart={() => void startFinetune()}
          busy={startTraining.isPending}
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            {STATUS_FILTERS.map((f) => (
              <StatChip
                key={f.value}
                label={f.label}
                count={counts?.[f.value] ?? 0}
                active={statusFilter === f.value}
                tone={f.value === "all" ? "neutral" : f.value}
                onClick={() => setStatusFilter(f.value)}
              />
            ))}
            <div className="ml-auto flex items-center gap-2">
              <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
                Kind
              </span>
              <SegmentedFilter
                value={kindFilter}
                options={KIND_FILTERS}
                onChange={setKindFilter}
              />
            </div>
          </div>

          <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
            <div
              ref={tableScrollRef}
              className="overflow-auto rounded-lg border border-border bg-card"
            >
              {rows.length === 0 ? (
                <div className="p-6 text-sm text-muted-foreground">
                  No runs match the current filters.
                </div>
              ) : (
                <table className="w-full min-w-[680px] text-sm">
                  <thead className="sticky top-0 z-10 bg-muted/95 text-left text-[10px] uppercase tracking-wider text-muted-foreground backdrop-blur">
                    <tr>
                      <th className="px-3 py-2 font-medium">Kind</th>
                      <th className="px-3 py-2 font-medium">Target</th>
                      <th className="px-3 py-2 font-medium">Status</th>
                      <th className="px-3 py-2 text-right font-medium">
                        Train set
                      </th>
                      <th className="px-3 py-2 text-right font-medium">
                        Duration
                      </th>
                      <th className="px-3 py-2 font-medium">Started</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((run) => {
                      const size = trainingSetSize(run);
                      const cls = run.target_class_id
                        ? classById.get(run.target_class_id)
                        : undefined;
                      const duration = runDurationSec(run, now);
                      const selected = selectedId === run.id;
                      const activated = run.metrics?.activated === true;
                      return (
                        <tr
                          key={run.id}
                          onClick={() => setSelectedId(run.id)}
                          className={cn(
                            "cursor-pointer border-t border-border transition-colors",
                            selected
                              ? "bg-accent/70"
                              : "hover:bg-muted/60",
                          )}
                        >
                          <td
                            className={cn(
                              "relative px-3 py-2",
                              selected &&
                                "before:absolute before:inset-y-0 before:left-0 before:w-0.5 before:bg-foreground",
                            )}
                          >
                            <div className="flex items-center gap-2">
                              <KindChip kind={run.kind} />
                              {activated && (
                                <span
                                  title="Activated as the current model"
                                  className="inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500"
                                />
                              )}
                            </div>
                          </td>
                          <td className="max-w-[12rem] px-3 py-2">
                            <ClassCell cls={cls} />
                          </td>
                          <td className="px-3 py-2">
                            <StatusBadge status={run.status} />
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {size == null ? (
                              <span className="text-muted-foreground">—</span>
                            ) : (
                              size.toLocaleString()
                            )}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">
                            {run.status === "running" && duration != null ? (
                              <span className="inline-flex items-center gap-1 text-blue-600 dark:text-blue-300">
                                <Activity className="h-3 w-3 animate-pulse" />
                                {formatElapsed(duration)}
                              </span>
                            ) : (
                              formatElapsed(duration)
                            )}
                          </td>
                          <td
                            className="whitespace-nowrap px-3 py-2 text-muted-foreground"
                            title={
                              run.started_at
                                ? new Date(run.started_at).toLocaleString()
                                : undefined
                            }
                          >
                            {formatRelative(run.started_at, now)}
                          </td>
                        </tr>
                      );
                    })}
                    <TableSentinelRow
                      colSpan={6}
                      hasMore={hasNextPage}
                      isFetching={isFetchingNextPage}
                      onLoadMore={loadMore}
                      rootRef={tableScrollRef}
                    >
                      {isFetchingNextPage ? (
                        <div className="flex items-center justify-center gap-2 px-3 py-3 text-xs text-muted-foreground">
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          Loading more…
                        </div>
                      ) : !hasNextPage ? (
                        <div className="px-3 py-2 text-center text-[11px] text-muted-foreground">
                          End of results — {total.toLocaleString()}{" "}
                          {total === 1 ? "run" : "runs"} total
                        </div>
                      ) : null}
                    </TableSentinelRow>
                  </tbody>
                </table>
              )}
            </div>

            <div className="overflow-auto rounded-lg border border-border bg-card p-4">
              {selectedId ? (
                <RunDetail runId={selectedId} classById={classById} />
              ) : (
                <div className="flex h-full min-h-[12rem] flex-col items-center justify-center gap-2 text-center">
                  <div className="flex h-9 w-9 items-center justify-center rounded-full bg-muted text-muted-foreground">
                    <CheckCircle2 className="h-4 w-4" />
                  </div>
                  <p className="text-sm font-medium">No run selected</p>
                  <p className="max-w-[18rem] text-xs text-muted-foreground">
                    Pick a run from the list to see metrics, status, and the
                    training log tail.
                  </p>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
