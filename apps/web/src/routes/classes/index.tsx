import { useState } from "react";
import { Link } from "react-router-dom";
import { Pencil, Plus } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { ClassFormDialog } from "@/components/ClassFormDialog";
import { useClasses, useDeleteClass, type VdClass } from "@/hooks/useClasses";

export function ClassesList() {
  const { data: classes = [], isPending } = useClasses();
  const deleteClass = useDeleteClass();
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<VdClass | null>(null);

  const deactivate = async (cls: VdClass): Promise<void> => {
    if (!window.confirm(`Deactivate "${cls.name}"?`)) return;
    try {
      await deleteClass.mutateAsync(cls.id);
    } catch {
      toast.error("Could not deactivate class");
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Classes"
        actions={
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" /> New class
          </Button>
        }
      />

      {isPending ? (
        <div className="space-y-1.5">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-11 animate-pulse rounded bg-muted" />
          ))}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full min-w-[480px] text-sm">
            <thead className="bg-muted/50 text-left text-xs uppercase text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Class</th>
                <th className="px-3 py-2 font-medium">Source</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {classes.map((cls) => (
                <tr key={cls.id} className="border-t border-border">
                  <td className="px-3 py-2">
                    <Link
                      to={`/classes/${cls.id}`}
                      className="flex items-center gap-2 hover:underline"
                    >
                      <span
                        className="h-3.5 w-3.5 rounded-sm border border-border"
                        style={{ backgroundColor: cls.color_hex }}
                      />
                      {cls.name}
                    </Link>
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">
                    {cls.source}
                  </td>
                  <td className="px-3 py-2">
                    {cls.is_active ? (
                      <span className="text-green-600">active</span>
                    ) : (
                      <span className="text-muted-foreground">inactive</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex justify-end gap-1">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setEditing(cls)}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      {cls.is_active && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => void deactivate(cls)}
                        >
                          Deactivate
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ClassFormDialog open={createOpen} onOpenChange={setCreateOpen} />
      <ClassFormDialog
        open={editing !== null}
        onOpenChange={(open) => !open && setEditing(null)}
        initial={editing ?? undefined}
      />
    </div>
  );
}
