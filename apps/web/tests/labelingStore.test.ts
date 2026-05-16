import { beforeEach, describe, expect, it } from "vitest";
import { useLabelingStore, type EditEntry } from "@/stores/labeling";

const entry = (id: string): EditEntry => ({ op: "create", id });
const ids = (stack: EditEntry[]): string[] => stack.map((e) => e.id);

describe("labeling undo/redo history", () => {
  beforeEach(() => {
    useLabelingStore.getState().resetFrame();
  });

  it("pushEdit appends to undo and clears redo", () => {
    useLabelingStore.getState().pushEdit(entry("a"));
    useLabelingStore.setState({ redoStack: [entry("stale")] });
    useLabelingStore.getState().pushEdit(entry("b"));

    const state = useLabelingStore.getState();
    expect(ids(state.undoStack)).toEqual(["a", "b"]);
    expect(state.redoStack).toEqual([]);
  });

  it("popUndo moves the newest entry onto the redo stack", () => {
    useLabelingStore.getState().pushEdit(entry("a"));
    useLabelingStore.getState().pushEdit(entry("b"));

    const popped = useLabelingStore.getState().popUndo();
    expect(popped?.id).toBe("b");

    const state = useLabelingStore.getState();
    expect(ids(state.undoStack)).toEqual(["a"]);
    expect(ids(state.redoStack)).toEqual(["b"]);
  });

  it("popRedo moves the entry back onto the undo stack", () => {
    useLabelingStore.getState().pushEdit(entry("a"));
    useLabelingStore.getState().popUndo();

    const redone = useLabelingStore.getState().popRedo();
    expect(redone?.id).toBe("a");

    const state = useLabelingStore.getState();
    expect(ids(state.undoStack)).toEqual(["a"]);
    expect(state.redoStack).toEqual([]);
  });

  it("resetFrame clears history and selection", () => {
    useLabelingStore.getState().pushEdit(entry("a"));
    useLabelingStore.getState().select("x");
    useLabelingStore.getState().resetFrame();

    const state = useLabelingStore.getState();
    expect(state.undoStack).toEqual([]);
    expect(state.redoStack).toEqual([]);
    expect(state.selectedId).toBeNull();
  });
});
