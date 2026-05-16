import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const SHORTCUTS: [string, string][] = [
  ["J / K", "Next / previous frame in queue"],
  ["B", "Toggle draw-box mode"],
  ["1 – 9", "Assign class (or set default)"],
  ["⇧ 1 – 9", "Assign sub-class within the selected class"],
  ["S", "Promote selected detection to a sub-class example"],
  ["X / Delete", "Delete selected detection"],
  ["Enter / Space", "Save — mark frame reviewed"],
  ["Esc", "Deselect / cancel draw"],
  ["Ctrl+Z / Ctrl+Y", "Undo / redo"],
  ["?", "Show this help"],
];

export function KeymapModal({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Keyboard shortcuts</DialogTitle>
        </DialogHeader>
        <div className="space-y-1.5">
          {SHORTCUTS.map(([key, desc]) => (
            <div key={key} className="flex items-center justify-between text-sm">
              <kbd className="rounded bg-muted px-1.5 py-0.5 text-xs font-medium">
                {key}
              </kbd>
              <span className="text-muted-foreground">{desc}</span>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
