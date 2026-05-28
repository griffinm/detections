import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { DetectionPreview } from "@/components/labeling/DetectionPreview";
import {
  DetectionThumbStrip,
  DetectionTileGrid,
} from "@/components/labeling/DetectionTileGrid";
import { LabelingTabs } from "@/components/labeling/LabelingTabs";
import { cn } from "@/lib/utils";
import { useClasses, type VdClass } from "@/hooks/useClasses";
import { useSubclasses } from "@/hooks/useSubclasses";
import {
  useBulkApply,
  usePredictedGroupDetections,
  usePredictedGroups,
  type ConfidenceBucket,
  type PredictedGroup,
} from "@/hooks/useBulkLabeling";

const BUCKET_LABEL: Record<ConfidenceBucket, string> = {
  high: "High confidence",
  med: "Medium confidence",
  low: "Low confidence",
};

const BUCKET_CLASSES: Record<ConfidenceBucket, string> = {
  high:
    "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200",
  med: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200",
  low: "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-200",
};

function groupKey(g: PredictedGroup): string {
  return `${g.predicted_subclass_id}:${g.confidence_bucket}`;
}

function GroupCard({
  group,
  onSelect,
}: {
  group: PredictedGroup;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className="block w-full rounded-lg border border-border bg-card p-4 text-left transition-colors hover:bg-muted"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-baseline gap-2">
            <h3 className="truncate text-base font-semibold">
              {group.predicted_subclass_name}
            </h3>
            <span className="truncate text-xs text-muted-foreground">
              {group.class_name ?? "—"}
            </span>
          </div>
          <div className="mt-1 flex items-center gap-2">
            <span
              className={cn(
                "rounded px-2 py-0.5 text-xs font-medium",
                BUCKET_CLASSES[group.confidence_bucket],
              )}
            >
              {BUCKET_LABEL[group.confidence_bucket]}
            </span>
            <span className="text-xs text-muted-foreground">
              {group.count} detection{group.count === 1 ? "" : "s"}
            </span>
          </div>
        </div>
      </div>
      <div className="mt-3">
        <DetectionThumbStrip detectionIds={group.sample_detection_ids} />
      </div>
    </button>
  );
}

