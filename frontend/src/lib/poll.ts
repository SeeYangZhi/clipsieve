export interface PollOptions {
  /** Set `cancelled` to stop after the fetch in flight; the poll resolves with what it has. */
  cancel?: { cancelled: boolean };
  intervalMs: number;
  /** No fetch starts later than this after the first one. */
  maxMs: number;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Calls `fetch` now and every `intervalMs` until `ok(value)`, `cancel.cancelled`
 * or `maxMs` has passed. Resolves with the accepted value, else the last value
 * fetched, else null (every fetch failed). A failed fetch is skipped, not thrown.
 */
export function pollUntil<T>(
  fetch: () => Promise<T>,
  ok: (value: T) => boolean,
  { cancel, intervalMs, maxMs }: PollOptions
): Promise<T | null> {
  const started = Date.now();
  const attempt = async (previous: T | null): Promise<T | null> => {
    let last = previous;
    try {
      last = await fetch();
      if (ok(last)) {
        return last;
      }
    } catch {
      // keep polling
    }
    if (cancel?.cancelled || Date.now() - started + intervalMs > maxMs) {
      return last;
    }
    await sleep(intervalMs);
    return cancel?.cancelled ? last : attempt(last);
  };
  return attempt(null);
}
