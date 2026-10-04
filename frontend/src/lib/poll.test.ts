import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { pollUntil } from "./poll";

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("pollUntil", () => {
  it("resolves with the first value the predicate accepts", async () => {
    const fetch = vi
      .fn<() => Promise<{ paused: boolean }>>()
      .mockResolvedValueOnce({ paused: false })
      .mockResolvedValueOnce({ paused: false })
      .mockResolvedValue({ paused: true });
    const p = pollUntil(fetch, (r) => r.paused, {
      intervalMs: 500,
      maxMs: 10_000,
    });
    await vi.advanceTimersByTimeAsync(1000);
    await expect(p).resolves.toEqual({ paused: true });
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it("falls back to the last value fetched when the server never agrees", async () => {
    const fetch = vi.fn(async () => ({ paused: false, tick: Date.now() }));
    const p = pollUntil(fetch, (r) => r.paused, {
      intervalMs: 500,
      maxMs: 2000,
    });
    await vi.advanceTimersByTimeAsync(2500);
    const last = await p;
    expect(last?.paused).toBe(false);
    // 0, 500, 1000, 1500, 2000 ms: five polls, none after maxMs.
    expect(fetch).toHaveBeenCalledTimes(5);
  });

  it("ignores a failed fetch and keeps polling; null when none succeeded", async () => {
    const flaky = vi
      .fn<() => Promise<{ paused: boolean }>>()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue({ paused: true });
    const p = pollUntil(flaky, (r) => r.paused, {
      intervalMs: 500,
      maxMs: 10_000,
    });
    await vi.advanceTimersByTimeAsync(500);
    await expect(p).resolves.toEqual({ paused: true });

    const dead = vi.fn(() => Promise.reject(new Error("offline")));
    const q = pollUntil(dead, () => true, { intervalMs: 500, maxMs: 1000 });
    await vi.advanceTimersByTimeAsync(1500);
    await expect(q).resolves.toBeNull();
  });

  it("stops early when cancelled", async () => {
    const fetch = vi.fn(async () => ({ paused: false }));
    const cancel = { cancelled: false };
    const p = pollUntil(fetch, (r) => r.paused, {
      cancel,
      intervalMs: 500,
      maxMs: 10_000,
    });
    await vi.advanceTimersByTimeAsync(600);
    cancel.cancelled = true;
    await vi.advanceTimersByTimeAsync(5000);
    await expect(p).resolves.toEqual({ paused: false });
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});
