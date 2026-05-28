import { useEffect, useMemo, useState } from "react";
import { Check, ChevronDown, SkipForward, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { LabelingTabs } from "@/components/labeling/LabelingTabs";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useClasses, type VdClass } from "@/hooks/useClasses";
import { useSubclasses, type VdSubclass } from "@/hooks/useSubclasses";
import {
  useDeleteDetectionGallery,
  useDetectionsQueue,
  usePatchDetection,
} from "@/hooks/useDetections";
import type { DetectionGalleryItem } from "@/hooks/useSubclasses";

/** Pre-fetch the next page when we get within this many items of the end. */
const PREFETCH_THRESHOLD = 5;

export function LabelingQuick() {
  const [classFilter, setClassFilter] = useState<string>("");
  const [index, setIndex] = useState(0);
  const queue = useDetectionsQueue({
    include: "auto",
    classId: classFilter || undefined,
  });
  const { rows, total, hasNextPage, isFetchingNextPage, fetchNextPage, isPending } =
    queue;

  // Walking off the end of a loaded page → grab the next one.
  useEffect(() => {
    if (
      !isPending &&
      hasNextPage &&
      !isFetchingNextPage &&
      index >= rows.length - PREFETCH_THRESHOLD
    ) {
      void fetchNextPage();
    }
  }, [index, rows.length, hasNextPage, isFetchingNextPage, isPending, fetchNextPage]);

  // Filter change should always restart at the top of the new queue.
  useEffect(() => {
    setIndex(0);
  }, [classFilter]);

  // The optimistic-splice mutation removes the current item from the array,
  // so the cursor "naturally advances" without us incrementing. But if we
  // overshoot (last item handled, no more pages), clamp back.
  useEffect(() => {
    if (rows.length > 0 && index >= rows.length && !hasNextPage) {
      setIndex(Math.max(0, rows.length - 1));
    }
  }, [rows.length, index, hasNextPage]);

  const current: DetectionGalleryItem | undefined = rows[index];
  const { data: classes = [] } = useClasses();
  const activeClasses = useMemo(() => classes.filter((c) => c.is_active), [classes]);
  const { data: subclasses = [] } = useSubclasses(current?.class_id ?? undefined);
  const activeSubclasses = useMemo(
    () => subclasses.filter((s) => s.is_active),
    [subclasses],
  );

  return (
    <div className="space-y-3">
      <PageHeader title="Labeling" />
      <LabelingTabs current="quick" />

      <FilterBar
        classFilter={classFilter}
        onClassFilter={setClassFilter}
        classes={activeClasses}
        position={current ? index + 1 : 0}
        total={total}
      />

      {isPending ? (
        <div className="h-64 animate-pulse rounded bg-muted" />
      ) : !current ? (
        <EmptyState classFilter={classFilter} />
      ) : (
        <ReviewCard
          key={current.id}
          item={current}
          classes={activeClasses}
          subclasses={activeSubclasses}
          onSkip={() => setIndex((i) => i + 1)}
        />
      )}
    </div>
  );
}

