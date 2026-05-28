import { Fragment, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { TableSentinelRow } from "@/components/ui/InfiniteScrollSentinel";
import { cn } from "@/lib/utils";
import {
  useActivateModel,
  useModelsInfinite,
  type ModelKindFilter,
  type ModelVersion,
} from "@/hooks/useModels";

type KindFilter = "all" | ModelKindFilter;
type StatusFilter = "all" | "active" | "inactive";

const KIND_FILTERS: { value: KindFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "yolo", label: "YOLO" },
  { value: "insightface", label: "InsightFace" },
  { value: "classifier", label: "Classifier" },
];

const STATUS_FILTERS: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "active", label: "Active" },
  { value: "inactive", label: "Inactive" },
];

interface PerClassEntry {
  class: string;
  prev: number | null;
  new: number | null;
  prev_val_samples: number;
  new_val_samples: number;
  status: "pass" | "fail" | "skipped";
  reason?: string;
}

interface RegressionCheck {
  aggregate: {
    prev: number | null;
    new: number;
    tolerance: number;
    pass: boolean;
  };
  per_class: PerClassEntry[];
  per_class_tolerance: number;
  min_val_samples: number;
  blocked_classes: string[];
  activate: boolean;
}

/** A one-line headline metric for the table — mAP for YOLO, accuracy for a classifier. */
function metricSummary(model: ModelVersion): string {
  const metrics = model.metrics ?? {};
  const map = metrics.val_map50_95;
  const acc = metrics.val_accuracy;
  if (model.kind === "yolo" && typeof map === "number") {
    return `mAP50-95 ${map.toFixed(3)}`;
  }
  if (model.kind === "classifier" && typeof acc === "number") {
    return `acc ${(acc * 100).toFixed(1)}%`;
  }
  return typeof metrics.source === "string" ? metrics.source : "—";
}

function fmt(v: number | null | undefined): string {
  return typeof v === "number" ? v.toFixed(3) : "—";
}

