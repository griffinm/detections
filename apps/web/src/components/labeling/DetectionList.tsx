import { Check } from "lucide-react";
import { ClassBadge } from "@/components/domain/ClassBadge";
import { cn } from "@/lib/utils";
import { useLabelingStore } from "@/stores/labeling";
import type { VdClass } from "@/hooks/useClasses";
import type { VdSubclass } from "@/hooks/useSubclasses";
import type { FrameDetail } from "@/hooks/useFrame";

export function DetectionList({
  frame,
  classes,
  subclasses,
}: {
  frame: FrameDetail;
  classes: VdClass[];
  subclasses: VdSubclass[];
}) {
  const selectedId = useLabelingStore((s) => s.selectedId);
  const select = useLabelingStore((s) => s.select);

  if (frame.detections.length === 0) {
    return <p className="text-sm text-muted-foreground">No detections.</p>;
  }

  return (
    <div className="space-y-0.5">
      {frame.detections.map((d) => {
        const cls = classes.find((c) => c.id === d.class_id);
        const sub = subclasses.find((s) => s.id === d.subclass_id);
        return (
          <button
            key={d.id}
            onClick={() => select(d.id)}
            className={cn(
              "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left",
              selectedId === d.id ? "bg-accent" : "hover:bg-muted",
            )}
          >
            <span className="flex min-w-0 flex-1 flex-col">
              <ClassBadge
                name={cls?.name ?? "unknown"}
                color={cls?.color_hex ?? "#888888"}
              />
              {sub && (
                <span className="ml-[18px] truncate text-xs text-muted-foreground">
                  {sub.name}
                  {d.confidence_subclass != null &&
                    ` · ${Math.round(d.confidence_subclass * 100)}%`}
                </span>
              )}
            </span>
            {d.confidence_class != null && (
              <span className="text-xs tabular-nums text-muted-foreground">
                {Math.round(d.confidence_class * 100)}%
              </span>
            )}
            {d.reviewed && <Check className="h-3.5 w-3.5 shrink-0 text-green-600" />}
          </button>
        );
      })}
    </div>
  );
}
