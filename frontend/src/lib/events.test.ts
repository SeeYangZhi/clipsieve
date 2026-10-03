import { describe, expect, it } from "vitest";
import { buildFixtureEvents, fixtureEvents } from "./__fixtures__/run-events";
import fixtureJson from "./__fixtures__/run-events.json";
import {
  answersPerSecond,
  type DashboardState,
  initialState,
  readyPlan,
  reduceAll,
  reduceEvent,
} from "./events";
import type { RunEvent } from "./types";

function deepFreeze<T>(value: T): T {
  if (value && typeof value === "object" && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const v of Object.values(value)) {
      deepFreeze(v);
    }
  }
  return value;
}

function makeEvent(
  seq: number,
  type: string,
  stage: RunEvent["stage"],
  payload: Record<string, unknown>
): RunEvent {
  return {
    payload,
    run_id: "FIXTURE",
    seq,
    stage,
    ts: `2026-10-03T10:01:${String(seq).padStart(2, "0")}Z`,
    type,
  } as RunEvent;
}

describe("reduceEvent", () => {
  it("tracks collected posts and stage", () => {
    const upToCollect = fixtureEvents.filter((e) => e.seq <= 9);
    const s = reduceAll(upToCollect);
    expect(s.counters.collected).toBe(5);
    expect(Object.keys(s.posts)).toHaveLength(5);
    expect(s.stage).toBe("collecting");
    expect(s.posts["local:fx-002"].post.text.title).toBe(
      "新加坡人在上海的第一周"
    );
  });

  it("marks pass-one drops and keeps counts", () => {
    const s = reduceAll(fixtureEvents.filter((e) => e.seq <= 15));
    expect(s.posts["local:fx-005"].state).toBe("dropped_pass_one");
    expect(s.posts["local:fx-001"].state).toBe("collected");
    expect(s.counters.pass_one_kept).toBe(4);
    expect(s.counters.jev_input_tokens).toBeGreaterThan(0);
  });

  it("sets latest and aggregates on judged", () => {
    const s = reduceAll(
      fixtureEvents.filter((e) => e.type !== "done" && e.seq <= 25)
    );
    expect(s.latest?.post.id).toBe("local:fx-004");
    expect(s.aggregates.hook_type.bold_claim).toBe(1);
    expect(s.aggregates.format.vlog_montage).toBe(2);
    expect(s.aggregates.persona_fit["4"]).toBeGreaterThanOrEqual(1);
    expect(s.counters.judged).toBe(4);
  });

  it("marks judge_failed on a judge error with post_id and counts errors", () => {
    const s = reduceAll(fixtureEvents.filter((e) => e.seq <= 26));
    expect(s.posts["local:fx-004"].state).toBe("judge_failed");
    expect(s.posts["local:fx-003"].state).toBe("judged");
    expect(s.counters.errors).toBe(1);
    expect(s.errors).toHaveLength(1);
  });

  it("applies selection", () => {
    const s = reduceAll(fixtureEvents.filter((e) => e.seq <= 28));
    expect(s.shortlist).toEqual(["local:fx-001", "local:fx-002"]);
    expect(s.posts["local:fx-001"].state).toBe("shortlisted");
    expect(s.posts["local:fx-003"].state).toBe("review");
    expect(s.counters.shortlisted).toBe(2);
    expect(s.counters.review).toBe(1);
  });

  it("takes counters from done and marks done", () => {
    const s = reduceAll(fixtureEvents);
    expect(s.done).toBe(true);
    expect(s.stage).toBe("done");
    expect(s.counters.elapsed_s).toBe(12.2);
    expect(s.counters.jev_cost_usd).toBeCloseTo(0.000_609, 6);
  });

  it("computes cost from tokens before done", () => {
    const s = reduceAll(fixtureEvents.filter((e) => e.seq <= 15));
    expect(s.counters.jev_cost_usd).toBeCloseTo(
      (s.counters.jev_input_tokens * 0.042) / 1_000_000,
      9
    );
  });

  it("ignores duplicate or older events (reconnect safety)", () => {
    const all = reduceAll(fixtureEvents);
    const first = fixtureEvents.filter((e) => e.seq <= 12);
    const rest = fixtureEvents.filter((e) => e.seq > 12);
    const resumed = [
      ...rest,
      ...fixtureEvents.filter((e) => e.seq <= 12),
    ].reduce(reduceEvent, reduceAll(first));
    expect(resumed).toEqual(all);
  });

  it("is pure", () => {
    const s0 = initialState();
    const s1 = reduceEvent(s0, fixtureEvents[0]);
    expect(s0).toEqual(initialState());
    expect(s1).not.toBe(s0);
  });

  it("never mutates its input state or event across the whole fixture", () => {
    const events = deepFreeze(structuredClone(fixtureEvents));
    let s: DashboardState = deepFreeze(initialState());
    for (const e of events) {
      s = deepFreeze(reduceEvent(s, e));
    }
    expect(s).toEqual(reduceAll(fixtureEvents));
  });

  it("resumes identically from every split point (reconnect with after=N)", () => {
    const all = JSON.stringify(reduceAll(fixtureEvents));
    for (let n = 0; n <= fixtureEvents.length; n += 1) {
      const head = reduceAll(fixtureEvents.filter((e) => e.seq <= n));
      const resumed = fixtureEvents
        .filter((e) => e.seq > n)
        .reduce(reduceEvent, head);
      expect(JSON.stringify(resumed)).toBe(all);
    }
  });

  it("returns the same state for an already-seen seq", () => {
    const s = reduceAll(fixtureEvents.filter((e) => e.seq <= 12));
    expect(reduceEvent(s, fixtureEvents[11])).toBe(s);
    expect(reduceEvent(s, fixtureEvents[3])).toBe(s);
  });

  it("keeps the Chinese caption on the tile", () => {
    const s = reduceAll(fixtureEvents);
    expect(s.posts["local:fx-002"].post.text.title).toBe(
      "新加坡人在上海的第一周"
    );
    expect(s.posts["local:fx-002"].post.text.caption).toBe(
      "从新加坡搬到上海的第一周，租房踩了三个坑。"
    );
  });

  it("leaves tiles alone for errors that are not judge errors on a post", () => {
    const before = reduceAll(fixtureEvents.filter((e) => e.seq <= 25));
    const s = [
      makeEvent(26, "error", "pass_two", {
        message: "ffmpeg failed",
        post_id: "local:fx-003",
        recoverable: true,
        where: "extract",
      }),
      makeEvent(27, "error", "pass_two", {
        message: "batch 429",
        recoverable: true,
        where: "judge",
      }),
      makeEvent(28, "error", "pass_two", {
        message: "null post",
        post_id: null,
        recoverable: true,
        where: "judge",
      }),
    ].reduce(reduceEvent, before);
    expect(s.posts).toEqual(before.posts);
    expect(s.counters.errors).toBe(3);
    expect(s.errors.map((e) => e.seq)).toEqual([26, 27, 28]);
  });

  it("marks only the named tile judge_failed for a judge_* error", () => {
    const before = reduceAll(fixtureEvents.filter((e) => e.seq <= 25));
    const s = reduceEvent(
      before,
      makeEvent(26, "error", "pass_two", {
        message: "timeout",
        post_id: "local:fx-002",
        recoverable: true,
        where: "judge_pass_two",
      })
    );
    expect(s.posts["local:fx-002"].state).toBe("judge_failed");
    for (const id of [
      "local:fx-001",
      "local:fx-003",
      "local:fx-004",
      "local:fx-005",
    ]) {
      expect(s.posts[id]).toBe(before.posts[id]);
    }
  });

  it("treats stage_changed to failed as terminal", () => {
    const before = reduceAll(fixtureEvents.filter((e) => e.seq <= 21));
    const s = reduceEvent(
      before,
      makeEvent(22, "stage_changed", "failed", {
        from: "pass_two",
        to: "failed",
      })
    );
    expect(s.stage).toBe("failed");
    expect(s.done).toBe(true);
    expect(before.done).toBe(false);
  });

  it("ignores unknown event types safely", () => {
    const before = reduceAll(fixtureEvents.filter((e) => e.seq <= 9));
    const s = reduceEvent(
      before,
      makeEvent(10, "something_new", "collecting", { anything: 1 })
    );
    expect(s.lastSeq).toBe(10);
    expect(s.posts).toBe(before.posts);
    expect(s.counters.collected).toBe(before.counters.collected);
  });
});