function FilterBar({
  classFilter,
  onClassFilter,
  classes,
  position,
  total,
}: {
  classFilter: string;
  onClassFilter: (v: string) => void;
  classes: VdClass[];
  position: number;
  total: number;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <NativeSelect
        value={classFilter}
        onChange={(e) => onClassFilter(e.target.value)}
        className="h-9"
      >
        <option value="">All classes</option>
        {classes.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </NativeSelect>
      <span className="ml-auto tabular-nums text-muted-foreground">
        {total === 0 ? "0 to review" : `${position} / ${total} unreviewed`}
      </span>
    </div>
  );
}

function EmptyState({ classFilter }: { classFilter: string }) {
  return (
    <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
      {classFilter
        ? "No unreviewed detections in this class. Try a different filter."
        : "All caught up — nothing to review."}
    </div>
  );
}

/** The single-detection card. Mobile (default): vertical stack — image,
 *  then crop + class/subclass dropdowns, then the action row. Desktop
 *  (`md:`): two-column with image left and the controls column on the
 *  right. Everything is designed to fit a phone viewport without scroll. */
function ReviewCard({
  item,
  classes,
  subclasses,
  onSkip,
}: {
  item: DetectionGalleryItem;
  classes: VdClass[];
  subclasses: VdSubclass[];
  onSkip: () => void;
}) {
  const patch = usePatchDetection();
  const remove = useDeleteDetectionGallery();
  const busy = patch.isPending || remove.isPending;

  const setClass = (next: string): void => {
    const nextId = next || null;
    if (nextId === item.class_id) return;
    patch.mutate(
      // Changing class invalidates the sub-class — clear it in the same hop.
      { id: item.id, patch: { class_id: nextId, subclass_id: null } },
      { onError: () => toast.error("Could not save class") },
    );
  };
  const setSubclass = (next: string): void => {
    const nextId = next || null;
    if (nextId === item.subclass_id) return;
    patch.mutate(
      { id: item.id, patch: { subclass_id: nextId } },
      { onError: () => toast.error("Could not save sub-class") },
    );
  };
  const confirm = (): void => {
    patch.mutate(
      { id: item.id, patch: { reviewed: true } },
      { onError: () => toast.error("Could not confirm detection") },
    );
  };
  const del = (): void => {
    remove.mutate(
      { id: item.id },
      { onError: () => toast.error("Could not delete detection") },
    );
  };

  return (
    <div className="grid gap-3 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
      <FrameView item={item} />
      <div className="flex flex-col gap-3">
        <div className="flex gap-3">
          <CropTile item={item} />
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <Field label="Class">
              <NativeSelect
                value={item.class_id ?? ""}
                onChange={(e) => setClass(e.target.value)}
                disabled={busy}
                className="h-9 w-full"
              >
                <option value="">(none)</option>
                {classes.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </NativeSelect>
            </Field>
            <Field label="Sub-class">
              <NativeSelect
                value={item.subclass_id ?? ""}
                onChange={(e) => setSubclass(e.target.value)}
                disabled={busy || !item.class_id || subclasses.length === 0}
                className="h-9 w-full"
              >
                <option value="">(none)</option>
                {subclasses.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </NativeSelect>
            </Field>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            onClick={confirm}
            disabled={busy}
            className="h-11 flex-1 text-base"
          >
            <Check className="h-4 w-4" /> Confirm
          </Button>
          <Button
            variant="outline"
            onClick={onSkip}
            disabled={busy}
            className="h-11"
          >
            <SkipForward className="h-4 w-4" />
            <span className="hidden sm:inline">Skip</span>
          </Button>
          <Button
            variant="ghost"
            onClick={del}
            disabled={busy}
            className="h-11 text-destructive"
            title="Delete detection"
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}

function FrameView({ item }: { item: DetectionGalleryItem }) {
  const { bbox } = item;
  return (
    <div className="relative overflow-hidden rounded-lg border border-border bg-muted">
      {item.image_url ? (
        <img
          src={item.image_url}
          alt="Source frame"
          className="block max-h-[42vh] w-full object-contain md:max-h-[70vh]"
        />
      ) : (
        <div className="flex h-40 items-center justify-center text-xs text-muted-foreground">
          Frame image unavailable
        </div>
      )}
      {item.image_url ? (
        <div
          className="pointer-events-none absolute border-2"
          style={{
            left: `${bbox.x * 100}%`,
            top: `${bbox.y * 100}%`,
            width: `${bbox.w * 100}%`,
            height: `${bbox.h * 100}%`,
            borderColor: "#facc15",
            boxShadow: "0 0 0 1px rgba(0,0,0,0.6)",
          }}
          aria-hidden
        />
      ) : null}
    </div>
  );
}

function CropTile({ item }: { item: DetectionGalleryItem }) {
  return (
    <div className="h-20 w-20 shrink-0 overflow-hidden rounded border border-border bg-muted sm:h-24 sm:w-24">
      {item.crop_url ? (
        <img
          src={item.crop_url}
          alt="Detection crop"
          className="h-full w-full object-cover"
        />
      ) : null}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

/** Native `<select>` styled to match the shadcn Select but able to fill its
 *  parent — the project's `<Select>` wraps in `inline-flex`, which can't be
 *  stretched to a form-row width without overriding the wrapper. */
function NativeSelect({
  className,
  children,
  ...props
}: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className="relative w-full">
      <select
        {...props}
        className={cn(
          "h-9 w-full appearance-none rounded-md border border-input bg-background pl-3 pr-8 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
          className,
        )}
      >
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
    </div>
  );
}
