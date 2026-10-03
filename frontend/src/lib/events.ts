import type { Counters, JudgeResult, Post, RunEvent, Stage } from "./types";

export const JEV_USD_PER_MILLION_INPUT = 0.042;

export type PostTileState =
  | "collected"
  | "dropped_pass_one"
  | "judged"
  | "shortlisted"
  | "review"
  | "judge_failed";

export interface PostTile {
  composite?: number;
  post: Post;
  state: PostTileState;
}

export interface DashboardState {
  /** question id -> answer label (choice) or rounded level (persona_fit) -> count */
  aggregates: Record<string, Record<string, number>>;
  counters: Counters;
  done: boolean;
  errors: RunEvent[];
  /** seq of the last applied event; events with seq <= lastSeq are ignored */
  lastSeq: number;
  latest: { composite: number; judge: JudgeResult; post: Post } | null;
  posts: Record<string, PostTile>;
  review: string[];
  shortlist: string[];
  stage: Stage;
  /** ts of the first applied event; elapsed_s is measured from it until done */
  startedAt: string | null;
}

type Payload = RunEvent["payload"];
type Aggregates = DashboardState["aggregates"];

export function emptyCounters(): Counters {
  return {
    collected: 0,
    elapsed_s: 0,
    errors: 0,
    jev_cost_usd: 0,
    jev_input_tokens: 0,
    judged: 0,
    pass_one_kept: 0,
    review: 0,
    shortlisted: 0,
  };
}

export function initialState(): DashboardState {
  return {
    aggregates: {},
    counters: emptyCounters(),
    done: false,
    errors: [],
    lastSeq: 0,
    latest: null,
    posts: {},
    review: [],
    shortlist: [],
    stage: "planning",
    startedAt: null,
  };
}

function bump(agg: Aggregates, qid: string, label: string): Aggregates {
  const row = { ...(agg[qid] ?? {}) };
  row[label] = (row[label] ?? 0) + 1;
  return { ...agg, [qid]: row };
}

function aggregate(agg: Aggregates, judge: JudgeResult): Aggregates {
  let out = agg;
  for (const [qid, a] of Object.entries(judge.answers)) {
    if (a.type === "choice") {
      out = bump(out, qid, String(a.value));
    } else if (qid === "persona_fit" && a.type === "score") {
      out = bump(out, qid, String(Math.round(Number(a.value))));
    }
  }
  return out;
}

function setTile(
  posts: Record<string, PostTile>,
  id: string,
  patch: Partial<PostTile>
): Record<string, PostTile> {
  const tile = posts[id];
  if (!tile) {
    return posts;
  }
  return { ...posts, [id]: { ...tile, ...patch } };
}

function addTokens(counters: Counters, tokens: number): Counters {
  const total = counters.jev_input_tokens + tokens;
  return {
    ...counters,
    jev_cost_usd: (total * JEV_USD_PER_MILLION_INPUT) / 1_000_000,
    jev_input_tokens: total,
  };
}

function onPostCollected(s: DashboardState, p: Payload): DashboardState {
  const post = p.post as Post;
  return {
    ...s,
    counters: { ...s.counters, collected: s.counters.collected + 1 },
    posts: { ...s.posts, [post.id]: { post, state: "collected" } },
  };
}

function onPassOneJudged(s: DashboardState, p: Payload): DashboardState {
  const judge = p.judge as JudgeResult;
  const kept = Boolean(p.kept);
  const counters = {
    ...s.counters,
    pass_one_kept: s.counters.pass_one_kept + (kept ? 1 : 0),
  };
  return {
    ...s,
    counters: addTokens(counters, judge.input_tokens),
    posts: setTile(s.posts, judge.post_id, {
      composite: Number(p.composite),
      state: kept ? "collected" : "dropped_pass_one",
    }),
  };
}

