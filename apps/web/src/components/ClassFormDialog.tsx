import { useEffect, useState } from "react";
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
import { useCreateClass, useUpdateClass, type VdClass } from "@/hooks/useClasses";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** When set, the dialog edits this class instead of creating one. */
  initial?: VdClass;
}

export function ClassFormDialog({ open, onOpenChange, initial }: Props) {
  const create = useCreateClass();
  const update = useUpdateClass();
  const [name, setName] = useState("");
  const [color, setColor] = useState("#22c55e");

  useEffect(() => {
    if (open) {
      setName(initial?.name ?? "");
      setColor(initial?.color_hex ?? "#22c55e");
    }
  }, [open, initial]);

  async function submit(): Promise<void> {
    try {
      if (initial) {
        await update.mutateAsync({ id: initial.id, name, color_hex: color });
      } else {
        await create.mutateAsync({ name, color_hex: color });
      }
      onOpenChange(false);
    } catch {
      toast.error("Could not save class");
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{initial ? "Edit class" : "New class"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="cls-name">Name</Label>
            <Input
              id="cls-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
            />
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
