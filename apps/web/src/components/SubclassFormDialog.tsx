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
import {
  useCreateSubclass,
  useUpdateSubclass,
  type VdSubclass,
} from "@/hooks/useSubclasses";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  classId: string;
  /** When set, the dialog edits this sub-class instead of creating one. */
  initial?: VdSubclass;
}

export function SubclassFormDialog({
  open,
  onOpenChange,
  classId,
  initial,
}: Props) {
  const create = useCreateSubclass(classId);
  const update = useUpdateSubclass();
  const [name, setName] = useState("");
  const [color, setColor] = useState("#3b82f6");

  useEffect(() => {
    if (open) {
      setName(initial?.name ?? "");
      setColor(initial?.color_hex ?? "#3b82f6");
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
      toast.error("Could not save sub-class");
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{initial ? "Edit sub-class" : "New sub-class"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="sub-name">Name</Label>
            <Input
              id="sub-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sub-color">Color</Label>
            <input
              id="sub-color"
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