function onJudged(s: DashboardState, p: Payload): DashboardState {
  const judge = p.judge as JudgeResult;
  const composite = Number(p.composite);
  const posts = setTile(s.posts, judge.post_id, { composite, state: "judged" });
  const tile = posts[judge.post_id];
  const counters = { ...s.counters, judged: s.counters.judged + 1 };
  return {
    ...s,
    aggregates: aggregate(s.aggregates, judge),
    counters: addTokens(counters, judge.input_tokens),
    latest: tile ? { composite, judge, post: tile.post } : s.latest,
    posts,
  };
}

function onSelected(s: DashboardState, p: Payload): DashboardState {
  const shortlist = p.shortlist as string[];
  const review = p.review as string[];
  let { posts } = s;
  for (const id of shortlist) {
    posts = setTile(posts, id, { state: "shortlisted" });
  }
  for (const id of review) {
    posts = setTile(posts, id, { state: "review" });
  }
  return {
    ...s,
    counters: {
      ...s.counters,
      review: review.length,
      shortlisted: shortlist.length,
    },
    posts,
    review,
    shortlist,
  };
}

function onError(
  s: DashboardState,
  p: Payload,
  event: RunEvent
): DashboardState {
  // post_id is optional: absent on the wire, null treated as absent.
  const postId = typeof p.post_id === "string" ? p.post_id : null;
  const judgeFailure =
    postId !== null &&
    typeof p.where === "string" &&
    p.where.startsWith("judge");
  return {
    ...s,
    counters: { ...s.counters, errors: s.counters.errors + 1 },
    errors: [...s.errors, event],
    posts: judgeFailure
      ? setTile(s.posts, postId, { state: "judge_failed" })
      : s.posts,
  };
}

function onStageChanged(s: DashboardState, p: Payload): DashboardState {
  const stage = p.to as Stage;
  return { ...s, done: s.done || stage === "failed", stage };
}

/**
 * Pure: never mutates `state` or `event`. Returns `state` itself (same
 * reference) for an event already applied (seq <= lastSeq), so a reconnect
 * that replays events yields the same state as an uninterrupted stream.
 * Unknown event types only advance lastSeq, stage and elapsed time.
 */
export function reduceEvent(
  state: DashboardState,
  event: RunEvent
): DashboardState {
  if (event.seq <= state.lastSeq) {
    return state;
  }
  const startedAt = state.startedAt ?? event.ts;
  const next: DashboardState = {
    ...state,
    counters: {
      ...state.counters,
      elapsed_s: (Date.parse(event.ts) - Date.parse(startedAt)) / 1000,
    },
    lastSeq: event.seq,
    stage: event.stage,
    startedAt,
  };
  const p = event.payload;
  switch (event.type) {
    case "post_collected":
      return onPostCollected(next, p);
    case "pass_one_judged":
      return onPassOneJudged(next, p);
    case "judged":
      return onJudged(next, p);
    case "selected":
      return onSelected(next, p);
    case "error":
      return onError(next, p, event);
    case "stage_changed":
      return onStageChanged(next, p);
    case "done":
      // The backend's final counters are authoritative.
      return { ...next, counters: { ...(p.counters as Counters) }, done: true };
    default:
      // run_created, plan_ready, plan_approved, evidence_ready, explained and
      // unknown types carry nothing the dashboard state tracks.
      return next;
  }
}

export function reduceAll(events: RunEvent[]): DashboardState {
  return events.reduce(reduceEvent, initialState());
}

/** Judge answers per second over the `windowMs` before the last event's ts. */
export function answersPerSecond(events: RunEvent[], windowMs = 5000): number {
  const last = events.at(-1);
  if (!last || windowMs <= 0) {
    return 0;
  }
  const end = Date.parse(last.ts);
  let answers = 0;
  for (const e of events) {
    if (e.type !== "judged" && e.type !== "pass_one_judged") {
      continue;
    }
    if (end - Date.parse(e.ts) <= windowMs) {
      const { judge } = e.payload as { judge: JudgeResult };
      answers += Object.keys(judge.answers).length;
    }
  }
  return answers / (windowMs / 1000);
}
