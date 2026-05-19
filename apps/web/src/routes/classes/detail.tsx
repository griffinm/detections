import { useState } from "react";
import { useParams } from "react-router-dom";
import { GraduationCap, Pencil, Plus, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { SubclassFormDialog } from "@/components/SubclassFormDialog";
import { cropBackgroundStyle } from "@/lib/cropStyle";
import { cn } from "@/lib/utils";
import { useClasses } from "@/hooks/useClasses";
import { useStartTraining } from "@/hooks/useTraining";
import {
  useDeleteExample,
  useDeleteSubclass,
  useRescanSubclasses,
  useSubclassExamples,
  useSubclasses,
  type SubclassExample,
  type VdSubclass,
} from "@/hooks/useSubclasses";

/** A detection crop, CSS-cropped from the full frame JPEG via its bbox. */
function ExampleThumb({
  example,
  onRemove,
}: {
  example: SubclassExample;
  onRemove: () => void;
}) {
  return (
    <div className="group relative">
      <div
        className="h-24 w-24 rounded border border-border bg-muted bg-no-repeat"
        style={cropBackgroundStyle(example.bbox, example.image_url)}
      />
      <button
        onClick={onRemove}
        title="Remove example"
        className="absolute right-1 top-1 hidden rounded bg-background/90 p-1 text-destructive group-hover:block"
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

function ExamplesGallery({ subclass }: { subclass: VdSubclass }) {
  const { data: examples = [], isPending } = useSubclassExamples(subclass.id);
  const removeExample = useDeleteExample(subclass.id);

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
    <div className="flex flex-wrap gap-2">
      {examples.map((ex) => (
        <ExampleThumb
          key={ex.id}
          example={ex}
          onRemove={() => void remove(ex.id)}
        />
      ))}
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
      ) : active.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No sub-classes yet. Add one, then label and promote example crops so
          the model can auto-assign it.
        </p>
      ) : (
        <div className="grid gap-4 md:grid-cols-[16rem_1fr]">
          <div className="space-y-0.5">
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
          </div>
          <div>
            {selected ? (
              <>
                <h2 className="mb-2 text-sm font-semibold">
                  {selected.name} — examples
                </h2>
                <ExamplesGallery subclass={selected} />
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                Select a sub-class to see its example crops.
              </p>
            )}
          </div>
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
