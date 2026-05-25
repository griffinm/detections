# 08 — Labeling UI

**Status:** Phase 3 (canvas, class picker, hotkeys, review queue) and the
Phase 4 sub-class layer (sub-class picker under the selected detection,
`Shift+1…9` assignment, `S` promote-to-example, examples gallery on
`/classes/:id`) are implemented. A later polish pass added the on-canvas
"original → current" chip on the selected detection, inline `+ New sub-class`
creation in the class picker, and the `unreviewed` / class-targeted queue
strategies.

The labeling UI is where the project earns its keep. It has to support:

- Confirming auto-detected boxes with a single keystroke.
- Correcting class / sub-class assignments.
- Resizing / moving boxes.
- Drawing brand-new boxes (required for bootstrapping custom classes like
  "deer" before the model knows about them).
- Promoting good crops to canonical sub-class examples.
- Keyboard-driven flow so a user can chew through hundreds of frames fast.

## Layout

```
┌──── Topbar ──────────────────────────────────────────────────────┐
│ clip-name  · frame 42/213 · ←/→ ·  [Save]  [Skip]  [End]  ⌨ ?    │
├──────────────────┬─────────────────────────────┬──────────────────┤
│  Detections      │                             │  Class picker    │
│ ─ [✓] person 0.94│                             │  ▸ person        │
│   ▸ Mallory 0.78 │                             │    ▸ Mallory     │
│ ─ [ ] car 0.41   │       Canvas (image +       │    ▸ Griffin     │
│ ─ [+] new …      │        bounding boxes)      │  ▸ car           │
│                  │                             │  ▸ dog           │
│                  │                             │  ▸ bear          │
│                  │                             │  ▸ deer (custom) │
│                  │                             │                  │
│                  │                             │  [+ New class]   │
└──────────────────┴─────────────────────────────┴──────────────────┘
       left rail: list                center: canvas          right rail: classes
```

Three columns; the center canvas takes most of the width. On narrower
viewports the right rail collapses into a popover.

## Canvas

Use **`react-konva`** (Konva via React). Reasons:
- Real layered scene graph; bbox rectangles are first-class objects.
- Transform handles, drag, scale are built-in.
- Better perf than an SVG-per-bbox approach when frames have many boxes.
- Saner zoom/pan than reinventing it on a `<canvas>`.

Layers:
1. **Image layer** — the frame JPEG drawn once at native resolution.
2. **Detection layer** — one `Rect` per detection, colored by class.
3. **Overlay layer** — the active drag/resize handles, the in-progress
   "draw" rect, marquee selection.

State held in Zustand, not Konva, so we can save/restore independently.

## Modes

A simple state machine in the labeling store:

```
IDLE ──(click bbox)──> SELECTED ──(drag handle)──> RESIZING ──> SELECTED
  │                       │
  │                       └──(drag body)──> MOVING ──> SELECTED
  │
  └──(hold "B" + drag)──> DRAWING ──(release)──> SELECTED (new det)

SELECTED ──(Esc / click empty)──> IDLE
```

`B` is the "Box" hotkey; we deliberately don't make plain drag-on-empty
start a new box (too easy to do by accident when panning).

On frame load the first detection is auto-selected (state starts in
`SELECTED`, not `IDLE`) so `↑`/`↓` and class hotkeys work without a
priming click. Selection is seeded once per frame and survives eager-save
cache updates.

## Hotkeys

| Key             | Action                                                  |
|-----------------|---------------------------------------------------------|
| `J` / `K`       | Next / previous frame (within current clip OR queue)    |
| `↑` / `↓`       | Cycle selection through detections in the frame (wraps) |
| `Space`         | Mark all detections on this frame "accepted as-is"      |
| `Enter`         | Save current frame (= mark all selected dets reviewed)  |
| `Shift+Enter`   | Save current frame, then advance to the next queued frame |
| `B`             | Hold + drag to draw a new box                           |
| `1`–`9`         | Assign top-level class by index (visible in right rail) |
| `Shift+1`–`9`   | Assign sub-class within currently selected class        |
| `R`             | Toggle "needs reassign" flag                            |
| `Delete` / `X`  | Delete selected detection                               |
| `S`             | Promote selected detection to subclass example         |
| `Esc`           | Deselect / cancel current draw                          |
| `?`             | Show keymap modal                                       |
| `Ctrl+Z` / `Y`  | Undo / redo (per-frame)                                 |

