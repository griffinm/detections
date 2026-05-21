import { useState } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ClassFormDialog } from "@/components/ClassFormDialog";
import { SubclassFormDialog } from "@/components/SubclassFormDialog";
import { cn } from "@/lib/utils";
import { useLabelingStore } from "@/stores/labeling";
import type { useDetectionActions } from "@/hooks/useDetections";
import type { VdClass } from "@/hooks/useClasses";
import type { VdSubclass } from "@/hooks/useSubclasses";
import type { FrameDetail } from "@/hooks/useFrame";

export function ClassPicker({
  classes,
  subclasses,
  frame,
  actions,
}: {
  classes: VdClass[];
  subclasses: VdSubclass[];
  frame: FrameDetail;
  actions: ReturnType<typeof useDetectionActions>;
}) {
  const selectedId = useLabelingStore((s) => s.selectedId);
  const defaultClassId = useLabelingStore((s) => s.defaultClassId);
  const setDefaultClass = useLabelingStore((s) => s.setDefaultClass);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [subclassDialogClassId, setSubclassDialogClassId] = useState<
    string | null
  >(null);

  const active = classes.filter((c) => c.is_active);
  const selectedDet = selectedId
    ? frame.detections.find((d) => d.id === selectedId)
    : undefined;

  const pickClass = (classId: string): void => {
    if (selectedId) {
      // Clicking the active class clears it (and the sub-class, since
      // a sub-class without its class is meaningless). Picking a *different*
      // class reassigns; the existing PATCH handler audits the change.
      const isActive = selectedDet?.class_id === classId;
      void actions.update(
        selectedId,
        isActive ? { class_id: null, subclass_id: null } : { class_id: classId },
      );
    } else {
      setDefaultClass(classId);
    }
  };

  const pickSubclass = (subclassId: string): void => {
    if (!selectedId) return;
    const isActive = selectedDet?.subclass_id === subclassId;
    void actions.update(
      selectedId,
      { subclass_id: isActive ? null : subclassId },
    );
  };

  return (
    <div className="space-y-0.5">
      {active.map((c, i) => {
        const showSubs = selectedDet?.class_id === c.id;
        const subs = showSubs
          ? subclasses.filter((s) => s.is_active && s.class_id === c.id)
          : [];
        return (
          <div key={c.id}>
            <button
              onClick={() => pickClass(c.id)}
              className={cn(
                "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left hover:bg-muted",
                selectedDet?.class_id === c.id && "bg-accent",
                !selectedId && defaultClassId === c.id && "ring-1 ring-ring",
              )}
            >
              <span
                className="h-3 w-3 shrink-0 rounded-sm border border-border"
                style={{ backgroundColor: c.color_hex }}
              />
              <span className="min-w-0 flex-1 truncate text-sm">{c.name}</span>
              {i < 9 && (
                <kbd className="rounded bg-muted px-1 text-[10px] text-muted-foreground">
                  {i + 1}
                </kbd>
              )}
            </button>

            {showSubs && (
              <div className="ml-3 border-l border-border pl-2">
                {subs.map((s, j) => (
                  <button
                    key={s.id}
                    onClick={() => pickSubclass(s.id)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded px-2 py-1 text-left hover:bg-muted",
                      selectedDet?.subclass_id === s.id && "ring-1 ring-ring",
                    )}
                  >
                    <span
                      className="h-2.5 w-2.5 shrink-0 rounded-sm border border-border"
                      style={{ backgroundColor: s.color_hex }}
                    />
                    <span className="min-w-0 flex-1 truncate text-xs">
                      {s.name}
                    </span>
                    {j < 9 && (
                      <kbd className="rounded bg-muted px-1 text-[10px] text-muted-foreground">
                        ⇧{j + 1}
                      </kbd>
                    )}
                  </button>
                ))}
                {subs.length === 0 && (
                  <p className="py-1 pl-1 text-[11px] text-muted-foreground">
                    No sub-classes yet.
                  </p>
                )}
                <button
                  onClick={() => setSubclassDialogClassId(c.id)}
                  className="flex w-full items-center gap-1 rounded px-2 py-1 text-left text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground"
                >
                  <Plus className="h-3 w-3" /> New sub-class
                </button>
              </div>
            )}
          </div>
        );
      })}

      <Button
        variant="outline"
        size="sm"
        className="mt-2 w-full"
        onClick={() => setDialogOpen(true)}
      >
        <Plus className="h-3.5 w-3.5" /> New class
      </Button>
      <ClassFormDialog open={dialogOpen} onOpenChange={setDialogOpen} />
      {subclassDialogClassId && (
        <SubclassFormDialog
          open
          onOpenChange={(o) => {
            if (!o) setSubclassDialogClassId(null);
          }}
          classId={subclassDialogClassId}
        />
      )}
    </div>
  );
}
