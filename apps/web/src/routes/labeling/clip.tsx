import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { DetectionPreview } from "@/components/labeling/DetectionPreview";
import { DetectionTileGrid } from "@/components/labeling/DetectionTileGrid";
import { LabelingTabs } from "@/components/labeling/LabelingTabs";
import { formatClipName } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useClasses } from "@/hooks/useClasses";
import { useClip } from "@/hooks/useFrames";
import { useSubclasses } from "@/hooks/useSubclasses";
import {
  useBulkApply,
  useClipClassSummary,
  useClipDetections,
} from "@/hooks/useBulkLabeling";
import type { GalleryInclude } from "@/hooks/useSubclasses";

const INCLUDE_CHIPS: ReadonlyArray<{ value: GalleryInclude; label: string }> = [
  { value: "all", label: "All" },
  { value: "auto", label: "Auto" },
  { value: "reviewed", label: "Reviewed" },
];

export function LabelingClip() {
  const { id = "" } = useParams<{ id: string }>();
  const { data: clip } = useClip(id);
  const { data: classes = [] } = useClasses();
  const { data: summary = [], isPending: summaryPending } =
    useClipClassSummary(id);

  // Default the class filter to the most-common class once the summary lands.
  const [classFilter, setClassFilter] = useState<string>("");
  useEffect(() => {
    if (!classFilter && summary.length > 0 && summary[0].class_id) {
      setClassFilter(summary[0].class_id);
    }
  }, [classFilter, summary]);

  const [include, setInclude] = useState<GalleryInclude>("auto");
  const { data: items = [], isPending } = useClipDetections({
    clipId: id,
    classId: classFilter || undefined,
    include,
  });

  // Target class for the bulk apply — defaults to the filter class but can
  // diverge when the user wants to reassign mis-classified detections (e.g.
  // a YOLO-tagged "dog" crop that's actually a cat).
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
  // New filter / class change → reset selection and focus to avoid carrying
  // ids that are no longer visible.
  useEffect(() => {
    setSelected(new Set());
    setFocusedId(null);
  }, [classFilter, include]);
  // Default focus to the first tile once a list arrives, so the preview
  // panel always has something rendered.
  useEffect(() => {
    if (!focusedId && items.length > 0) {
      setFocusedId(items[0].id);
    }
  }, [focusedId, items]);

  const focusedItem = items.find((i) => i.id === focusedId) ?? null;

  const colorBySub = useMemo(
    () => Object.fromEntries(activeSubclasses.map((s) => [s.id, s.color_hex])),
    [activeSubclasses],
  );

  const bulk = useBulkApply();
  const targetSubName =
    activeSubclasses.find((s) => s.id === targetSubclass)?.name ?? "";
  const activeClasses = useMemo(
    () => classes.filter((c) => c.is_active),
    [classes],
  );
  const targetClassName =
    activeClasses.find((c) => c.id === targetClass)?.name ?? "";
  const classReassign = Boolean(targetClass) && targetClass !== classFilter;
  const canApply =
    selected.size > 0 && (Boolean(targetSubclass) || classReassign);

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

  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumbs={[
          { label: "Clips", to: "/clips" },
          {
            label: clip ? formatClipName(clip.created_at) : "Clip",
            to: `/clips/${id}`,
          },
        ]}
        title="Bulk label this clip"
        description="Every detection of the chosen class across the whole clip. Multi-select, then apply a sub-class to all at once."
      />
      <LabelingTabs current="clip" />

      <div className="flex flex-wrap items-center gap-3">
        <Select
          value={classFilter}
          onChange={(e) => setClassFilter(e.target.value)}
          disabled={summaryPending}
        >
          <option value="">Pick a class…</option>
          {summary
            .filter((s) => s.class_id)
            .map((s) => (
              <option key={s.class_id ?? ""} value={s.class_id ?? ""}>
                {s.class_name ?? "—"} ({s.count})
              </option>
            ))}
        </Select>
        <div className="inline-flex rounded-md border border-input">
          {INCLUDE_CHIPS.map((c) => (
            <button
              key={c.value}
              type="button"
              onClick={() => setInclude(c.value)}
              className={cn(
                "px-3 py-1 text-xs first:rounded-l-md last:rounded-r-md transition-colors",
                include === c.value
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-muted",
              )}
            >
              {c.label}
            </button>
          ))}
        </div>
        <span className="text-xs text-muted-foreground">
          {selected.size} of {items.length} selected
        </span>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setSelected(new Set(items.map((i) => i.id)))}
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
          {/* Target class picker — defaults to the filter but can diverge to
              reassign mis-classified detections. */}
          <Select
            value={targetClass}
            onChange={(e) => setTargetClass(e.target.value)}
            className="h-8 text-xs"
            title="Target class to assign"
            disabled={activeClasses.length === 0}
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
          ) : items.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No detections match the current filter.
            </p>
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