A focus indicator on the canvas vs the class picker disambiguates which
sub-tree numeric keys go to.

## Drawing / editing semantics

- Coords stored as normalized `{x,y,w,h}` (0..1). Translated to pixel
  coords on render.
- Resize: 8 handles (corners + edges). Snap to 1-pixel grid in pixel
  space, then re-normalize.
- Minimum size: 6 px in pixel space. Smaller draws are aborted.
- Aspect-ratio lock: hold `Shift` during resize.
- Constrained-to-image: bbox is clamped to the image rect; can't drag
  off-canvas.

## Class picker UX

Right rail is a flat-but-grouped tree:

- Top-level classes shown with their color swatch and configured hotkey
  index.
- Expanding a class shows its sub-classes with their hotkeys.
- Click anywhere selects: if a detection is selected, that detection
  is assigned. If no detection is selected, the choice becomes the
  "default class for the next-drawn box" (visible in the topbar).
- `+ New class` opens a modal; submits to `POST /api/classes` and
  appends to the list.
- `+ New sub-class` appears inline under each expanded class — it opens the
  shared `SubclassFormDialog`, so a sub-class can be created without leaving
  the labeling screen.

## Saving

We save eagerly (per change) using PATCH, not on a "save" button. The
"Save" button means "mark all currently-displayed unreviewed detections
as `reviewed=true`" — i.e., it asserts user agreement with everything on
screen. This is the most common path. **Save & Next** (`Shift+Enter`, the
primary topbar button) does the same review then advances to the next queued
frame, so a confirmed frame is one click/keystroke.

Conflict resolution: single-user app → optimistic, no conflict.

## Undo / redo

Per-frame, in-memory ring buffer of up to 50 edits. Because editing is
eager-saved (milestone 09), undo/redo are **not** pure local reverts — each
stack entry is an inverse API call:

- move/resize or reclassify → inverse `PATCH`
- draw a new box → undo `DELETE`, redo `restore`
- delete → undo `restore`, redo `DELETE`

Soft-deleted detections keep stable ids, so redo after an undo-of-delete (or
undo-of-draw) reattaches the same row. The history is cleared on frame change.

## Review queue

Two ways to enter the labeling UI:

1. From a clip → frame: free-form, you choose what to look at.
2. From the **Labeling Queue** (`/labeling`): a prioritized list. The
   user clicks "Start" and is taken to `/labeling/:fid` with the queue
   id in the URL. J / K advance through the queue.

Queue prioritization strategies — implemented (`strategy` + `class_id` query
params on `/api/labeling/queue`, exposed as two selectors on `/labeling`):
- **Low confidence** (`lowconf`): frames ordered by their lowest unreviewed
  `confidence_class`, ascending.
- **Unreviewed first** (`unreviewed`): newest unfinished frame first.
- **Class-targeted** (`class_id`): orthogonal filter — only frames with an
  unreviewed detection of that class; per-frame counts scope to it.

Deferred: **Recent corrections** — frames near recently corrected ones, as a
kNN over the corrected detection's embedding (`specs/deferred.md`).

## Bulk labeling

The per-frame queue handles "one decision at a time". Two additional sub-pages
turn many decisions into one, sharing the same `<DetectionTileGrid>` +
`<DetectionPreview>` pair and the backend `POST /api/labeling/bulk-review`
write path. A `<LabelingTabs>` strip under the page header switches between
**Frame queue** (default `/labeling`), **Predicted groups**, and **By clip**
(lands on the clip list, where each clip detail page now has a `Bulk-label`
button).

### Tile grid + preview interaction

Tile thumbnails are small (96 px) so the user can scan many at once, which
means click semantics are split:

- **Click the tile body** → focuses the tile (moves the side preview panel
  to it); does **not** change selection.
