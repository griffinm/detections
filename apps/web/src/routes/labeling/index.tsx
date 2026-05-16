import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useClasses } from "@/hooks/useClasses";
import { useLabelingQueue } from "@/hooks/useLabelingQueue";
import { useLabelingStore } from "@/stores/labeling";

const SELECT_CLASS =
  "rounded-md border border-input bg-background px-2 py-1 text-sm";

export function LabelingQueue() {
  const navigate = useNavigate();
  const [strategy, setStrategy] = useState("lowconf");
  const [classId, setClassId] = useState("");
  const { data: classes = [] } = useClasses();
  const { data: items = [], isPending } = useLabelingQueue(
    strategy,
    classId || undefined,
  );
  const setQueue = useLabelingStore((s) => s.setQueue);

  const startAt = (index: number): void => {
    setQueue(items.map((i) => i.frame_id));
    navigate(`/labeling/${items[index].frame_id}`);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold tracking-tight">Labeling Queue</h1>
        <select
          className={SELECT_CLASS}
          value={strategy}
          onChange={(e) => setStrategy(e.target.value)}
        >
          <option value="lowconf">Lowest confidence</option>
          <option value="unreviewed">Newest first</option>
        </select>
        <select
          className={SELECT_CLASS}
          value={classId}
          onChange={(e) => setClassId(e.target.value)}
        >
          <option value="">All classes</option>
          {classes
            .filter((c) => c.is_active)
            .map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
        </select>
        <Button
          className="ml-auto"
          disabled={items.length === 0}
          onClick={() => startAt(0)}
        >
          Start reviewing
        </Button>
      </div>

      {isPending ? (
        <div className="space-y-1.5">
          {[...Array(8)].map((_, i) => (
            <div key={i} className="h-14 animate-pulse rounded bg-muted" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {classId
            ? "No frames to review for this class."
            : "Nothing to review — every detection has been confirmed."}
        </p>
      ) : (
        <div className="space-y-1">
          {items.map((item, index) => (
            <button
              key={item.frame_id}
              onClick={() => startAt(index)}
              className="flex w-full items-center gap-3 rounded-lg border border-border p-2 text-left hover:bg-muted"
            >
              <div className="h-12 w-20 shrink-0 overflow-hidden rounded bg-muted">
                {item.image_url && (
                  <img
                    src={item.image_url}
                    alt=""
                    loading="lazy"
                    className="h-full w-full object-cover"
                  />
                )}
              </div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium">
                  {item.clip_filename}
                </div>
                <div className="text-xs text-muted-foreground">
                  frame {item.frame_index}
                </div>
              </div>
              <span className="rounded-md bg-yellow-100 px-2 py-0.5 text-xs font-medium text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200">
                {item.unreviewed_count} to review
              </span>
              {item.min_confidence != null && (
                <span className="w-12 text-right text-xs tabular-nums text-muted-foreground">
                  {Math.round(item.min_confidence * 100)}%
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
