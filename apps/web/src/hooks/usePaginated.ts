import {
  useInfiniteQuery,
  type InfiniteData,
  type QueryKey,
} from "@tanstack/react-query";

/** Cursor-paged response envelope from the backend. Mirrors
 *  `apps/api/src/api/schemas/common.py:Paginated` and the contract in
 *  `specs/04-backend-api.md`. */
export interface Paginated<T> {
  items: T[];
  total: number;
  next_cursor: string | null;
}

interface Args {
  /** Query key — filter params should be included so changing them tears
   *  down the old infinite query cleanly and starts a fresh page 1. */
  queryKey: QueryKey;
  /** Base URL, e.g. "/api/training-runs". `cursor` and `limit` are appended;
   *  callers pass everything else via `params`. */
  url: string;
  params?: Record<string, string | number | boolean | undefined | null>;
  /** Default 50; the backend clamps to [1, 200]. */
  limit?: number;
  enabled?: boolean;
}

/** TanStack v5 `useInfiniteQuery` shaped to the project's cursor envelope.
 *
 *  Returns a flattened ergonomic shape: `rows` is the concatenation of all
 *  loaded pages, `total` is the filtered total (from the envelope), and the
 *  navigation handles are exposed directly. Intentionally narrower than the
 *  full `UseInfiniteQueryResult` — consumers should not need its internals. */
export function useCursorInfiniteQuery<T>({
  queryKey,
  url,
  params,
  limit = 50,
  enabled = true,
}: Args) {
  const query = useInfiniteQuery<
    Paginated<T>,
    Error,
    InfiniteData<Paginated<T>, string | null>,
    QueryKey,
    string | null
  >({
    queryKey,
    enabled,
    initialPageParam: null,
    queryFn: async ({ pageParam, signal }) => {
      const qs = new URLSearchParams();
      qs.set("limit", String(limit));
      if (pageParam) qs.set("cursor", pageParam);
      if (params) {
        for (const [k, v] of Object.entries(params)) {
          if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
        }
      }
      const res = await fetch(`${url}?${qs.toString()}`, { signal });
      if (!res.ok) {
        throw Object.assign(new Error(`Failed to fetch ${url}`), {
          status: res.status,
        });
      }
      return res.json() as Promise<Paginated<T>>;
    },
    // v5 footgun: return undefined (not null) to signal "no more pages".
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    // Cap memory on deep scrolls. Keyset cursors are stable across inserts,
    // so eviction + re-fetch on scroll-back is seamless.
    maxPages: 10,
  });

  const rows: T[] = query.data?.pages.flatMap((p) => p.items) ?? [];
  const total = query.data?.pages[0]?.total ?? 0;

  return {
    rows,
    total,
    hasNextPage: query.hasNextPage,
    isFetchingNextPage: query.isFetchingNextPage,
    fetchNextPage: query.fetchNextPage,
    isPending: query.isPending,
    isError: query.isError,
    refetch: query.refetch,
  };
}
