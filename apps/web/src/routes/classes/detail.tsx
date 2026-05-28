import { useCallback, useMemo, useState, type MouseEvent } from "react";
import { Link, useParams } from "react-router-dom";
import {
  GraduationCap,
  Image as ImageIcon,
  ListChecks,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Eraser,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { InfiniteScrollSentinel } from "@/components/ui/InfiniteScrollSentinel";
import { Select } from "@/components/ui/select";
import { Tabs, type TabItem } from "@/components/ui/tabs";
import { SubclassFormDialog } from "@/components/SubclassFormDialog";
import { cn } from "@/lib/utils";
import { useClasses, useClassDetections, useClassExamples } from "@/hooks/useClasses";
import { useStartTraining } from "@/hooks/useTraining";
import {
  useDeleteDetectionGallery,
  useRestoreDetectionGallery,
  useRetagDetectionGallery,
  useUntagDetection,
} from "@/hooks/useDetections";
import {
  useDeleteExample,
  useDeleteSubclass,
  useRescanSubclasses,
  useSubclassDetections,
  useSubclassExamples,
  useSubclasses,
  type DetectionGalleryItem,
  type GalleryInclude,
  type GallerySort,
  type SubclassExample,
  type VdSubclass,
} from "@/hooks/useSubclasses";

type GalleryTab = "examples" | "tagged";

/** A 96px tile backed by the server's cached JPEG crop of the detection bbox. */
function ExampleThumb({
  example,
  borderColor,
  onRemove,
}: {
  example: SubclassExample;
  borderColor?: string;
  onRemove?: () => void;
}) {
  return (
    <div className="group relative">
      <div
        className="h-24 w-24 overflow-hidden rounded border-2 bg-muted"
        style={{ borderColor: borderColor ?? "var(--border)" }}
      >
        {example.crop_url ? (
          <img
            src={example.crop_url}
            alt=""
            loading="lazy"
            decoding="async"
            className="h-full w-full object-cover"
          />
        ) : null}
      </div>
      {onRemove ? (
        <button
          onClick={onRemove}
          title="Remove example"
          className="absolute right-1 top-1 hidden rounded bg-background/90 p-1 text-destructive group-hover:block"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      ) : null}
    </div>
  );
}

/** A tagged-detection tile: click to jump into the labeling UI.
 *  Hover surfaces Untag / Delete buttons; either action stops the click from
 *  bubbling to the wrapping Link. */
function TaggedThumb({
  item,
  borderColor,
  onUntag,
  onDelete,
}: {
  item: DetectionGalleryItem;
  borderColor?: string;
  onUntag?: () => void;
  onDelete?: () => void;
}) {
  const reviewed = item.reviewed;
  const stop = (handler: () => void) => (e: MouseEvent<HTMLButtonElement>) => {
    e.preventDefault();
    e.stopPropagation();
    handler();
  };
  return (
    <Link
      to={`/labeling/${item.frame_id}`}
      title={
        reviewed
          ? `Reviewed ${new Date(item.reviewed_at ?? item.created_at).toLocaleString()}`
          : `Auto-assigned ${new Date(item.created_at).toLocaleString()}`
      }
      className="group relative block"
    >
      <div
        className="h-24 w-24 overflow-hidden rounded border-2 bg-muted"
        style={{ borderColor: borderColor ?? "var(--border)" }}
      >
        {item.crop_url ? (
          <img
            src={item.crop_url}
            alt=""
            loading="lazy"
            decoding="async"
            className="h-full w-full object-cover"
          />
        ) : null}
      </div>
      <span
        className={cn(
          "absolute left-1 top-1 h-2.5 w-2.5 rounded-full border border-background",
          reviewed ? "bg-emerald-500" : "bg-amber-500",
        )}
        aria-label={reviewed ? "Reviewed" : "Auto-assigned"}
      />
      {onUntag || onDelete ? (
        <div className="absolute right-1 top-1 hidden gap-1 group-hover:flex">
          {onUntag ? (
            <button
              onClick={stop(onUntag)}
              title="Untag (clear sub-class)"
              className="rounded bg-background/90 p-1 text-muted-foreground hover:text-foreground"
            >
              <Eraser className="h-3.5 w-3.5" />
            </button>
          ) : null}
          {onDelete ? (
            <button
              onClick={stop(onDelete)}
              title="Delete detection"
              className="rounded bg-background/90 p-1 text-destructive"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          ) : null}
        </div>
      ) : null}
    </Link>
  );
}

/** Untag + Delete handlers shared by both tagged galleries. Each fires the
 *  optimistic mutation and shows a 5s sonner toast with an Undo action. */
function useTileActions() {
  const untagMut = useUntagDetection();
  const retagMut = useRetagDetectionGallery();
  const deleteMut = useDeleteDetectionGallery();
  const restoreMut = useRestoreDetectionGallery();

  const untag = useCallback(
    (item: DetectionGalleryItem) => {
      // Button is hidden when there's no sub-class — guard anyway.
      const prevSubclass = item.subclass_id;
      const prevReviewed = item.reviewed;
      if (!prevSubclass) return;
      untagMut.mutate(
        { id: item.id },
        {
          onSuccess: () =>
            toast("Detection untagged", {
              duration: 5000,
              action: {
                label: "Undo",
                onClick: () =>
                  retagMut.mutate({
                    id: item.id,
                    subclass_id: prevSubclass,
                    reviewed: prevReviewed,
                  }),
              },
            }),
          onError: () => toast.error("Could not untag detection"),
        },
      );
    },
    [untagMut, retagMut],
  );

  const remove = useCallback(
    (item: DetectionGalleryItem) => {
      deleteMut.mutate(
        { id: item.id },
        {
          onSuccess: () =>
            toast("Detection deleted", {
              duration: 5000,
              action: {
                label: "Undo",
                onClick: () => restoreMut.mutate({ id: item.id }),
              },
            }),
          onError: () => toast.error("Could not delete detection"),
        },
      );
    },
    [deleteMut, restoreMut],
  );

  return { untag, remove };
}

function GalleryFooter({
  hasNextPage,
  isFetchingNextPage,
  fetchNextPage,
  total,
  unit,
}: {
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  fetchNextPage: () => void;
  total: number;
  unit: string;
}) {
  return (
    <div className="mt-3">
      <InfiniteScrollSentinel
        hasMore={hasNextPage}
        isFetching={isFetchingNextPage}
        onLoadMore={fetchNextPage}
      />
      {isFetchingNextPage ? (
        <div className="flex items-center justify-center gap-2 py-2 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Loading more…
        </div>
      ) : !hasNextPage && total > 0 ? (
        <div className="py-1 text-center text-[11px] text-muted-foreground">
          End of results — {total.toLocaleString()} {unit}
          {total === 1 ? "" : "s"} total
        </div>
      ) : null}
    </div>
  );
}

function SubclassExamplesGallery({ subclass }: { subclass: VdSubclass }) {
  const {
    rows: examples,
    total,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
    isPending,
  } = useSubclassExamples(subclass.id);
  const removeExample = useDeleteExample(subclass.id);
  const loadMore = useCallback(() => void fetchNextPage(), [fetchNextPage]);

  const remove = async (id: string): Promise<void> => {
    try {
      await removeExample.mutateAsync(id);
    } catch {
      toast.error("Could not remove example");
    }
  };

  if (isPending) {
    return <p className="text-sm text-muted-foreground">Loading examples…</p>;
  }
  if (examples.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No examples yet — promote detections with{" "}
        <kbd className="rounded bg-muted px-1 text-xs">S</kbd> in the labeling
        UI.
      </p>
    );
  }
  return (
    <>
      <div className="flex flex-wrap gap-2">
        {examples.map((ex) => (
          <ExampleThumb
            key={ex.id}
            example={ex}
            borderColor={subclass.color_hex}
            onRemove={() => void remove(ex.id)}
          />
        ))}
      </div>
      <GalleryFooter
        hasNextPage={hasNextPage}
        isFetchingNextPage={isFetchingNextPage}
        fetchNextPage={loadMore}
        total={total}
        unit="example"
      />
    </>
  );
}

