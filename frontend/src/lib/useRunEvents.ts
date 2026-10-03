"use client";

import { useEffect, useRef, useState } from "react";
import { eventsUrl } from "./api";
import { type DashboardState, initialState, reduceEvent } from "./events";
import type { RunEvent } from "./types";

export type RunEventsOptions =
  | { mode: "live" }
  | { mode: "replay"; speed: number; playing: boolean };

/** The part of the browser `EventSource` the hook uses; tests inject a fake. */
export interface EventSourceLike {
  addEventListener: (type: "run_event", fn: (e: MessageEvent) => void) => void;
  close: () => void;
  onerror: ((e: Event) => void) | null;
  onopen: ((e: Event) => void) | null;
}
export type EventSourceFactory = (url: string) => EventSourceLike;

export interface RunEventsResult {
  /** True while an EventSource is open (live tail, or loading a replay). */
  connected: boolean;
  /** Events applied to `state`, in order, each once. */
  events: RunEvent[];
  /** Replay: played / total, 0..1. Live: 1 once the run is terminal, else 0. */
  progress: number;
  state: DashboardState;
}

// Only ever called inside an effect, so server rendering never touches EventSource.
const defaultFactory: EventSourceFactory = (url) =>
  new EventSource(url) as unknown as EventSourceLike;

const RECONNECT_MS = 1000;

/** The server's rule: the stream ends at `done` or the first event in stage `failed`. */
function isTerminal(e: RunEvent): boolean {
  return e.type === "done" || e.stage === "failed";
}

function parse(msg: MessageEvent): RunEvent {
  return JSON.parse(msg.data as string) as RunEvent;
}

/** Everything one (mode, runId) pair shows; replaced wholesale when either changes. */
interface Session {
  connected: boolean;
  /** Replay: number of `log` events played. */
  cursor: number;
  events: RunEvent[];
  key: string;
  /** Replay: the whole run log once loaded. */
  log: RunEvent[] | null;
  state: DashboardState;
}

function freshSession(key: string): Session {
  return {
    connected: false,
    cursor: 0,
    events: [],
    key,
    log: null,
    state: initialState(),
  };
}

/** An updater that ignores late callbacks from a session that has been replaced. */
function forSession(
  key: string,
  fn: (s: Session) => Session
): (s: Session) => Session {
  return (s) => (s.key === key ? fn(s) : s);
}

function withConnected(connected: boolean) {
  return (s: Session): Session =>
    s.connected === connected ? s : { ...s, connected };
}

/** Apply one live event; a seq already applied (reconnect overlap) is a no-op. */
function applyLive(ev: RunEvent) {
  return (s: Session): Session =>
    ev.seq <= s.state.lastSeq
      ? s
      : { ...s, events: [...s.events, ev], state: reduceEvent(s.state, ev) };
}

/** Play log[i]; only applies when exactly i events have been played. */
function applyReplay(i: number, ev: RunEvent) {
  return (s: Session): Session =>
    s.cursor === i
      ? {
          ...s,
          cursor: i + 1,
          events: [...s.events, ev],
          state: reduceEvent(s.state, ev),
        }
      : s;
}

function progressOf(mode: RunEventsOptions["mode"], s: Session): number {
  if (mode === "live") {
    return s.state.done ? 1 : 0;
  }
  return s.log && s.log.length > 0 ? s.cursor / s.log.length : 0;
}

interface Playhead {
  /** Original-time ms of the current gap already waited before a pause or speed change. */
  carry: number;
  cursor: number;
  log: RunEvent[] | null;
}

/**
 * Feeds the pure reducer from the run's SSE stream.
 *
 * live: tails `/events?after=<lastSeq>`; on error closes and reopens after
 * RECONNECT_MS with the last applied seq, so the state matches an
 * uninterrupted stream; stops at the terminal event.
 *
 * replay: loads the whole log from `after=0`, then plays it with the original
 * inter-event gaps divided by `speed`. Pausing or changing speed keeps the
 * position, including time already waited inside the current gap.
 *
 * `factory` must be referentially stable (module-level), or every render reconnects.
 */
