import { useEffect } from "react";
import { useLabelingStore } from "@/stores/labeling";
import type { useDetectionActions } from "@/hooks/useDetections";
import type { VdClass } from "@/hooks/useClasses";
import type { VdSubclass } from "@/hooks/useSubclasses";

interface Options {
  actions: ReturnType<typeof useDetectionActions>;
  classes: VdClass[];
  subclasses: VdSubclass[];
  onPrev: () => void;
  onNext: () => void;
  onToggleKeymap: () => void;
}

/** Window-level labeling shortcuts, active while the labeling page is mounted. */
export function useLabelingHotkeys({
  actions,
  classes,
  subclasses,
  onPrev,
  onNext,
  onToggleKeymap,
}: Options): void {
  useEffect(() => {
    function handler(e: KeyboardEvent): void {
      const target = e.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable)
      ) {
        return;
      }

      const store = useLabelingStore.getState();
      const selected = store.selectedId;
      const lower = e.key.toLowerCase();

      if ((e.ctrlKey || e.metaKey) && lower === "z") {
        e.preventDefault();
        void actions.undo();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && lower === "y") {
        e.preventDefault();
        void actions.redo();
        return;
      }
      if (e.ctrlKey || e.metaKey) return;

      // Digit row, layout-independent. Shift+N assigns a sub-class within the
      // selected detection's class; plain N assigns a top-level class.
      const digit = /^Digit([1-9])$/.exec(e.code);
      if (digit) {
        const idx = Number(digit[1]) - 1;
        if (e.shiftKey) {
          if (!selected) return;
          const det = actions.get(selected);
          if (!det?.class_id) return;
          const sub = subclasses.filter(
            (s) => s.is_active && s.class_id === det.class_id,
          )[idx];
          if (sub) void actions.update(selected, { subclass_id: sub.id });
          return;
        }
        const cls = classes.filter((c) => c.is_active)[idx];
        if (cls) {
          if (selected) void actions.update(selected, { class_id: cls.id });
          else store.setDefaultClass(cls.id);
        }
        return;
      }

      switch (lower) {
        case "b":
          store.setMode(store.mode === "drawing" ? "idle" : "drawing");
          break;
        case "s":
          if (selected) void actions.promote(selected);
          break;
        case "x":
        case "delete":
        case "backspace":
          if (selected) {
            void actions.remove(selected);
            store.select(null);
          }
          break;
        case "j":
          onNext();
          break;
        case "k":
          onPrev();
          break;
        case "enter":
        case " ":
          e.preventDefault();
          void actions.reviewFrame();
          break;
        case "escape":
          store.setMode("idle");
          store.select(null);
          break;
        case "?":
          onToggleKeymap();
          break;
      }
    }

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [actions, classes, subclasses, onPrev, onNext, onToggleKeymap]);
}
