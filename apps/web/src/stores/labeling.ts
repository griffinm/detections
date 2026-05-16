import { create } from "zustand";
import type { Bbox } from "@/hooks/useFrame";

/** The fields an `update` edit can change — enough to PATCH in either direction. */
export interface DetectionPatch {
  bbox?: Bbox;
  class_id?: string | null;
  subclass_id?: string | null;
}

/** One reversible edit. `create`/`delete` rely on stable ids (soft-delete). */
export type EditEntry =
  | { op: "update"; id: string; prev: DetectionPatch; next: DetectionPatch }
  | { op: "create"; id: string }
  | { op: "delete"; id: string };

const HISTORY_LIMIT = 50;

interface LabelingState {
  selectedId: string | null;
  mode: "idle" | "drawing";
  defaultClassId: string | null;
  queueIds: string[];
  /** The frame currently open in the labeling UI — SSE skips invalidating it. */
  activeFrameId: string | null;
  undoStack: EditEntry[];
  redoStack: EditEntry[];

  select: (id: string | null) => void;
  setMode: (mode: "idle" | "drawing") => void;
  setDefaultClass: (id: string) => void;
  setQueue: (ids: string[]) => void;
  setActiveFrame: (id: string | null) => void;
  pushEdit: (entry: EditEntry) => void;
  peekUndo: () => EditEntry | undefined;
  peekRedo: () => EditEntry | undefined;
  commitUndo: () => void;
  commitRedo: () => void;
  resetFrame: () => void;
}

export const useLabelingStore = create<LabelingState>((set, get) => ({
  selectedId: null,
  mode: "idle",
  defaultClassId: null,
  queueIds: [],
  activeFrameId: null,
  undoStack: [],
  redoStack: [],

  select: (selectedId) => set({ selectedId }),
  setMode: (mode) => set({ mode }),
  setDefaultClass: (defaultClassId) => set({ defaultClassId }),
  setQueue: (queueIds) => set({ queueIds }),
  setActiveFrame: (activeFrameId) => set({ activeFrameId }),

  // A fresh edit invalidates the redo branch.
  pushEdit: (entry) =>
    set((s) => ({
      undoStack: [...s.undoStack, entry].slice(-HISTORY_LIMIT),
      redoStack: [],
    })),

  // peek* read the entry without mutating; the caller invokes commit* only
  // once the inverse API request succeeds, so a failed undo/redo leaves the
  // stacks untouched and re-runnable.
  peekUndo: () => {
    const { undoStack } = get();
    return undoStack[undoStack.length - 1];
  },

  peekRedo: () => {
    const { redoStack } = get();
    return redoStack[redoStack.length - 1];
  },

  commitUndo: () => {
    const { undoStack, redoStack } = get();
    const entry = undoStack[undoStack.length - 1];
    if (entry) {
      set({ undoStack: undoStack.slice(0, -1), redoStack: [...redoStack, entry] });
    }
  },

  commitRedo: () => {
    const { undoStack, redoStack } = get();
    const entry = redoStack[redoStack.length - 1];
    if (entry) {
      set({ redoStack: redoStack.slice(0, -1), undoStack: [...undoStack, entry] });
    }
  },

  resetFrame: () =>
    set({ selectedId: null, mode: "idle", undoStack: [], redoStack: [] }),
}));
