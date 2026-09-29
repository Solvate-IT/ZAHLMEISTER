/** Page size requested from paged list endpoints (backend: app/api/pagination.py). */
export const PAGE_SIZE = 500;
export const TOTAL_COUNT_HEADER = "x-total-count";

/**
 * Read every page of a paged list endpoint. Each request stays bounded on the
 * server while callers still receive the complete list. Without a total-count
 * header (an unpaged endpoint) the first response is the whole list.
 */
export async function collectPages<T>(
  fetchPage: (query: string) => Promise<Response>,
): Promise<T[]> {
  const items: T[] = [];
  for (let offset = 0; ; offset += PAGE_SIZE) {
    const response = await fetchPage(`limit=${PAGE_SIZE}&offset=${offset}`);
    const page = (await response.json()) as T[];
    items.push(...page);
    const header = response.headers.get(TOTAL_COUNT_HEADER);
    const complete = header === null || items.length >= Number(header);
    if (complete || page.length < PAGE_SIZE) return items;
  }
}

export function withQuery(path: string, query: string): string {
  return `${path}${path.includes("?") ? "&" : "?"}${query}`;
}
