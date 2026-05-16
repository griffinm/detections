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
  undoStack: EditEntry[];
  redoStack: EditEntry[];

  select: (id: string | null) => void;
  setMode: (mode: "idle" | "drawing") => void;
  setDefaultClass: (id: string) => void;
  setQueue: (ids: string[]) => void;
  pushEdit: (entry: EditEntry) => void;
  popUndo: () => EditEntry | undefined;
  popRedo: () => EditEntry | undefined;
  resetFrame: () => void;
}

export const useLabelingStore = create<LabelingState>((set, get) => ({
  selectedId: null,
  mode: "idle",
  defaultClassId: null,
  queueIds: [],
  undoStack: [],
  redoStack: [],

  select: (selectedId) => set({ selectedId }),
  setMode: (mode) => set({ mode }),
  setDefaultClass: (defaultClassId) => set({ defaultClassId }),
  setQueue: (queueIds) => set({ queueIds }),

  // A fresh edit invalidates the redo branch.
  pushEdit: (entry) =>
    set((s) => ({
      undoStack: [...s.undoStack, entry].slice(-HISTORY_LIMIT),
      redoStack: [],
    })),

  popUndo: () => {
    const { undoStack, redoStack } = get();
    const entry = undoStack[undoStack.length - 1];
    if (entry) {
      set({ undoStack: undoStack.slice(0, -1), redoStack: [...redoStack, entry] });
    }
    return entry;
  },

  popRedo: () => {
    const { undoStack, redoStack } = get();
    const entry = redoStack[redoStack.length - 1];
    if (entry) {
      set({ redoStack: redoStack.slice(0, -1), undoStack: [...undoStack, entry] });
    }
    return entry;
  },

  resetFrame: () =>
    set({ selectedId: null, mode: "idle", undoStack: [], redoStack: [] }),
}));
