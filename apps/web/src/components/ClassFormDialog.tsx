import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  useClassCatalog,
  useCreateClass,
  useUpdateClass,
  type ClassCatalogEntry,
  type VdClass,
} from "@/hooks/useClasses";
import { cn } from "@/lib/utils";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** When set, the dialog edits this class instead of creating one. */
  initial?: VdClass;
}

const MAX_SUGGESTIONS = 8;

export function ClassFormDialog({ open, onOpenChange, initial }: Props) {
  const isEdit = initial != null;
  const create = useCreateClass();
  const update = useUpdateClass();
  const catalog = useClassCatalog(open && !isEdit);

  const [name, setName] = useState("");
  const [color, setColor] = useState("#22c55e");
  const [yoloIndex, setYoloIndex] = useState<number | null>(null);
  const [listOpen, setListOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setName(initial?.name ?? "");
      setColor(initial?.color_hex ?? "#22c55e");
      setYoloIndex(initial?.yolo_class_index ?? null);
      setListOpen(false);
      setHighlight(0);
    }
  }, [open, initial]);

  const suggestions: ClassCatalogEntry[] = useMemo(() => {
    if (isEdit) return [];
    const entries = catalog.data ?? [];
    const q = name.trim().toLowerCase();
    const matches = q
      ? entries.filter((e) => e.name.toLowerCase().includes(q))
      : entries;
    return matches.slice(0, MAX_SUGGESTIONS);
  }, [catalog.data, name, isEdit]);

  const exactCatalogMatch = useMemo(
    () =>
      (catalog.data ?? []).find(
        (e) => e.name.toLowerCase() === name.trim().toLowerCase(),
      ),
    [catalog.data, name],
  );

  function pickCatalog(entry: ClassCatalogEntry): void {
    if (entry.in_use) return;
    setName(entry.name);
    setYoloIndex(entry.yolo_class_index);
    setListOpen(false);
    inputRef.current?.focus();
  }

  function pickCustom(): void {
    setYoloIndex(null);
    setListOpen(false);
    inputRef.current?.focus();
  }

  function onNameChange(next: string): void {
    setName(next);
    setHighlight(0);
    setListOpen(true);
    // If the user edits away from a previously-picked catalog name, drop the
    // index — unless the new text exactly matches another catalog entry.
    if (yoloIndex !== null) {
      const trimmed = next.trim().toLowerCase();
      const match = (catalog.data ?? []).find(
        (e) => e.name.toLowerCase() === trimmed && !e.in_use,
      );
      setYoloIndex(match ? match.yolo_class_index : null);
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>): void {
    if (isEdit) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setListOpen(true);
      setHighlight((h) => Math.min(h + 1, suggestions.length));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === "Enter" && listOpen) {
      // Highlight `suggestions.length` = the "custom name" row.
      if (highlight < suggestions.length) {
        e.preventDefault();
        pickCatalog(suggestions[highlight]);
      } else if (highlight === suggestions.length && name.trim()) {
        e.preventDefault();
        pickCustom();
      }
    } else if (e.key === "Escape" && listOpen) {
      e.preventDefault();
      setListOpen(false);
    }
  }

  async function submit(): Promise<void> {
    try {
      if (initial) {
        await update.mutateAsync({ id: initial.id, name, color_hex: color });
      } else {
        await create.mutateAsync({
          name,
          color_hex: color,
          yolo_class_index: yoloIndex,
        });
      }
      onOpenChange(false);
    } catch {
      toast.error("Could not save class");
    }
  }

  const showCustomRow =
    !isEdit && name.trim() !== "" && exactCatalogMatch == null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{initial ? "Edit class" : "New class"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="cls-name">Name</Label>
            <div className="relative">
              <Input
                id="cls-name"
                ref={inputRef}
                value={name}
                onChange={(e) => onNameChange(e.target.value)}
                onFocus={() => !isEdit && setListOpen(true)}
                onBlur={() =>
                  // Defer so click on a suggestion row fires before close.
                  setTimeout(() => setListOpen(false), 120)
                }
                onKeyDown={onKeyDown}
                autoFocus
                autoComplete="off"
              />
              {!isEdit && listOpen && (suggestions.length > 0 || showCustomRow) && (
                <ul
                  role="listbox"
                  className="absolute z-50 mt-1 max-h-64 w-full overflow-auto rounded-md border border-input bg-popover py-1 text-sm shadow-md"
                >
                  {suggestions.map((entry, i) => (
                    <li
                      key={entry.name}
                      role="option"
                      aria-selected={highlight === i}
                      aria-disabled={entry.in_use}
                      className={cn(
                        "flex cursor-pointer items-center justify-between px-3 py-1.5",
                        highlight === i && "bg-accent",
                        entry.in_use && "cursor-not-allowed opacity-50",
                      )}
                      onMouseEnter={() => setHighlight(i)}
                      onMouseDown={(e) => {
                        e.preventDefault();
                        pickCatalog(entry);
                      }}
                    >
                      <span>{entry.name}</span>
                      <span className="text-xs text-muted-foreground">
                        {entry.in_use
                          ? "(already added)"
                          : `YOLO #${entry.yolo_class_index}`}
                      </span>
                    </li>
                  ))}
                  {showCustomRow && (
                    <>
                      {suggestions.length > 0 && (
                        <li
                          aria-hidden
                          className="my-1 border-t border-input"
                        />
                      )}
                      <li
                        role="option"
                        aria-selected={highlight === suggestions.length}
                        className={cn(
                          "cursor-pointer px-3 py-1.5",
                          highlight === suggestions.length && "bg-accent",
                        )}
                        onMouseEnter={() => setHighlight(suggestions.length)}
                        onMouseDown={(e) => {
                          e.preventDefault();
                          pickCustom();
                        }}
                      >
                        Use &ldquo;{name.trim()}&rdquo; as custom name
                      </li>
                    </>
                  )}
                </ul>
              )}
            </div>
            {!isEdit && yoloIndex !== null && (
              <p className="text-xs text-muted-foreground">
                YOLO class #{yoloIndex} — detections of this class will land
                here without re-activating a model.
              </p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cls-color">Color</Label>
            <input
              id="cls-color"
              type="color"
              value={color}
              onChange={(e) => setColor(e.target.value)}
              className="h-9 w-16 cursor-pointer rounded border border-input bg-background"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={() => void submit()} disabled={!name.trim()}>
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
