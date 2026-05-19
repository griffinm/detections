# 07 — Frontend Foundation

The labeling-UI specifics live in plan 08. This one covers the app shell,
build setup, theming, routing, and the API integration layer.

## Stack

- **Vite 5** + **React 18** + **TypeScript 5** (strict).
- **Tailwind CSS 3** + **shadcn/ui** (Radix-based) component library.
- **`class-variance-authority`** + **`tailwind-merge`** (per shadcn).
- **TanStack Query 5** for server state.
- **TanStack Router** (or React Router 7) for client routing. Default
  recommendation: **React Router 7** in declarative mode (simpler;
  smaller bundle; type-safety via codegen we don't need v1).
- **Zustand** for UI-local state (selection, drag, theme persistence).
- **`@hey-api/openapi-ts`** to generate the API client into
  `libs/ts/api-client/`.
- **Lucide icons**, **sonner** for toasts (both bundled with shadcn).
- **Vitest** + **React Testing Library** for unit/component tests.
- **Playwright** for E2E (smoke flows: ingest a fixture clip, see frames,
  open one frame, draw a box, save).

## Project layout

```
apps/web/
├── index.html
├── vite.config.ts
├── tsconfig.json
├── tailwind.config.ts
├── components.json                 # shadcn config
├── src/
│   ├── main.tsx
│   ├── App.tsx                     # router root
│   ├── lib/
│   │   ├── api.ts                  # configured @vd/api-client instance
│   │   ├── query.ts                # QueryClient + retry policy
│   │   ├── sse.ts                  # EventSource hook → react-query invalidation
│   │   ├── theme.tsx               # light/dark provider
│   │   └── utils.ts                # cn(), classNames
│   ├── components/
│   │   ├── layout/                 # AppShell, Sidebar, Topbar, ThemeToggle
│   │   ├── ui/                     # shadcn copies (button, dialog, …)
│   │   ├── data/                   # DataTable, CursorPager, Empty, Loading
│   │   └── domain/                 # ClassBadge, ConfidenceBar, FrameThumb, …
│   ├── routes/
│   │   ├── dashboard.tsx
│   │   ├── clips/{index,detail}.tsx
│   │   ├── frames/{detail,labeling}.tsx
│   │   ├── classes/{index,detail}.tsx
│   │   ├── models.tsx
│   │   ├── training.tsx
│   │   ├── metrics.tsx
│   │   └── settings.tsx
│   └── hooks/
│       ├── useClips.ts             # wraps @vd/api-client + react-query
│       ├── useDetections.ts
│       └── useLiveEvents.ts        # SSE → invalidate matching queries
└── tests/
```

## Theming (light + dark)

shadcn uses CSS variables for tokens. Tailwind's `dark:` variant works in
class mode.

```css
/* src/index.css */
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    --background: 0 0% 100%;
    --foreground: 240 10% 4%;
    --muted: 240 5% 96%;
    --muted-foreground: 240 4% 46%;
    --primary: 222 47% 11%;
    --primary-foreground: 210 40% 98%;
    /* … shadcn token set … */
  }
  .dark {
    --background: 240 10% 4%;
    --foreground: 0 0% 98%;
    /* … */
  }
}
```

Theme provider:

```tsx
// src/lib/theme.tsx
type Theme = "light" | "dark" | "system";
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() =>
    (localStorage.getItem("vd.theme") as Theme) ?? "system"
  );
  useEffect(() => {
    const root = document.documentElement;
    const effective = theme === "system"
      ? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
      : theme;
    root.classList.toggle("dark", effective === "dark");
    localStorage.setItem("vd.theme", theme);
  }, [theme]);
  return <ThemeCtx value={{ theme, setTheme }}>{children}</ThemeCtx>;
}
```

A `ThemeToggle` lives in the topbar (light / dark / system).

## App shell

shadcn sidebar + topbar.

```
┌───────────────────────────────────────────────────────────────┐
│ video-detection                                ⌘K  ☼/☾  ⚙     │
├──────────────┬────────────────────────────────────────────────┤
│ ▸ Dashboard  │                                                │
│ ▸ Clips      │                                                │
│ ▸ Labeling   │             page content                       │
│ ▸ Classes    │                                                │
│ ▸ Models     │                                                │
│ ▸ Training   │                                                │
│ ▸ Metrics    │                                                │
│ ▸ Settings   │                                                │
└──────────────┴────────────────────────────────────────────────┘
```

Live status indicators in the topbar:
- queue depth pill (driven by SSE `queue.depth` events)
- "training in progress" pill if any run is active
- "GPU temp / util" optional, if we add nvidia-ml-py to system endpoint

### Responsive behaviour

The shell is responsive at the `lg` breakpoint:
- **`lg` and up** — sidebar is statically docked (`AppShell` flex row).
- **Below `lg`** — sidebar collapses to an off-canvas drawer. `AppShell`
  owns the open/closed state; `Topbar` shows a hamburger that opens it and
  `Sidebar` renders as a fixed overlay + backdrop. Nav clicks close it.

Page-level rules: every data table is wrapped in `overflow-x-auto` with a
`min-w-*` so it scrolls instead of crushing columns on a phone; grids step
down their column counts; the labeling tool (plan 08) stacks the canvas over
tabbed Detections/Classes panels below `lg`.

### Shared UI primitives

To keep pages visually consistent, common patterns are extracted rather than
re-implemented per route:
- `components/layout/PageHeader.tsx` — title + optional breadcrumbs, inline
  meta, right-aligned actions. Every route's heading row uses it.
- `components/ui/status-badge.tsx` — one badge for clip-processing **and**
  training-run statuses (shared colour map).
- `components/ui/card.tsx` — bordered section surface (title/actions/body).
- `components/ui/select.tsx` — styled native `<select>`.
- `lib/format.ts` — `formatBytes`, `formatDuration` (no per-file copies).

## Routes

| Path                          | Purpose                                            |
|-------------------------------|----------------------------------------------------|
| `/`                           | Dashboard: summary tiles + recent activity feed    |
| `/clips`                      | Paginated table of ingested clips                  |
| `/clips/:id`                  | Single clip; frame grid; detection counts          |
| `/clips/:id/frames/:fid`      | Frame viewer (read-only)                           |
| `/labeling`                   | Review queue (low-confidence / unreviewed)         |
| `/labeling/:fid`              | Per-frame labeling tool (plan 08)                  |
| `/classes`                    | List of classes                                    |
| `/classes/:id`                | Class detail: sub-classes, examples gallery        |
| `/models`                     | Model versions, activate                           |
| `/training`                   | Training runs list + start new run                 |
| `/metrics`                    | Accuracy charts + calibration                      |
| `/settings`                   | Tunable settings (DB-backed)                       |

## Data fetching pattern

```tsx
// src/hooks/useClips.ts
import { useInfiniteQuery } from "@tanstack/react-query";
import { ClipsService } from "@vd/api-client";

export function useClipsList(params: { status?: string; q?: string }) {
  return useInfiniteQuery({
    queryKey: ["clips", params],
    queryFn: ({ pageParam }) =>
      ClipsService.listClips({ ...params, cursor: pageParam, limit: 50 }),
    initialPageParam: undefined,
    getNextPageParam: (last) => last.nextCursor,
  });
}
```

All hooks share a `QueryClient` configured with:
- `staleTime: 30_000`
- `retry: (failureCount, err) => err.status !== 404 && failureCount < 2`
- `refetchOnWindowFocus: true` for dashboard, off for the labeling UI

## SSE → query invalidation

```tsx
// src/lib/sse.ts
export function useLiveEvents() {
  const qc = useQueryClient();
  useEffect(() => {
    const es = new EventSource("/api/stream/events");
    const route = (ev: MessageEvent) => {
      const e = JSON.parse(ev.data);
      switch (e.type) {
        case "clip.status":
          qc.invalidateQueries({ queryKey: ["clips"] });
          qc.invalidateQueries({ queryKey: ["clip", e.id] });
          break;
        case "frame.detect.done":
          qc.invalidateQueries({ queryKey: ["frame", e.id] });
          break;
        case "training_run.update":
          qc.invalidateQueries({ queryKey: ["trainingRuns"] });
          break;
      }
    };
    es.onmessage = route;
    return () => es.close();
  }, [qc]);
}
```

`useLiveEvents` mounts once in `App.tsx`.

## Frame image delivery

Two options for serving frame JPEGs to the browser:
1. **Static mount**: API mounts `/files/frames/*` from disk. Simple; the
   browser can cache directly; no decode overhead.
2. **Streaming endpoint**: `/api/frames/:id/image` reads the file and
   returns bytes. Lets us authorize per-request.

v1: option 1 (static mount, no auth). The static URL is included in the
frame's API response so the UI just `<img src={frame.imageUrl}>`.

For the labeling canvas we use an `<img>` decoded once and drawn into a
canvas at native resolution; zoom/pan transforms the canvas, not the
image src.

## Performance budgets

- Initial bundle (gzipped): ≤ 200 KB.
- Dashboard FCP local: ≤ 800 ms.
- Frame switch in labeling UI (J/K): ≤ 100 ms perceived.
- Code-split per route (Vite handles this with dynamic `import()` in the
  router config).

## A11y

- shadcn components are Radix-backed → accessible by default.
- Keyboard shortcuts in labeling UI are documented in a `?` modal.
- Color is never the only signal for class identity — always also a
  short label.
- Tailwind dark-mode contrast ratios > 4.5:1; spot-checked.

## Open questions

- **Router choice**: React Router 7 vs TanStack Router. RR7 is simpler;
  TanStack offers type-safe routes + loaders. Default to RR7 for v1.
  Migration to TanStack would be mechanical if we ever want it.
- **State management beyond TQ + Zustand**: probably none. If we add
  collab/multi-user later, we'd want a real shared store; not now.