export function useRunEvents(
  runId: string,
  opts: RunEventsOptions,
  factory: EventSourceFactory = defaultFactory
): RunEventsResult {
  const { mode } = opts;
  const playing = opts.mode === "replay" && opts.playing;
  const speed = opts.mode === "replay" ? opts.speed : 1;
  const key = `${mode}:${runId}`;

  const [stored, setSession] = useState(() => freshSession(key));
  let session = stored;
  if (stored.key !== key) {
    // A different run or mode: reset during render, so nothing stale commits.
    session = freshSession(key);
    setSession(session);
  }
  const { log } = session;
  const playhead = useRef<Playhead>({ carry: 0, cursor: 0, log: null });

  // Live: stream, reduce, reconnect with after=lastSeq, stop at terminal.
  useEffect(() => {
    if (mode !== "live") {
      return;
    }
    const update = (fn: (s: Session) => Session) =>
      setSession(forSession(key, fn));
    let lastSeq = 0;
    let stopped = false;
    let source: EventSourceLike | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      retry = null;
      const es = factory(eventsUrl(runId, lastSeq));
      source = es;
      es.onopen = () => update(withConnected(true));
      es.addEventListener("run_event", (msg) => {
        const ev = parse(msg);
        if (stopped || ev.seq <= lastSeq) {
          return;
        }
        lastSeq = ev.seq;
        update(applyLive(ev));
        if (isTerminal(ev)) {
          stopped = true;
          es.close();
          update(withConnected(false));
        }
      });
      es.onerror = () => {
        es.close();
        update(withConnected(false));
        if (!stopped) {
          retry = setTimeout(connect, RECONNECT_MS);
        }
      };
    };

    connect();
    return () => {
      stopped = true;
      if (retry !== null) {
        clearTimeout(retry);
      }
      source?.close();
    };
  }, [factory, key, mode, runId]);

  // Replay, phase 1: buffer the whole log (the server closes after terminal).
  useEffect(() => {
    if (mode !== "replay") {
      return;
    }
    const update = (fn: (s: Session) => Session) =>
      setSession(forSession(key, fn));
    const buffer: RunEvent[] = [];
    let finished = false;
    const es = factory(eventsUrl(runId, 0));

    const finish = () => {
      if (finished) {
        return;
      }
      finished = true;
      es.close();
      const loaded = [...buffer];
      // A new log restarts playback from its first event.
      update(() => ({ ...freshSession(key), log: loaded }));
    };

    es.onopen = () => update(withConnected(true));
    es.addEventListener("run_event", (msg) => {
      const ev = parse(msg);
      if (finished || ev.seq <= (buffer.at(-1)?.seq ?? 0)) {
        return;
      }
      buffer.push(ev);
      if (isTerminal(ev)) {
        finish();
      }
    });
    // An error before the terminal event replays what arrived.
    es.onerror = finish;

    return () => {
      finished = true;
      es.close();
    };
  }, [factory, key, mode, runId]);

  // Replay, phase 2: one self-rescheduling timer walks the log at `speed`.
  useEffect(() => {
    if (log === null || !playing || !(speed > 0)) {
      return;
    }
    const update = (fn: (s: Session) => Session) =>
      setSession(forSession(key, fn));
    if (playhead.current.log !== log) {
      playhead.current = { carry: 0, cursor: 0, log };
    }
    const head = playhead.current;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let scheduledAt = 0;

    const scheduleNext = () => {
      timer = null;
      const i = head.cursor;
      if (i >= log.length) {
        return;
      }
      const gap =
        i === 0 ? 0 : Date.parse(log[i].ts) - Date.parse(log[i - 1].ts);
      scheduledAt = Date.now();
      timer = setTimeout(
        () => {
          head.cursor = i + 1;
          head.carry = 0;
          update(applyReplay(i, log[i]));
          scheduleNext();
        },
        Math.max(0, gap - head.carry) / speed
      );
    };

    scheduleNext();
    return () => {
      if (timer !== null) {
        clearTimeout(timer);
        head.carry += (Date.now() - scheduledAt) * speed;
      }
    };
  }, [key, log, playing, speed]);

  return {
    connected: session.connected,
    events: session.events,
    progress: progressOf(mode, session),
    state: session.state,
  };
}
