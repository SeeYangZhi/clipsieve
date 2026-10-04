import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fixtureEvents } from "./__fixtures__/run-events";
import { reduceAll } from "./events";
import type { RunEvent } from "./types";
import { type EventSourceLike, useRunEvents } from "./useRunEvents";

class FakeES implements EventSourceLike {
  static instances: FakeES[] = [];
  listeners: Partial<Record<string, ((e: MessageEvent) => void)[]>> = {};
  onerror: ((e: Event) => void) | null = null;
  onopen: ((e: Event) => void) | null = null;
  closed = false;
  url: string;
  constructor(url: string) {
    this.url = url;
    FakeES.instances.push(this);
  }
  addEventListener(type: string, fn: (e: MessageEvent) => void) {
    const list = this.listeners[type] ?? [];
    list.push(fn);
    this.listeners[type] = list;
  }
  close() {
    this.closed = true;
  }
  open() {
    this.onopen?.(new Event("open"));
  }
  send(ev: RunEvent) {
    for (const fn of this.listeners.run_event ?? []) {
      fn(
        new MessageEvent("run_event", {
          data: JSON.stringify(ev),
          lastEventId: String(ev.seq),
        })
      );
    }
  }
  fail() {
    this.onerror?.(new Event("error"));
  }
}

const factory = (url: string) => new FakeES(url);

beforeEach(() => {
  FakeES.instances = [];
  vi.useFakeTimers();
});
afterEach(() => vi.useRealTimers());

describe("useRunEvents live", () => {
  it("reduces events and reconnects with after=lastSeq", () => {
    const { result } = renderHook(() =>
      useRunEvents("FIXTURE", { mode: "live" }, factory)
    );
    const [es] = FakeES.instances;
    expect(es.url).toBe("/api/runs/FIXTURE/events?after=0");
    act(() => es.open());
    expect(result.current.connected).toBe(true);
    act(() => {
      for (const e of fixtureEvents.slice(0, 12)) {
        es.send(e);
      }
    });
    expect(result.current.state.counters.collected).toBe(5);
    act(() => es.fail());
    expect(result.current.connected).toBe(false);
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    const [, es2] = FakeES.instances;
    expect(es2.url).toBe("/api/runs/FIXTURE/events?after=12");
    act(() => {
      es2.open();
      for (const e of fixtureEvents) {
        es2.send(e);
      }
    });
    expect(result.current.state).toEqual(reduceAll(fixtureEvents));
    expect(result.current.state.done).toBe(true);
    expect(es2.closed).toBe(true);
  });
});

describe("useRunEvents replay", () => {
  it("loads the log then plays at speed with correct progress", () => {
    const { result, rerender } = renderHook(
      (props: { speed: number; playing: boolean }) =>
        useRunEvents("FIXTURE", { mode: "replay", ...props }, factory),
      { initialProps: { playing: false, speed: 1 } }
    );
    const [es] = FakeES.instances;
    act(() => {
      es.open();
      for (const e of fixtureEvents) {
        es.send(e);
      }
    });
    expect(es.closed).toBe(true);
    expect(result.current.progress).toBe(0);
    expect(result.current.state.counters.collected).toBe(0);
    rerender({ playing: true, speed: 4 });
    act(() => {
      vi.advanceTimersByTime(0);
    });
    expect(result.current.events).toHaveLength(1);
    act(() => {
      vi.advanceTimersByTime(125);
    });
    expect(result.current.events).toHaveLength(2);
    rerender({ playing: true, speed: 1 });
    act(() => {
      vi.advanceTimersByTime(20_000);
    });
    expect(result.current.events).toHaveLength(fixtureEvents.length);
    expect(result.current.progress).toBe(1);
    expect(result.current.state).toEqual(reduceAll(fixtureEvents));
  });

  it("pauses without losing position", () => {
    const { result, rerender } = renderHook(
      (props: { speed: number; playing: boolean }) =>
        useRunEvents("FIXTURE", { mode: "replay", ...props }, factory),
      { initialProps: { playing: true, speed: 16 } }
    );
    const [es] = FakeES.instances;
    act(() => {
      es.open();
      for (const e of fixtureEvents) {
        es.send(e);
      }
    });
    act(() => {
      vi.advanceTimersByTime(300);
    });
    const n = result.current.events.length;
    expect(n).toBeGreaterThan(1);
    rerender({ playing: false, speed: 16 });
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(result.current.events).toHaveLength(n);
    rerender({ playing: true, speed: 16 });
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(result.current.events).toHaveLength(fixtureEvents.length);
  });
});

