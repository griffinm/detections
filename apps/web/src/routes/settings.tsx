import { type ReactNode, useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  type SettingItem,
  useResetSetting,
  useSettings,
  useUpdateSetting,
} from "@/hooks/useSettings";

const SECTIONS: { title: string; keys: string[] }[] = [
  {
    title: "Processing",
    keys: [
      "frame_fps",
      "detection_min_confidence",
      "subclass_min_confidence",
      "frame_jpeg_quality",
      "detect_batch_size",
    ],
  },
  {
    title: "Training",
    keys: [
      "custom_class_finetune_threshold",
      "subclass_retrain_threshold",
      "yolo_finetune_epochs",
      "yolo_finetune_imgsz",
    ],
  },
  {
    title: "Retention",
    keys: ["delete_processed_videos", "delete_frames_without_objects"],
  },
];

const DESCRIPTIONS: Record<string, string> = {
  frame_fps: "Frames sampled per second of video.",
  detection_min_confidence: "YOLO score below which a box is dropped.",
  subclass_min_confidence: "kNN / classifier confidence to assign a sub-class.",
  frame_jpeg_quality: "Extracted-frame JPEG quality (0–100).",
  detect_batch_size: "Frames per GPU detection batch.",
  custom_class_finetune_threshold: "New labels that trigger a YOLO fine-tune.",
  subclass_retrain_threshold: "New labels that trigger a classifier retrain.",
  yolo_finetune_epochs: "Epochs per fine-tune run.",
  yolo_finetune_imgsz: "Training image size (px).",
  delete_processed_videos: "Delete the source video when a clip is removed.",
  delete_frames_without_objects: "Prune frame JPEGs that have no detections.",
};

function humanize(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function RowShell({
  item,
  children,
}: {
  item: SettingItem;
  children: ReactNode;
}) {
  const reset = useResetSetting();
  const overridden = item.value !== item.default;
  return (
    <tr className="border-b border-border last:border-0">
      <td className="px-4 py-3 align-top">
        <div className="text-sm font-medium">{humanize(item.key)}</div>
        <div className="text-xs text-muted-foreground">
          {DESCRIPTIONS[item.key]}
        </div>
      </td>
      <td className="px-4 py-3">{children}</td>
      <td className="whitespace-nowrap px-4 py-3 text-xs text-muted-foreground">
        default {String(item.default)}
      </td>
      <td className="px-4 py-3 text-right">
        {overridden && (
          <Button
            variant="ghost"
            size="sm"
            disabled={reset.isPending}
            onClick={() =>
              reset.mutate(item.key, {
                onError: () => toast.error("Reset failed"),
              })
            }
          >
            Reset
          </Button>
        )}
      </td>
    </tr>
  );
}

function BooleanRow({ item }: { item: SettingItem }) {
  const update = useUpdateSetting();
  return (
    <RowShell item={item}>
      <input
        type="checkbox"
        className="h-4 w-4 accent-primary"
        checked={Boolean(item.value)}
        disabled={update.isPending}
        onChange={(e) =>
          update.mutate(
            { key: item.key, value: e.target.checked },
            {
              onSuccess: () => toast.success(`${humanize(item.key)} saved`),
              onError: () => toast.error("Save failed"),
            },
          )
        }
      />
    </RowShell>
  );
}

function NumberRow({ item }: { item: SettingItem }) {
  const update = useUpdateSetting();
  const [draft, setDraft] = useState(String(item.value));
  const changed = draft !== String(item.value);

  function save() {
    const num =
      item.type === "integer" ? parseInt(draft, 10) : parseFloat(draft);
    if (Number.isNaN(num)) {
      toast.error("Enter a valid number");
      return;
    }
    update.mutate(
      { key: item.key, value: num },
      {
        onSuccess: (saved) => {
          setDraft(String(saved.value));
          toast.success(`${humanize(item.key)} saved`);
        },
        onError: () => toast.error("Save failed"),
      },
    );
  }

  return (
    <RowShell item={item}>
      <div className="flex items-center gap-2">
        <Input
          type="number"
          step={item.type === "integer" ? 1 : "any"}
          value={draft}
          className="w-28"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && changed && save()}
        />
        <Button size="sm" disabled={!changed || update.isPending} onClick={save}>
          Save
        </Button>
      </div>
    </RowShell>
  );
}

function SettingRow({ item }: { item: SettingItem }) {
  return item.type === "boolean" ? (
    <BooleanRow item={item} />
  ) : (
    <NumberRow key={String(item.value)} item={item} />
  );
}

export function SettingsPage() {
  const { data, isPending, isError } = useSettings();
  const byKey = new Map((data ?? []).map((s) => [s.key, s]));

  return (
    <div className="space-y-6">
      <PageHeader
        title="Settings"
        description="Tunable parameters. Changes are stored in the database and take effect on the next worker job — no restart needed."
      />

      {isError && (
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
          Failed to load settings.
        </div>
      )}
      {isPending && <div className="h-40 animate-pulse rounded-lg bg-muted" />}

      {data &&
        SECTIONS.map((section) => (
          <div key={section.title} className="space-y-2">
            <h2 className="text-base font-semibold">{section.title}</h2>
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full min-w-[560px] text-left">
                <tbody>
                  {section.keys.map((key) => {
                    const item = byKey.get(key);
                    return item ? <SettingRow key={key} item={item} /> : null;
                  })}
                </tbody>
              </table>
            </div>
          </div>
        ))}
    </div>
  );
}