function ClassExamplesGallery({
  classId,
  subclasses,
}: {
  classId: string;
  subclasses: VdSubclass[];
}) {
  const {
    rows: examples,
    total,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
    isPending,
  } = useClassExamples(classId);
  const loadMore = useCallback(() => void fetchNextPage(), [fetchNextPage]);
  const colorBySubclass = useMemo(
    () => Object.fromEntries(subclasses.map((s) => [s.id, s.color_hex])),
    [subclasses],
  );

  if (isPending) {
    return <p className="text-sm text-muted-foreground">Loading examples…</p>;
  }
  if (examples.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No examples in any sub-class yet — promote detections with{" "}
        <kbd className="rounded bg-muted px-1 text-xs">S</kbd> in the labeling
        UI.
      </p>
    );
  }
  return (
    <>
      <div className="flex flex-wrap gap-2">
        {examples.map((ex) => (
          <ExampleThumb
            key={ex.id}
            example={ex}
            borderColor={colorBySubclass[ex.subclass_id]}
          />
        ))}
      </div>
      <GalleryFooter
        hasNextPage={hasNextPage}
        isFetchingNextPage={isFetchingNextPage}
        fetchNextPage={loadMore}
        total={total}
        unit="example"
      />
    </>
  );
}

function GalleryToolbar({
  include,
  sort,
  onInclude,
  onSort,
  count,
}: {
  include: GalleryInclude;
  sort: GallerySort;
  onInclude: (v: GalleryInclude) => void;
  onSort: (v: GallerySort) => void;
  count: number;
}) {
  const chips: ReadonlyArray<{ value: GalleryInclude; label: string }> = [
    { value: "all", label: "All" },
    { value: "auto", label: "Auto" },
    { value: "reviewed", label: "Reviewed" },
  ];
  return (
    <div className="mb-3 flex flex-wrap items-center gap-3">
      <div className="inline-flex rounded-md border border-input">
        {chips.map((c) => (
          <button
            key={c.value}
            onClick={() => onInclude(c.value)}
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
      <Select
        value={sort}
        onChange={(e) => onSort(e.target.value as GallerySort)}
        className="h-8 text-xs"
      >
        <option value="created_desc">Newest first</option>
        <option value="reviewed_desc">Recently reviewed</option>
      </Select>
      <span className="ml-auto text-xs text-muted-foreground">
        {count} {count === 1 ? "detection" : "detections"}
      </span>
    </div>
  );
}

function SubclassTaggedGallery({ subclass }: { subclass: VdSubclass }) {
  const [include, setInclude] = useState<GalleryInclude>("all");
  const [sort, setSort] = useState<GallerySort>("created_desc");
  const {
    rows: items,
    total,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
    isPending,
  } = useSubclassDetections(subclass.id, { include, sort });
  const loadMore = useCallback(() => void fetchNextPage(), [fetchNextPage]);
  const actions = useTileActions();

  return (
    <div>
      <GalleryToolbar
        include={include}
        sort={sort}
        onInclude={setInclude}
        onSort={setSort}
        count={total}
      />
      {isPending ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No detections match this filter yet.
        </p>
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            {items.map((it) => (
              <TaggedThumb
                key={it.id}
                item={it}
                borderColor={subclass.color_hex}
                onUntag={() => actions.untag(it)}
                onDelete={() => actions.remove(it)}
              />
            ))}
          </div>
          <GalleryFooter
            hasNextPage={hasNextPage}
            isFetchingNextPage={isFetchingNextPage}
            fetchNextPage={loadMore}
            total={total}
            unit="detection"
          />
        </>
      )}
    </div>
  );
}

function ClassTaggedGallery({
  classId,
  subclasses,
}: {
  classId: string;
  subclasses: VdSubclass[];
}) {
  const [include, setInclude] = useState<GalleryInclude>("all");
  const [sort, setSort] = useState<GallerySort>("created_desc");
  const {
    rows: items,
    total,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
    isPending,
  } = useClassDetections(classId, { include, sort });
  const loadMore = useCallback(() => void fetchNextPage(), [fetchNextPage]);
  const colorBySubclass = useMemo(
    () => Object.fromEntries(subclasses.map((s) => [s.id, s.color_hex])),
    [subclasses],
  );
  const actions = useTileActions();

  return (
    <div>
      <GalleryToolbar
        include={include}
        sort={sort}
        onInclude={setInclude}
        onSort={setSort}
        count={total}
      />
      {isPending ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No detections match this filter yet.
        </p>
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            {items.map((it) => (
              <TaggedThumb
                key={it.id}
                item={it}
                borderColor={
                  it.subclass_id ? colorBySubclass[it.subclass_id] : undefined
                }
                onUntag={it.subclass_id ? () => actions.untag(it) : undefined}
                onDelete={() => actions.remove(it)}
              />
            ))}
          </div>
          <GalleryFooter
            hasNextPage={hasNextPage}
            isFetchingNextPage={isFetchingNextPage}
            fetchNextPage={loadMore}
            total={total}
            unit="detection"
          />
        </>
      )}
    </div>
  );
}

function GalleryPanel({
  title,
  subclass,
  classId,
  subclasses,
}: {
  title: string;
  subclass: VdSubclass | null;
  classId: string;
  subclasses: VdSubclass[];
}) {
  const [tab, setTab] = useState<GalleryTab>("examples");
  const tabs: ReadonlyArray<TabItem<GalleryTab>> = [
    {
      value: "examples",
      label: (
        <span className="inline-flex items-center gap-1.5">
          <ImageIcon className="h-3.5 w-3.5" /> Examples
        </span>
      ),
    },
    {
      value: "tagged",
      label: (
        <span className="inline-flex items-center gap-1.5">
          <ListChecks className="h-3.5 w-3.5" /> All tagged
        </span>
      ),
    },
  ];
  return (
    <div>
      <h2 className="mb-2 text-sm font-semibold">{title}</h2>
      <Tabs<GalleryTab>
        value={tab}
        onChange={setTab}
        items={tabs}
        className="mb-3"
      />
      {tab === "examples" ? (
        subclass ? (
          <SubclassExamplesGallery subclass={subclass} />
        ) : (
          <ClassExamplesGallery classId={classId} subclasses={subclasses} />
        )
      ) : subclass ? (
        <SubclassTaggedGallery subclass={subclass} />
      ) : (
        <ClassTaggedGallery classId={classId} subclasses={subclasses} />
      )}
    </div>
  );
}

export function ClassDetail() {
  const { id = "" } = useParams<{ id: string }>();
  const { data: classes = [] } = useClasses();
  const { data: subclasses = [], isPending } = useSubclasses(id);
  const deleteSubclass = useDeleteSubclass();
  const rescan = useRescanSubclasses();
  const startTraining = useStartTraining();

  const cls = classes.find((c) => c.id === id);
  const active = subclasses.filter((s) => s.is_active);

  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<VdSubclass | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = active.find((s) => s.id === selectedId) ?? null;

  const deactivate = async (s: VdSubclass): Promise<void> => {
    if (!window.confirm(`Deactivate sub-class "${s.name}"?`)) return;
    try {
      await deleteSubclass.mutateAsync(s.id);
    } catch {
      toast.error("Could not deactivate sub-class");
    }
  };

  const triggerRescan = async (): Promise<void> => {
    try {
      await rescan.mutateAsync(id);
      toast.success("Re-scan queued — existing clips will be re-embedded");
    } catch {
      toast.error("Could not start re-scan");
    }
  };

  const trainClassifier = async (): Promise<void> => {
    try {
      await startTraining.mutateAsync({
        kind: "classifier",
        target_class_id: id,
      });
      toast.success("Sub-class classifier training queued");
    } catch {
      toast.error("Could not start classifier training");
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumbs={[{ label: "Classes", to: "/classes" }]}
        title={cls?.name ?? "Class"}
        actions={
          <>
            <Button
              variant="outline"
              onClick={() => void trainClassifier()}
              disabled={active.length < 2 || startTraining.isPending}
              title={
                active.length < 2
                  ? "Needs at least 2 sub-classes"
                  : "Train a classifier on the labelled examples"
              }
            >
              <GraduationCap className="h-4 w-4" /> Train classifier
            </Button>
            <Button variant="outline" onClick={() => void triggerRescan()}>
              <RefreshCw className="h-4 w-4" /> Re-scan existing clips
            </Button>
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" /> New sub-class
            </Button>
          </>
        }
      />

      {isPending ? (
        <div className="h-11 animate-pulse rounded bg-muted" />
      ) : (
        <div className="grid gap-4 md:grid-cols-[16rem_1fr]">
          <div className="space-y-0.5">
            <button
              onClick={() => setSelectedId(null)}
              className={cn(
                "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm",
                selectedId === null ? "bg-accent" : "hover:bg-muted",
              )}
            >
              <span
                className="h-3 w-3 shrink-0 rounded-sm border border-border"
                style={{ backgroundColor: cls?.color_hex ?? "#888888" }}
              />
              <span className="truncate font-medium">All sub-classes</span>
            </button>
            {active.map((s) => (
              <div
                key={s.id}
                className={cn(
                  "flex items-center gap-1 rounded px-2 py-1.5",
                  selectedId === s.id ? "bg-accent" : "hover:bg-muted",
                )}
              >
                <button
                  onClick={() => setSelectedId(s.id)}
                  className="flex min-w-0 flex-1 items-center gap-2 text-left"
                >
                  <span
                    className="h-3 w-3 shrink-0 rounded-sm border border-border"
                    style={{ backgroundColor: s.color_hex }}
                  />
                  <span className="truncate text-sm">{s.name}</span>
                </button>
                <Button size="sm" variant="ghost" onClick={() => setEditing(s)}>
                  <Pencil className="h-3.5 w-3.5" />
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => void deactivate(s)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            ))}
            {active.length === 0 ? (
              <p className="px-2 pt-2 text-xs text-muted-foreground">
                No sub-classes yet. Add one, then promote examples in the
                labeling UI.
              </p>
            ) : null}
          </div>
          <GalleryPanel
            key={selected?.id ?? "__class__"}
            title={
              selected ? selected.name : `${cls?.name ?? "Class"} — all sub-classes`
            }
            subclass={selected}
            classId={id}
            subclasses={active}
          />
        </div>
      )}

      <SubclassFormDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        classId={id}
      />
      <SubclassFormDialog
        open={editing !== null}
        onOpenChange={(open) => !open && setEditing(null)}
        classId={id}
        initial={editing ?? undefined}
      />
    </div>
  );
}