function GroupDetail({
  group,
  classes,
  onBack,
}: {
  group: PredictedGroup;
  classes: VdClass[];
  onBack: () => void;
}) {
  const { data: items = [], isPending } = usePredictedGroupDetections({
    predictedSubclassId: group.predicted_subclass_id,
    bucket: group.confidence_bucket,
  });
  const activeClasses = useMemo(
    () => classes.filter((c) => c.is_active),
    [classes],
  );
  // Target class for the bulk apply — defaults to the group's class but can
  // diverge to reassign mis-classified detections (e.g. predicted-as-dog
  // crops that are actually cats).
  const [targetClass, setTargetClass] = useState<string>(group.class_id ?? "");
  const { data: subclasses = [] } = useSubclasses(targetClass || undefined);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [targetSubclass, setTargetSubclass] = useState<string>(
    group.predicted_subclass_id,
  );
  const bulk = useBulkApply();

  // When the full list lands, default every tile to selected — the common
  // case is "yes, confirm them all" — and focus the first tile so the
  // preview panel has something to show.
  const allIds = useMemo(() => items.map((i) => i.id), [items]);
  useEffect(() => {
    setSelected(new Set(allIds));
    setFocusedId(allIds[0] ?? null);
  }, [allIds]);

  const activeSubclasses = subclasses.filter((s) => s.is_active);
  // When the target class changes away from the group's class the predicted
  // sub-class no longer belongs to it — drop to "(no sub-class)" and let the
  // user pick from the new class. When they switch back, default to the
  // group's prediction again.
  useEffect(() => {
    if (activeSubclasses.length === 0) {
      setTargetSubclass("");
      return;
    }
    if (!activeSubclasses.some((s) => s.id === targetSubclass)) {
      setTargetSubclass(
        targetClass === group.class_id ? group.predicted_subclass_id : "",
      );
    }
  }, [
    activeSubclasses,
    targetSubclass,
    targetClass,
    group.class_id,
    group.predicted_subclass_id,
  ]);
  const targetSubName =
    activeSubclasses.find((s) => s.id === targetSubclass)?.name ?? "";
  const targetClassName =
    activeClasses.find((c) => c.id === targetClass)?.name ?? "";
  const classReassign =
    Boolean(targetClass) && targetClass !== group.class_id;
  const canApply =
    selected.size > 0 && (Boolean(targetSubclass) || classReassign);
  const colorBySub = useMemo(
    () => Object.fromEntries(activeSubclasses.map((s) => [s.id, s.color_hex])),
    [activeSubclasses],
  );
  const focusedItem = items.find((i) => i.id === focusedId) ?? null;

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
      reviewed: true,
    };
    const effectiveClass = targetClass || group.class_id;
    if (effectiveClass) payload.class_id = effectiveClass;
    if (targetSubclass) payload.subclass_id = targetSubclass;
    bulk.mutate(payload, {
      onSuccess: (result) => {
        toast.success(
          `Applied to ${result.updated} detection${
            result.updated === 1 ? "" : "s"
          }${result.skipped ? ` (${result.skipped} skipped)` : ""}`,
        );
        onBack();
      },
      onError: () => toast.error("Failed to apply"),
    });
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="outline" size="sm" onClick={onBack}>
          <ArrowLeft className="h-3.5 w-3.5" /> Back to groups
        </Button>
        <div className="min-w-0">
          <div className="flex items-baseline gap-2">
            <h2 className="truncate text-lg font-semibold">
              {group.predicted_subclass_name}
            </h2>
            <span className="truncate text-xs text-muted-foreground">
              {group.class_name ?? "—"} · {BUCKET_LABEL[group.confidence_bucket]}
            </span>
          </div>
          <p className="text-xs text-muted-foreground">
            {selected.size} of {items.length} selected
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setSelected(new Set(allIds))}
            disabled={items.length === 0}
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
            disabled={activeClasses.length === 0}
          >
            {activeClasses.map((c) => (
              <option key={c.id} value={c.id}>
                {c.id === group.class_id ? c.name : `→ ${c.name}`}
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
          <Button onClick={apply} disabled={bulk.isPending || !canApply}>
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
        <div>
          {isPending ? (
            <div className="flex flex-wrap gap-2">
              {[...Array(12)].map((_, i) => (
                <div
                  key={i}
                  className="h-24 w-24 animate-pulse rounded border-2 border-border bg-muted"
                />
              ))}
            </div>
          ) : (
            <DetectionTileGrid
              items={items}
              selectedIds={selected}
              onSelectionChange={setSelected}
              focusedId={focusedId}
              onFocusChange={setFocusedId}
              borderColorByItem={(it) =>
                it.subclass_id ? colorBySub[it.subclass_id] : undefined
              }
            />
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
    </div>
  );
}

export function LabelingGroups() {
  const { data: classes = [] } = useClasses();
  const [classFilter, setClassFilter] = useState("");
  const { data: groups = [], isPending } = usePredictedGroups({
    classId: classFilter || undefined,
  });
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const selectedGroup =
    groups.find((g) => groupKey(g) === selectedKey) ?? null;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Bulk labeling"
        description="Confirm or correct the model's sub-class prediction for an entire group of auto-assigned detections at once."
        actions={
          !selectedGroup && (
            <Select
              value={classFilter}
              onChange={(e) => setClassFilter(e.target.value)}
            >
              <option value="">All classes</option>
              {classes
                .filter((c) => c.is_active)
                .map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
            </Select>
          )
        }
      />
      <LabelingTabs current="groups" />

      {selectedGroup ? (
        <GroupDetail
          group={selectedGroup}
          classes={classes}
          onBack={() => setSelectedKey(null)}
        />
      ) : isPending ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-32 animate-pulse rounded-lg bg-muted" />
          ))}
        </div>
      ) : groups.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No auto-assigned detections waiting for review. Drop a clip or wait
          for the worker to finish sub-class assignment.
        </p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {groups.map((g) => (
            <GroupCard
              key={groupKey(g)}
              group={g}
              onSelect={() => setSelectedKey(groupKey(g))}
            />
          ))}
        </div>
      )}
    </div>
  );
}