describe("fixtureEvents", () => {
  it("is a valid sequence: seq 1..N, strictly increasing ts, one run", () => {
    expect(fixtureEvents.length).toBeGreaterThanOrEqual(30);
    fixtureEvents.forEach((e, i) => {
      expect(e.seq).toBe(i + 1);
      expect(e.run_id).toBe("FIXTURE");
      if (i > 0) {
        expect(Date.parse(e.ts)).toBeGreaterThan(
          Date.parse(fixtureEvents[i - 1].ts)
        );
      }
    });
    expect(fixtureEvents[0].type).toBe("run_created");
    expect(fixtureEvents.at(-1)?.type).toBe("done");
  });

  it("pins the seq positions the reducer tests cut at", () => {
    const seqOf = (type: string) =>
      fixtureEvents.filter((e) => e.type === type).map((e) => e.seq);
    expect(seqOf("post_collected")).toEqual([5, 6, 7, 8, 9]);
    expect(seqOf("pass_one_judged")).toEqual([11, 12, 13, 14, 15]);
    expect(seqOf("judged")).toEqual([22, 23, 24, 25]);
    expect(seqOf("error")).toEqual([26]);
    expect(seqOf("selected")).toEqual([28]);
  });

  it("is deterministic and matches the generated run-events.json", () => {
    expect(buildFixtureEvents()).toEqual(fixtureEvents);
    expect(fixtureJson).toEqual(fixtureEvents);
  });
});

describe("answersPerSecond", () => {
  it("counts answers in the trailing window", () => {
    const judged = fixtureEvents.filter((e) => e.type === "judged");
    const rate = answersPerSecond(judged, 5000);
    expect(rate).toBeCloseTo((4 * 7) / 5, 3);
  });
  it("returns 0 with no events", () => {
    expect(answersPerSecond([])).toBe(0);
  });
});

describe("readyPlan", () => {
  it("is null until a plan_ready arrives, then that event's plan", () => {
    expect(readyPlan([])).toBeNull();
    expect(readyPlan(fixtureEvents.slice(0, 1))).toBeNull();
    const plan = readyPlan(fixtureEvents);
    expect(plan?.queries).toEqual([
      { lang: "en", platform: "local", query: "shanghai" },
    ]);
    expect(plan?.persona_fit_criteria).toHaveLength(5);
  });

  it("takes the latest plan_ready and ignores one without a plan", () => {
    const [, first] = fixtureEvents;
    const later = makeEvent(40, "plan_ready", "planning", {
      plan: { ...(first.payload.plan as object), rubric_pack: "other" },
    });
    expect(readyPlan([first, later])?.rubric_pack).toBe("other");
    const empty = makeEvent(41, "plan_ready", "planning", { plan: null });
    expect(readyPlan([first, empty])?.rubric_pack).toBe("creator-hooks-v1");
  });
});