- **Click the corner checkbox** → explicit selection toggle.
- **Shift-click the tile body** → range-selects from the last-focused tile.
- **Select all / Clear** buttons cover the bulk cases.

The right-rail `<DetectionPreview>` shows the focused detection at three
useful levels: a large cached crop (`/api/detections/{id}/crop?size=512`),
the whole frame JPEG with the bbox drawn over it as an `inset`-positioned
div using normalized coords, and a deep-link to `/labeling/:frame_id` if
the user needs to fix the box itself.

### Predicted groups (`/labeling/groups`)

Renders `GET /api/labeling/predicted-groups` as a grid of cards keyed by
`(predicted_subclass, confidence_bucket)`. Each card shows: subclass name,
parent class, count, a bucket pill (`high ≥0.85 / med ≥0.7 / low ≥
subclass_min_confidence`), and a 9-thumb preview strip drawn from the
group's `sample_detection_ids`. Selecting a card fetches the full group via
`GET /api/labeling/predicted-group-detections`, lays the tiles out in a
multi-select grid, defaults every tile to selected, and exposes a Select
that defaults to the predicted sub-class but can be overridden to a sibling
sub-class. **Apply** sends one `POST /api/labeling/bulk-review` with
`subclass_id` and `reviewed=true`.

### Clip-scoped (`/labeling/clips/:clip_id`)

The "same subject across 30 frames" view. Class filter defaults to the most-
common class in the clip via `GET /api/clips/{id}/class-summary`. The tile
grid is `GET /api/clips/{id}/detections?class_id=...&include=auto|reviewed|all`
ordered by `frame_index` so the clip reads left-to-right. Multi-select supports
click, shift-click range, and Select all / Clear; the Apply target is the
sub-class chosen from a Select. Same bulk endpoint as above.

### Similarity clusters (`/labeling/similarity`)

Companion to `/labeling/groups`: that view groups by the auto-assigner's
`predicted_subclass_id`; this one ignores predictions and clusters un-reviewed,
un-assigned detections of one class purely by embedding similarity. Useful
when the auto-assigner has nothing to commit yet (no examples, sub-classes
not seeded, kNN below `subclass_min_confidence`).

Backend: `GET /api/labeling/similarity-clusters?class_id=...&cluster_size=8&max_clusters=40&max_pool=2000`.
Pool = detections where `class_id=:id AND reviewed=false AND subclass_id IS NULL
AND deleted_at IS NULL AND frames.kept = true AND any embedding non-null`,
oldest first, capped at `max_pool` (`pool_truncated=true` when exceeded). The
handler does greedy seed-iteration: pop the oldest un-clustered detection as
the seed, fetch its `cluster_size - 1` nearest neighbors from the remaining
pool via pgvector cosine distance over the HNSW indexes
(`ix_detections_{face,object}_embedding`), emit one cluster, repeat until
`max_clusters` or the pool is exhausted. The face-vs-object embedding dispatch
mirrors `vd.assign_subclass` (face beats object when both are present);
`embedding_kind` reports which space the class actually used. Anything that
didn't fit appears as `remaining` so the UI can prompt for a refresh after
the user labels some.

The page renders one `<DetectionTileGrid>` per cluster, all sharing the same
`selectedIds` set so selection composes across clusters. Each cluster has a
**Select cluster / Deselect cluster** toggle for the common "this whole
group is one sub-class" case. The toolbar is a `<Select>` of `class`
sub-classes plus an **Apply** button that calls the same
`POST /api/labeling/bulk-review` with `{class_id, subclass_id, reviewed:true}` —
class is passed alongside subclass so the bulk endpoint's class-coercion path
handles rows whose `class_id` somehow drifted from the filter.

### Unified-apply semantics

