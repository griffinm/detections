import { useEffect, useRef, useState } from "react";
import type Konva from "konva";
import {
  Image as KonvaImage,
  Label,
  Layer,
  Rect,
  Stage,
  Tag,
  Text,
  Transformer,
} from "react-konva";
import { MIN_BOX_PX, toNormalizedBbox, toPixelRect } from "@/lib/bbox";
import { useLabelingStore } from "@/stores/labeling";
import type { useDetectionActions } from "@/hooks/useDetections";
import type { VdClass } from "@/hooks/useClasses";
import type { VdSubclass } from "@/hooks/useSubclasses";
import type { Detection, FrameDetail } from "@/hooks/useFrame";

interface Props {
  frame: FrameDetail;
  classes: VdClass[];
  subclasses: VdSubclass[];
  actions: ReturnType<typeof useDetectionActions>;
}

function useHtmlImage(src: string | null): HTMLImageElement | null {
  const [image, setImage] = useState<HTMLImageElement | null>(null);
  useEffect(() => {
    if (!src) {
      setImage(null);
      return;
    }
    const img = new window.Image();
    img.src = src;
    img.onload = () => setImage(img);
    return () => {
      img.onload = null;
    };
  }, [src]);
  return image;
}

export function LabelingCanvas({ frame, classes, subclasses, actions }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [containerW, setContainerW] = useState(0);
  const image = useHtmlImage(frame.image_url);

  const selectedId = useLabelingStore((s) => s.selectedId);
  const mode = useLabelingStore((s) => s.mode);
  const defaultClassId = useLabelingStore((s) => s.defaultClassId);
  const select = useLabelingStore((s) => s.select);
  const setMode = useLabelingStore((s) => s.setMode);

  const rectRefs = useRef(new Map<string, Konva.Rect>());
  const trRef = useRef<Konva.Transformer>(null);
  const drawStart = useRef<{ x: number; y: number } | null>(null);
  const [draft, setDraft] = useState<{
    x: number;
    y: number;
    w: number;
    h: number;
  } | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => setContainerW(el.clientWidth);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const aspect = frame.width > 0 ? frame.height / frame.width : 0.5625;
  const dispW = containerW;
  const dispH = containerW * aspect;

  // Keep the transformer attached to whichever rect is selected.
  useEffect(() => {
    const tr = trRef.current;
    if (!tr) return;
    const node = selectedId ? rectRefs.current.get(selectedId) ?? null : null;
    tr.nodes(node ? [node] : []);
    tr.getLayer()?.batchDraw();
  }, [selectedId, frame.detections, dispW, dispH]);

  const colorOf = (classId: string | null): string =>
    classes.find((c) => c.id === classId)?.color_hex ?? "#888888";

  // A detection's display name: sub-class if set, else class, else "unlabeled".
  const labelOf = (classId: string | null, subclassId: string | null): string => {
    const sub = subclassId && subclasses.find((s) => s.id === subclassId)?.name;
    if (sub) return sub;
    const cls = classId && classes.find((c) => c.id === classId)?.name;
    return cls || "unlabeled";
  };

  const chipText = (d: Detection): string => {
    const current = labelOf(d.class_id, d.subclass_id);
    const predicted = labelOf(d.predicted_class_id, d.predicted_subclass_id);
    const hasPrediction =
      d.predicted_class_id != null || d.predicted_subclass_id != null;
    return hasPrediction && predicted !== current
      ? `${predicted} → ${current}`
      : current;
  };

  const selectedDet = selectedId
    ? frame.detections.find((d) => d.id === selectedId)
    : undefined;

  function commitGeometry(id: string, node: Konva.Rect): void {
    const w = Math.max(node.width() * node.scaleX(), MIN_BOX_PX);
    const h = Math.max(node.height() * node.scaleY(), MIN_BOX_PX);
    node.scaleX(1);
    node.scaleY(1);
    const bbox = toNormalizedBbox({ x: node.x(), y: node.y(), w, h }, dispW, dispH);
    void actions.update(id, { bbox });
  }

  // Pointer (not mouse) events so box-drawing works with both mouse and touch.
  function onStagePointerDown(e: Konva.KonvaEventObject<PointerEvent>): void {
    if (mode === "drawing") {
      const pos = e.target.getStage()?.getPointerPosition();
      if (!pos) return;
      drawStart.current = pos;
      setDraft({ x: pos.x, y: pos.y, w: 0, h: 0 });
      return;
    }
    if (e.target === e.target.getStage()) select(null);
  }

  function onStagePointerMove(e: Konva.KonvaEventObject<PointerEvent>): void {
    if (mode !== "drawing" || !drawStart.current) return;
    const pos = e.target.getStage()?.getPointerPosition();
    if (!pos) return;
    const start = drawStart.current;
    setDraft({
      x: Math.min(start.x, pos.x),
      y: Math.min(start.y, pos.y),
      w: Math.abs(pos.x - start.x),
      h: Math.abs(pos.y - start.y),
    });
  }

  async function onStagePointerUp(): Promise<void> {
    if (mode !== "drawing" || !draft) return;
    const rect = draft;
    drawStart.current = null;
    setDraft(null);
    setMode("idle");
    if (rect.w >= MIN_BOX_PX && rect.h >= MIN_BOX_PX) {
      const created = await actions.create(
        toNormalizedBbox(rect, dispW, dispH),
        defaultClassId,
      );
      select(created.id);
    }
  }

  return (
    <div ref={containerRef} className="w-full">
      {dispW > 0 && image && (
        <Stage
          width={dispW}
          height={dispH}
          onPointerDown={onStagePointerDown}
          onPointerMove={onStagePointerMove}
          onPointerUp={() => void onStagePointerUp()}
          style={{
            cursor: mode === "drawing" ? "crosshair" : "default",
            // Suppress browser pan/zoom while drawing a box on a touchscreen;
            // leave vertical scroll intact otherwise so the page still scrolls.
            touchAction: mode === "drawing" ? "none" : "pan-y",
          }}
        >
          <Layer listening={false}>
            <KonvaImage image={image} width={dispW} height={dispH} />
          </Layer>
          <Layer listening={mode !== "drawing"}>
            {frame.detections.map((d) => {
              const px = toPixelRect(d.bbox, dispW, dispH);
              return (
                <Rect
                  key={d.id}
                  x={px.x}
                  y={px.y}
                  width={px.w}
                  height={px.h}
                  stroke={colorOf(d.class_id)}
                  strokeWidth={selectedId === d.id ? 3 : 2}
                  dash={d.reviewed ? undefined : [6, 4]}
                  draggable={selectedId === d.id}
                  onClick={() => select(d.id)}
                  onDragEnd={(e) => commitGeometry(d.id, e.target as Konva.Rect)}
                  onTransformEnd={(e) => commitGeometry(d.id, e.target as Konva.Rect)}
                  ref={(node) => {
                    if (node) rectRefs.current.set(d.id, node);
                    else rectRefs.current.delete(d.id);
                  }}
                />
              );
            })}
            {selectedDet &&
              (() => {
                const px = toPixelRect(selectedDet.bbox, dispW, dispH);
                return (
                  <Label x={px.x} y={Math.max(0, px.y - 20)} listening={false}>
                    <Tag fill="rgba(0,0,0,0.78)" cornerRadius={3} />
                    <Text
                      text={chipText(selectedDet)}
                      fontSize={12}
                      fill="#ffffff"
                      padding={4}
                    />
                  </Label>
                );
              })()}
            {draft && (
              <Rect
                x={draft.x}
                y={draft.y}
                width={draft.w}
                height={draft.h}
                stroke="#3b82f6"
                strokeWidth={2}
                dash={[4, 4]}
                fill="rgba(59,130,246,0.1)"
                listening={false}
              />
            )}
            <Transformer
              ref={trRef}
              rotateEnabled={false}
              ignoreStroke
              boundBoxFunc={(oldBox, newBox) =>
                newBox.width < MIN_BOX_PX || newBox.height < MIN_BOX_PX
                  ? oldBox
                  : newBox
              }
            />
          </Layer>
        </Stage>
      )}
    </div>
  );
}