function statusPill(status: PerClassEntry["status"]): string {
  if (status === "pass") return "text-green-600";
  if (status === "fail") return "text-destructive";
  return "text-muted-foreground";
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

function RegressionPanel({ check }: { check: RegressionCheck }) {
  const agg = check.aggregate;
  const aggDelta =
    typeof agg.prev === "number" ? agg.new - agg.prev : null;
  return (
    <div className="space-y-3 px-4 py-3 text-sm">
      <div>
        <div className="text-xs uppercase tracking-wide text-muted-foreground">
          Activation guard
        </div>
        <div className="mt-1 flex items-baseline gap-2">
          <span className={check.activate ? "text-green-600" : "text-destructive"}>
            {check.activate ? "Activated" : "Blocked"}
          </span>
          {!check.activate && check.blocked_classes.length > 0 && (
            <span className="text-xs text-muted-foreground">
              blocked by: {check.blocked_classes.join(", ")}
            </span>
          )}
          {!check.activate && !agg.pass && (
            <span className="text-xs text-muted-foreground">
              blocked by aggregate mAP regression
            </span>
          )}
        </div>
        <div className="mt-1 text-xs text-muted-foreground tabular-nums">
          aggregate mAP50-95: {fmt(agg.prev)} → {fmt(agg.new)}
          {aggDelta !== null && (
            <span className={aggDelta < 0 ? "text-destructive" : "text-green-600"}>
              {" "}({aggDelta >= 0 ? "+" : ""}{aggDelta.toFixed(3)})
            </span>
          )}
          {" "}· tolerance {agg.tolerance.toFixed(3)}
        </div>
      </div>

      <div>
        <div className="text-xs uppercase tracking-wide text-muted-foreground">
          Per-class (tolerance {check.per_class_tolerance.toFixed(3)},
          min {check.min_val_samples} val samples)
        </div>
        <table className="mt-2 w-full text-xs tabular-nums">
          <thead className="text-left text-muted-foreground">
            <tr>
              <th className="py-1 pr-3 font-medium">Class</th>
              <th className="py-1 pr-3 font-medium">Prev mAP</th>
              <th className="py-1 pr-3 font-medium">New mAP</th>
              <th className="py-1 pr-3 font-medium">Δ</th>
              <th className="py-1 pr-3 font-medium">Val samples</th>
              <th className="py-1 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {check.per_class.map((e) => {
              const delta =
                typeof e.prev === "number" && typeof e.new === "number"
                  ? e.new - e.prev
                  : null;
              return (
                <tr key={e.class} className="border-t border-border/50">
                  <td className="py-1 pr-3">{e.class}</td>
                  <td className="py-1 pr-3">{fmt(e.prev)}</td>
                  <td className="py-1 pr-3">{fmt(e.new)}</td>
                  <td
                    className={`py-1 pr-3 ${
                      delta !== null && delta < 0
                        ? "text-destructive"
                        : delta !== null && delta > 0
                          ? "text-green-600"
                          : ""
                    }`}
                  >
                    {delta !== null
                      ? `${delta >= 0 ? "+" : ""}${delta.toFixed(3)}`
                      : "—"}
                  </td>
                  <td className="py-1 pr-3 text-muted-foreground">
                    {e.prev_val_samples} → {e.new_val_samples}
                  </td>
                  <td className={`py-1 ${statusPill(e.status)}`}>
                    {e.status}
                    {e.reason ? (
                      <span className="ml-1 text-muted-foreground">({e.reason})</span>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PerClassOnly({ model }: { model: ModelVersion }) {
  const m = (model.metrics ?? {}) as Record<string, unknown>;
  const perClass = (m.per_class_map50_95 ?? {}) as Record<string, number>;
  const valCounts = (m.per_class_val_samples ?? {}) as Record<string, number>;
  const names = Object.keys(perClass).sort();
  if (names.length === 0) return null;
  return (
    <div className="space-y-2 px-4 py-3 text-sm">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">
        Per-class mAP50-95
      </div>
      <table className="w-full text-xs tabular-nums">
        <thead className="text-left text-muted-foreground">
          <tr>
            <th className="py-1 pr-3 font-medium">Class</th>
            <th className="py-1 pr-3 font-medium">mAP50-95</th>
            <th className="py-1 font-medium">Val samples</th>
          </tr>
        </thead>
        <tbody>
          {names.map((name) => (
            <tr key={name} className="border-t border-border/50">
              <td className="py-1 pr-3">{name}</td>
              <td className="py-1 pr-3">{fmt(perClass[name])}</td>
              <td className="py-1 text-muted-foreground">
                {valCounts[name] ?? 0}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ModelDetail({ model }: { model: ModelVersion }) {
  const m = (model.metrics ?? {}) as Record<string, unknown>;
  const check = m.regression_check as RegressionCheck | undefined;
  if (check) return <RegressionPanel check={check} />;
  return <PerClassOnly model={model} />;
}

export function ModelsPage() {
  const [kindFilter, setKindFilter] = useState<KindFilter>("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [open, setOpen] = useState<Set<string>>(new Set());

  const filters = useMemo(
    () => ({
      kind: kindFilter === "all" ? undefined : kindFilter,
      is_active:
        statusFilter === "all"
          ? undefined
          : statusFilter === "active",
    }),
    [kindFilter, statusFilter],
  );

  const {
    rows: models,
    total,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
    isPending,
  } = useModelsInfinite(filters);

  const activate = useActivateModel();
  const tableScrollRef = useRef<HTMLDivElement>(null);
  const loadMore = useMemo(() => () => void fetchNextPage(), [fetchNextPage]);

  const toggle = (id: string) =>
    setOpen((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const onActivate = async (model: ModelVersion): Promise<void> => {
    try {
      await activate.mutateAsync(model.id);
      toast.success(`Activated ${model.name}`);
    } catch {
      toast.error("Could not activate model");
    }
  };

  const filtersActive = kindFilter !== "all" || statusFilter !== "all";

  return (
    <div className="flex h-full flex-col gap-4">
      <PageHeader
        title="Models"
        description="YOLO detectors and sub-class classifiers. One version per kind is active."
      />

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
            Kind
          </span>
          <SegmentedFilter
            value={kindFilter}
            options={KIND_FILTERS}
            onChange={setKindFilter}
          />
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
            Status
          </span>
          <SegmentedFilter
            value={statusFilter}
            options={STATUS_FILTERS}
            onChange={setStatusFilter}
          />
        </div>
      </div>

      {isPending ? (
        <div className="space-y-1.5">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-11 animate-pulse rounded bg-muted" />
          ))}
        </div>
      ) : models.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {filtersActive
            ? "No models match the current filters."
            : "No model versions yet."}
        </p>
      ) : (
        <div
          ref={tableScrollRef}
          className="min-h-0 flex-1 overflow-auto rounded-lg border border-border"
        >
          <table className="w-full min-w-[640px] text-sm">
            <thead className="sticky top-0 z-10 bg-muted/95 text-left text-xs uppercase text-muted-foreground backdrop-blur">
              <tr>
                <th className="w-8 px-3 py-2" />
                <th className="px-3 py-2 font-medium">Name</th>
                <th className="px-3 py-2 font-medium">Kind</th>
                <th className="px-3 py-2 font-medium">Metrics</th>
                <th className="px-3 py-2 font-medium">Trained on</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {models.map((model) => {
                const m = (model.metrics ?? {}) as Record<string, unknown>;
                const expandable =
                  model.kind === "yolo" &&
                  (m.regression_check !== undefined ||
                    m.per_class_map50_95 !== undefined);
                const isOpen = open.has(model.id);
                return (
                  <Fragment key={model.id}>
                    <tr className="border-t border-border">
                      <td className="px-3 py-2">
                        {expandable && (
                          <button
                            type="button"
                            aria-label={isOpen ? "Collapse" : "Expand"}
                            onClick={() => toggle(model.id)}
                            className="text-muted-foreground hover:text-foreground"
                          >
                            {isOpen ? (
                              <ChevronDown className="h-4 w-4" />
                            ) : (
                              <ChevronRight className="h-4 w-4" />
                            )}
                          </button>
                        )}
                      </td>
                      <td className="px-3 py-2">{model.name}</td>
                      <td className="px-3 py-2 text-muted-foreground">
                        {model.kind}
                      </td>
                      <td className="px-3 py-2 tabular-nums">
                        {metricSummary(model)}
                      </td>
                      <td className="px-3 py-2 tabular-nums text-muted-foreground">
                        {model.trained_on ?? "—"}
                      </td>
                      <td className="px-3 py-2">
                        {model.is_active ? (
                          <span className="text-green-600">active</span>
                        ) : (
                          <span className="text-muted-foreground">inactive</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {!model.is_active && (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => void onActivate(model)}
                          >
                            Activate
                          </Button>
                        )}
                      </td>
                    </tr>
                    {expandable && isOpen && (
                      <tr className="bg-muted/30">
                        <td />
                        <td colSpan={6}>
                          <ModelDetail model={model} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
              <TableSentinelRow
                colSpan={7}
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
                    {total === 1 ? "model" : "models"} total
                  </div>
                ) : null}
              </TableSentinelRow>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
