import { useMemo } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { DeleteFrameButton } from "@/components/DeleteFrameButton";
import { useFrame, type Detection, type FrameDetail } from "@/hooks/useFrame";
import { useClasses, type VdClass } from "@/hooks/useClasses";

const FALLBACK_COLOR = "#888888";

function classOf(det: Detection, classes: Map<string, VdClass>) {
  const cls = det.class_id ? classes.get(det.class_id) : undefined;
  return {
    name: cls?.name ?? "unknown",
    color: cls?.color_hex ?? FALLBACK_COLOR,
  };
}

function DetectionOverlay({
  frame,
  classes,
}: {
  frame: FrameDetail;
  classes: Map<string, VdClass>;
}) {
  const hasDims = frame.width > 0 && frame.height > 0;

  return (
    <div className="relative inline-block max-w-full">
      <img
        src={frame.image_url ?? undefined}
        alt={`Frame ${frame.frame_index}`}
        className="block h-auto max-w-full rounded border border-border"
      />
      {hasDims && (
        <svg
          viewBox={`0 0 ${frame.width} ${frame.height}`}
          preserveAspectRatio="xMidYMid meet"
          className="pointer-events-none absolute inset-0 h-full w-full"
        >
          {frame.detections.map((d) => {
            const { color } = classOf(d, classes);
            return (
              <rect
                key={d.id}
                x={d.bbox.x * frame.width}
                y={d.bbox.y * frame.height}
                width={d.bbox.w * frame.width}
                height={d.bbox.h * frame.height}
                fill="none"
                stroke={color}
                strokeWidth={2}
                vectorEffect="non-scaling-stroke"
              />
            );
          })}
        </svg>
      )}
      {hasDims &&
        frame.detections.map((d) => {
          const { name, color } = classOf(d, classes);
          const conf =
            d.confidence_class != null
              ? ` ${Math.round(d.confidence_class * 100)}%`
              : "";
          return (
            <span
              key={d.id}
              className="absolute -translate-y-full whitespace-nowrap rounded-t px-1.5 py-0.5 text-[11px] font-medium leading-tight text-white"
              style={{
                left: `${d.bbox.x * 100}%`,
                top: `${d.bbox.y * 100}%`,
                backgroundColor: color,
              }}
            >
              {name}
              {conf}
            </span>
          );
        })}
    </div>
  );
}

export function FrameDetailPage() {
  const { id, frameId } = useParams<{ id: string; frameId: string }>();
  const navigate = useNavigate();

  const { data: frame, isPending, isError } = useFrame(frameId ?? "");
  const { data: classList } = useClasses();
  const classes = useMemo(
    () => new Map((classList ?? []).map((c) => [c.id, c])),
    [classList],
  );

  const backToClip = () => navigate(`/clips/${id}`);

  if (isError) {
    return (
      <div className="space-y-4">
        <PageHeader
          title="Frame"
          breadcrumbs={[
            { label: "Clips", to: "/clips" },
            { label: "Clip", to: `/clips/${id}` },
          ]}
        />
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
          Frame not found.
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={[
          { label: "Clips", to: "/clips" },
          { label: "Clip", to: `/clips/${id}` },
        ]}
        title={
          isPending ? (
            <span className="inline-block h-6 w-32 animate-pulse rounded bg-muted align-middle" />
          ) : (
            `Frame ${frame?.frame_index}`
          )
        }
        meta={
          frame != null && (
            <span className="text-sm font-normal text-muted-foreground">
              {frame.timestamp_sec.toFixed(1)}s · {frame.detections.length}{" "}
              detection{frame.detections.length === 1 ? "" : "s"}
            </span>
          )
        }
        actions={
          frame != null && (
            <>
              <DeleteFrameButton
                frameId={frame.id}
                clipId={frame.clip_id}
                frameIndex={frame.frame_index}
                onDeleted={backToClip}
              />
              <Button
                size="sm"
                onClick={() => navigate(`/labeling/${frame.id}`)}
              >
                Label this frame
              </Button>
            </>
          )
        }
      />

      {isPending ? (
        <div className="aspect-video w-full max-w-3xl animate-pulse rounded bg-muted" />
      ) : frame == null ? null : frame.image_url == null ? (
        <div className="rounded-lg border border-border p-4 text-sm text-muted-foreground">
          This frame had no detected objects and its image was pruned.
        </div>
      ) : (
        <DetectionOverlay frame={frame} classes={classes} />
      )}
    </div>
  );
}
