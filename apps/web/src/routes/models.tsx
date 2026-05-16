import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useActivateModel, useModels, type ModelVersion } from "@/hooks/useModels";

/** A one-line headline metric for the table — mAP for YOLO, accuracy for a classifier. */
function metricSummary(model: ModelVersion): string {
  const metrics = model.metrics ?? {};
  const map = metrics.val_map50_95;
  const acc = metrics.val_accuracy;
  if (model.kind === "yolo" && typeof map === "number") {
    return `mAP50-95 ${map.toFixed(3)}`;
  }
  if (model.kind === "classifier" && typeof acc === "number") {
    return `acc ${(acc * 100).toFixed(1)}%`;
  }
  return typeof metrics.source === "string" ? metrics.source : "—";
}

export function ModelsPage() {
  const { data: models = [], isPending } = useModels();
  const activate = useActivateModel();

  const onActivate = async (model: ModelVersion): Promise<void> => {
    try {
      await activate.mutateAsync(model.id);
      toast.success(`Activated ${model.name}`);
    } catch {
      toast.error("Could not activate model");
    }
  };

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold tracking-tight">Models</h1>
      <p className="text-sm text-muted-foreground">
        YOLO detectors and sub-class classifiers. One version per kind is active.
      </p>

      {isPending ? (
        <div className="space-y-1.5">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-11 animate-pulse rounded bg-muted" />
          ))}
        </div>
      ) : models.length === 0 ? (
        <p className="text-sm text-muted-foreground">No model versions yet.</p>
      ) : (
        <div className="overflow-hidden rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left text-xs uppercase text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Name</th>
                <th className="px-3 py-2 font-medium">Kind</th>
                <th className="px-3 py-2 font-medium">Metrics</th>
                <th className="px-3 py-2 font-medium">Trained on</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {models.map((model) => (
                <tr key={model.id} className="border-t border-border">
                  <td className="px-3 py-2">{model.name}</td>
                  <td className="px-3 py-2 text-muted-foreground">{model.kind}</td>
                  <td className="px-3 py-2 tabular-nums">{metricSummary(model)}</td>
                  <td className="px-3 py-2 tabular-nums text-muted-foreground">
                    {model.trained_on ?? "—"}
                  </td>
                  <td className="px-3 py-2">
                    {model.is_active ? (
                      <span className="text-green-600">active</span>
                    ) : (
                      <span className="text-muted-foreground">inactive</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {!model.is_active && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => void onActivate(model)}
                      >
                        Activate
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
