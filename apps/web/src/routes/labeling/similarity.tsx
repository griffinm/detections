import { useEffect, useMemo, useState } from "react";
import { CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { DetectionPreview } from "@/components/labeling/DetectionPreview";
import { DetectionTileGrid } from "@/components/labeling/DetectionTileGrid";
import { LabelingTabs } from "@/components/labeling/LabelingTabs";
import { useClasses } from "@/hooks/useClasses";
import { useSubclasses } from "@/hooks/useSubclasses";
import {
  useBulkApply,
  useSimilarityClusters,
  type SimilarityCluster,
} from "@/hooks/useBulkLabeling";
import type { DetectionGalleryItem } from "@/hooks/useSubclasses";

const CLUSTER_SIZE_OPTIONS = [4, 8, 16] as const;

export function LabelingSimilarity() {
  const { data: classes = [] } = useClasses();
  const activeClasses = useMemo(
    () => classes.filter((c) => c.is_active),
    [classes],
  );

  const [classFilter, setClassFilter] = useState("");
  const [clusterSize, setClusterSize] = useState<number>(8);
  const { data, isPending, isFetching } = useSimilarityClusters({
    classId: classFilter || undefined,
    clusterSize,
  });

  // Target class for the bulk apply — defaults to the filter class but can
  // diverge when the user wants to fix mis-classified detections (e.g. a
  // YOLO-tagged "dog" crop that's actually a cat).
  const [targetClass, setTargetClass] = useState<string>("");
  useEffect(() => {
    setTargetClass(classFilter);
  }, [classFilter]);

  const { data: subclasses = [] } = useSubclasses(targetClass || undefined);
  const activeSubclasses = subclasses.filter((s) => s.is_active);
  const [targetSubclass, setTargetSubclass] = useState<string>("");
  useEffect(() => {
    if (activeSubclasses.length === 0) {
      setTargetSubclass("");
    } else if (!activeSubclasses.some((s) => s.id === targetSubclass)) {
      setTargetSubclass(activeSubclasses[0].id);
    }
  }, [activeSubclasses, targetSubclass]);

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [focusedId, setFocusedId] = useState<string | null>(null);

  // Class change → reset selection; the visible ids change wholesale.
  useEffect(() => {
    setSelected(new Set());
    setFocusedId(null);
  }, [classFilter, clusterSize]);

  const allItems: DetectionGalleryItem[] = useMemo(
    () => (data?.clusters ?? []).flatMap((c) => c.members),
    [data],
  );
  useEffect(() => {
    if (!focusedId && allItems.length > 0) {
      setFocusedId(allItems[0].id);
    }
  }, [focusedId, allItems]);

  const focusedItem = allItems.find((i) => i.id === focusedId) ?? null;

  const colorBySub = useMemo(
    () => Object.fromEntries(activeSubclasses.map((s) => [s.id, s.color_hex])),
    [activeSubclasses],
  );

  const bulk = useBulkApply();
  const targetSubName =
    activeSubclasses.find((s) => s.id === targetSubclass)?.name ?? "";
  const targetClassName =
    activeClasses.find((c) => c.id === targetClass)?.name ?? "";
  const classReassign = Boolean(targetClass) && targetClass !== classFilter;
  const canApply =
    selected.size > 0 && (Boolean(targetSubclass) || classReassign);

  const selectCluster = (cluster: SimilarityCluster): void => {
    const next = new Set(selected);
    for (const m of cluster.members) next.add(m.id);
    setSelected(next);
  };

  const apply = (): void => {
    if (selected.size === 0) {
      toast.error("Select at least one detection");
      return;
    }
    if (!targetSubclass && !classReassign) {
      toast.error("Pick a sub-class or a different target class to apply");
      return;
    }
    const payload: Parameters<typeof bulk.mutate>[0] = {
      detection_ids: [...selected],
      class_id: targetClass || classFilter,
      reviewed: true,
    };
    if (targetSubclass) payload.subclass_id = targetSubclass;
    bulk.mutate(payload, {
      onSuccess: (result) => {
        toast.success(
          `Applied to ${result.updated} detection${
            result.updated === 1 ? "" : "s"
          }${result.skipped ? ` (${result.skipped} skipped)` : ""}`,
        );
        setSelected(new Set());
      },
      onError: () => toast.error("Failed to apply"),
    });
  };

  const clusters = data?.clusters ?? [];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Similarity clusters"
        description="Group un-reviewed, un-assigned detections by embedding similarity — no model prediction baked in. Select across clusters and apply a sub-class."
        actions={
          <>
            <Select
              value={classFilter}
              onChange={(e) => setClassFilter(e.target.value)}
            >
              <option value="">Pick a class…</option>
              {activeClasses.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
            <Select
              value={String(clusterSize)}
              onChange={(e) => setClusterSize(Number(e.target.value))}
              className="w-28"
            >
              {CLUSTER_SIZE_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  Size {n}
                </option>
              ))}
            </Select>
          </>
        }
      />
      <LabelingTabs current="similarity" />

      {!classFilter ? (
        <p className="text-sm text-muted-foreground">
          Pick a class above to compute clusters.
        </p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-xs text-muted-foreground">
              {selected.size} of {allItems.length} selected
              {data ? (
                <>
                  {" · "}
                  {clusters.length} cluster
                  {clusters.length === 1 ? "" : "s"} · pool {data.pool_size}
                  {data.pool_truncated ? "+" : ""}
                  {data.remaining > 0
                    ? ` · ${data.remaining} left over (refresh after applying)`
                    : ""}
                </>
              ) : null}
            </span>
            <div className="ml-auto flex flex-wrap items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() =>
                  setSelected(new Set(allItems.map((i) => i.id)))
                }
                disabled={allItems.length === 0}
              >
                Select all
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setSelected(new Set())}
                disabled={selected.size === 0}
              >
                Clear
              </Button>
              <Select
                value={targetClass}
                onChange={(e) => setTargetClass(e.target.value)}
                className="h-8 text-xs"
                title="Target class to assign"
              >
                {activeClasses.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.id === classFilter ? c.name : `→ ${c.name}`}
                  </option>
                ))}
              </Select>
              {activeSubclasses.length > 0 ? (
                <Select
                  value={targetSubclass}
                  onChange={(e) => setTargetSubclass(e.target.value)}
                  className="h-8 text-xs"
                >
                  <option value="">(no sub-class)</option>
                  {activeSubclasses.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </Select>
              ) : (
                <span className="text-xs text-muted-foreground">
                  No sub-classes for {targetClassName || "this class"}
                </span>
              )}
              <Button
                onClick={apply}
                disabled={bulk.isPending || !canApply}
              >
                <CheckCircle2 className="h-4 w-4" />
                {targetSubName
                  ? `Apply “${targetSubName}”`
                  : classReassign
                    ? `Reassign to “${targetClassName}”`
                    : "Apply"}
              </Button>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
            <div className="space-y-6">
              {isPending || isFetching ? (
                <div className="flex flex-wrap gap-2">
                  {[...Array(16)].map((_, i) => (
                    <div
                      key={i}
                      className="h-24 w-24 animate-pulse rounded border-2 border-border bg-muted"
                    />
                  ))}
                </div>
              ) : clusters.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No un-reviewed, un-assigned detections in this class. Try the
                  Predicted groups tab if the model has already labeled them.
                </p>
              ) : (
                clusters.map((cluster, idx) => {
                  const allSelected = cluster.members.every((m) =>
                    selected.has(m.id),
                  );
                  return (
                    <section key={cluster.seed_id} className="space-y-2">
                      <div className="flex flex-wrap items-baseline gap-3">
                        <h3 className="text-sm font-semibold">
                          Cluster {idx + 1}
                        </h3>
                        <span className="text-xs text-muted-foreground">
                          {cluster.members.length} item
                          {cluster.members.length === 1 ? "" : "s"} · avg
                          distance {cluster.avg_distance.toFixed(3)}
                        </span>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="ml-auto"
                          onClick={() =>
                            allSelected
                              ? setSelected((s) => {
                                  const next = new Set(s);
                                  for (const m of cluster.members)
                                    next.delete(m.id);
                                  return next;
                                })
                              : selectCluster(cluster)
                          }
                        >
                          {allSelected ? "Deselect cluster" : "Select cluster"}
                        </Button>
                      </div>
                      <DetectionTileGrid
                        items={cluster.members}
                        selectedIds={selected}
                        onSelectionChange={setSelected}
                        focusedId={focusedId}
                        onFocusChange={setFocusedId}
                        borderColorByItem={(it) =>
                          it.subclass_id
                            ? colorBySub[it.subclass_id]
                            : undefined
                        }
                      />
                    </section>
                  );
                })
              )}
            </div>
            <DetectionPreview
              item={focusedItem}
              bboxColor={
                focusedItem?.subclass_id
                  ? colorBySub[focusedItem.subclass_id]
                  : undefined
              }
            />
          </div>
        </>
      )}
    </div>
  );
}