`POST /api/labeling/bulk-review` accepts any subset of `{class_id,
subclass_id, reviewed}` and applies it to every detection in
`detection_ids`. Per row the audit reason is inferred exactly like the
per-detection PATCH — `user_reassign` when class or subclass changes,
`user_review` when reviewed flips false→true. Soft-deleted rows and rows
where the chosen sub-class would belong to a different class (without an
overriding `class_id` in the same call) are silently skipped and surfaced
in the response as `skipped`. The mutation invalidates the affected
TanStack Query caches (`predicted-groups`, `similarity-clusters`,
`clip-detections`, `labeling-queue`, the class/sub-class galleries, and
any open `frames/:id`
queries via the response's `affected_frame_ids`); SSE handles open frame
views in real time.

### Out of scope (deferred)

- **Undo for bulk apply.** The per-detection undo ring buffer is local to a
  frame; a bulk action can touch hundreds of detections across many frames.
  Re-running bulk with the previous state is the workaround until a
  general bulk-undo is justified.
- **kNN "find similar" sidebar inside the per-frame view**, pseudo-tracks via
  IoU, auto-propagation on a single label. Tracked alongside the existing
  `recent corrections` queue strategy. (Bulk embedding-cluster discovery now
  lives on `/labeling/similarity`.)

## Class / sub-class detail page

Reached from `/classes/:id`. Left rail is the sub-class picker, with an
`All sub-classes` entry pinned on top that selects the whole-class view.
The right panel is a two-tab surface (`components/ui/tabs.tsx`):

- **Examples** — the curated kNN reference set.
  - Sub-class scope: `GET /api/subclasses/{id}/examples` — same gallery as
    before, with per-tile remove and a sub-class-colored border.
  - Class scope: `GET /api/classes/{id}/examples` aggregates across the
    class's active sub-classes; each tile is bordered with that sub-class's
    color so a `bear / Bruno` example reads at a glance.
- **All tagged** — every non-deleted detection currently assigned to this
  class / sub-class. Powered by `GET /api/{subclasses|classes}/{id}/detections`
  with three controls:
  - **Filter chips:** `All` (default) / `Auto` (`reviewed=false`) / `Reviewed`
    (`reviewed=true`) — distinguishes kNN auto-assignment from human review.
  - **Sort:** `Newest first` (`created_desc`) or `Recently reviewed`
    (`reviewed_desc`). State resets when switching the left-rail selection.
  - **Tile badge:** green dot = reviewed, amber dot = auto-assigned.
  - **Click** → deep-links to `/labeling/:frame_id` so a bad auto-assignment
    can be corrected in one hop.

Promoting still uses `S` in the labeling UI; the panel itself is read-only
beyond `Remove example` on the Examples tab.

When a user promotes a detection to an example, we:
1. Insert `subclass_examples` row.
2. Schedule `vd.train_subclass_classifier(class_id)` if threshold reached.

## Visual feedback

- Bbox color = class color (configurable per class).
- Bbox stroke style:
  - Solid: current class assignment.
  - Dashed: predicted but not yet user-reviewed.
  - Pulsing: low confidence flagged for review.
- Confidence shown as a thin progress bar next to the class label.
- A small chip on the selected detection shows "original → current state"
  (e.g. "person → Mallory"), drawn just above the box; it collapses to a
  single label when the prediction and the current assignment agree.
- A magnified crop of the selected detection (`DetectionCrop`) is shown
  directly under the canvas — a fixed-height, width-capped box that scales
  the frame JPEG so just the detection's region fills it, so small boxes
  stay reviewable without zooming the whole frame.

## Accessibility

- All interactive bbox handles are keyboard-reachable via Tab.
- Selected bbox has a 2px focus ring in addition to color.
- The keymap modal is reachable via `?` or the help icon.

## Performance

- Don't unmount the canvas between J/K frame switches; replace the
  background image and bbox list in place.
- Pre-fetch the next 3 frames via TanStack Query.
- For frames with > 100 detections (unlikely but possible), virtualize
  the left detection list.

## Open questions

- **Pixel-perfect drawing on high-DPI displays**: Konva handles devicePixelRatio
  automatically; verify.
- **Touch support**: out of scope for v1; this is a desktop-keyboard tool.
- **Polygon / mask labels**: out of scope. Rectangles only. If we ever
  need them, swap rect to `Line` (closed polygon) and adjust serialization.
