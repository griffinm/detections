import { useState } from "react";
import { Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { useDeleteFrame } from "@/hooks/useFrames";

interface Props {
  frameId: string;
  clipId: string;
  frameIndex: number;
  /** `icon` for a compact overlay button, `button` for a labelled one. */
  variant?: "icon" | "button";
  className?: string;
  /** Called after a successful delete (e.g. to navigate away). */
  onDeleted?: () => void;
}

/** Stop a click from reaching an enclosing <Link> or row handler. */
function swallow(e: React.MouseEvent): void {
  e.preventDefault();
  e.stopPropagation();
}

export function DeleteFrameButton({
  frameId,
  clipId,
  frameIndex,
  variant = "button",
  className,
  onDeleted,
}: Props) {
  const del = useDeleteFrame();
  const [open, setOpen] = useState(false);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {variant === "icon" ? (
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Delete frame ${frameIndex}`}
            className={className}
            onClick={swallow}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        ) : (
          <Button
            variant="destructive"
            size="sm"
            className={className}
            onClick={swallow}
          >
            <Trash2 className="h-4 w-4" /> Delete frame
          </Button>
        )}
      </DialogTrigger>
      <DialogContent onClick={(e) => e.stopPropagation()}>
        <DialogHeader>
          <DialogTitle>Delete frame?</DialogTitle>
          <DialogDescription>
            Frame {frameIndex}, its detections, and its image will be
            permanently removed. This cannot be undone.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            disabled={del.isPending}
            onClick={() =>
              del.mutate(
                { id: frameId, clipId },
                {
                  onSuccess: () => {
                    toast.success("Frame deleted");
                    setOpen(false);
                    onDeleted?.();
                  },
                  onError: () => toast.error("Failed to delete frame"),
                },
              )
            }
          >
            Delete
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
