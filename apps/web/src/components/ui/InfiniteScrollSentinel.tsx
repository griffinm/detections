import { useEffect, useRef, type ReactNode, type RefObject } from "react";

interface Props {
  hasMore: boolean;
  isFetching: boolean;
  onLoadMore: () => void;
  /** Scrollable ancestor. Required when the list lives inside an
   *  `overflow-auto` wrapper — otherwise IntersectionObserver observes against
   *  the viewport, which is wrong if the wrapper itself scrolls. */
  rootRef?: RefObject<Element | null>;
  /** Pre-fetch buffer; default 200px so the next page loads before the user
   *  actually hits the bottom. */
  rootMargin?: string;
}

/** Invisible 1px target. The IntersectionObserver fires once when it enters
 *  the root, calls `onLoadMore` if there's more to fetch and we're not
 *  already fetching, and disconnects on unmount. */
export function InfiniteScrollSentinel({
  hasMore,
  isFetching,
  onLoadMore,
  rootRef,
  rootMargin = "200px",
}: Props) {
  const targetRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const target = targetRef.current;
    if (!target || !hasMore) return;

    const obs = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          // Guard with both flags: filter-change tears the old infinite query
          // down, and during the swap we should not fire-and-forget.
          if (entry.isIntersecting && hasMore && !isFetching) {
            onLoadMore();
          }
        }
      },
      { root: rootRef?.current ?? null, rootMargin },
    );
    obs.observe(target);
    return () => obs.disconnect();
  }, [hasMore, isFetching, onLoadMore, rootRef, rootMargin]);

  return <div ref={targetRef} aria-hidden="true" style={{ height: 1 }} />;
}

interface TableProps extends Props {
  colSpan: number;
  /** Optional footer content rendered above the sentinel inside the same
   *  cell — e.g. a "Loading…" or "End of results" line. */
  children?: ReactNode;
}

/** `<tr>` wrapper for sentinels that live inside a `<tbody>`. The actual
 *  observer target is the inner `InfiniteScrollSentinel`'s `<div>`. */
export function TableSentinelRow({
  colSpan,
  children,
  ...sentinel
}: TableProps) {
  return (
    <tr aria-hidden={children ? undefined : "true"}>
      <td colSpan={colSpan} className="p-0">
        {children}
        <InfiniteScrollSentinel {...sentinel} />
      </td>
    </tr>
  );
}