function load(es: FakeES, events: RunEvent[] = fixtureEvents) {
  act(() => {
    es.open();
    for (const e of events) {
      es.send(e);
    }
  });
}

describe("useRunEvents timing and cleanup", () => {
  it("keeps time already waited when speed changes mid-gap, without skipping or repeating", () => {
    const { result, rerender } = renderHook(
      (props: { speed: number; playing: boolean }) =>
        useRunEvents("FIXTURE", { mode: "replay", ...props }, factory),
      { initialProps: { playing: true, speed: 1 } }
    );
    load(FakeES.instances[0]);
    act(() => {
      vi.advanceTimersByTime(0);
    });
    expect(result.current.events).toHaveLength(1);
    // 250 ms into the 500 ms gap before event 2, switch to 2x: 125 ms remain.
    act(() => {
      vi.advanceTimersByTime(250);
    });
    rerender({ playing: true, speed: 2 });
    act(() => {
      vi.advanceTimersByTime(124);
    });
    expect(result.current.events).toHaveLength(1);
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current.events).toHaveLength(2);
    for (const speed of [4, 1, 16, 8]) {
      rerender({ playing: true, speed });
      act(() => {
        vi.advanceTimersByTime(40);
      });
    }
    rerender({ playing: true, speed: 4 });
    act(() => {
      vi.advanceTimersByTime(20_000);
    });
    expect(result.current.events).toEqual(fixtureEvents);
    expect(result.current.state).toEqual(reduceAll(fixtureEvents));
  });

  it("stops live tailing at an event in stage failed", () => {
    const failed: RunEvent = {
      ...fixtureEvents[9],
      payload: { from: "collecting", to: "failed" },
      seq: 10,
      stage: "failed",
    };
    const { result } = renderHook(() =>
      useRunEvents("FIXTURE", { mode: "live" }, factory)
    );
    const [es] = FakeES.instances;
    load(es, [...fixtureEvents.slice(0, 9), failed]);
    expect(es.closed).toBe(true);
    expect(result.current.connected).toBe(false);
    expect(result.current.state.done).toBe(true);
    expect(result.current.progress).toBe(1);
    act(() => {
      es.fail();
      vi.advanceTimersByTime(5000);
    });
    expect(FakeES.instances).toHaveLength(1);
  });

  it("closes the source and clears timers on unmount", () => {
    const live = renderHook(() =>
      useRunEvents("FIXTURE", { mode: "live" }, factory)
    );
    act(() => FakeES.instances[0].fail());
    expect(vi.getTimerCount()).toBe(1);
    live.unmount();
    expect(vi.getTimerCount()).toBe(0);
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(FakeES.instances).toHaveLength(1);

    const replay = renderHook(() =>
      useRunEvents(
        "FIXTURE",
        { mode: "replay", playing: true, speed: 1 },
        factory
      )
    );
    const [, es] = FakeES.instances;
    replay.unmount();
    expect(es.closed).toBe(true);

    const playing = renderHook(() =>
      useRunEvents(
        "FIXTURE",
        { mode: "replay", playing: true, speed: 1 },
        factory
      )
    );
    load(FakeES.instances[2]);
    act(() => {
      vi.advanceTimersByTime(600);
    });
    expect(playing.result.current.events).toHaveLength(2);
    expect(vi.getTimerCount()).toBe(1);
    playing.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});
