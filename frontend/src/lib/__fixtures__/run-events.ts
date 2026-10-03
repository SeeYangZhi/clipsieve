import type { JudgeResult, RunEvent, Stage } from "@/lib/types";
import { fixturePosts } from "./posts";

const RUN_ID = "FIXTURE";
const T0 = Date.parse("2026-10-03T10:00:00Z");

let seq = 0;
function ev(
  offsetMs: number,
  type: RunEvent["type"],
  stage: Stage,
  payload: Record<string, unknown>
): RunEvent {
  seq += 1;
  return {
    payload,
    run_id: RUN_ID,
    seq,
    stage,
    ts: new Date(T0 + offsetMs).toISOString(),
    type,
  };
}

const hookTypes = ["bold_claim", "problem", "story", "result_first", "none"];
const formats = [
  "talking_head",
  "vlog_montage",
  "vlog_montage",
  "image_carousel",
  "image_carousel",
];

function passOne(postId: string, i: number): JudgeResult {
  return {
    answers: {
      format_guess: {
        confidence: 0.5,
        probabilities: {
          image_carousel: 0.3,
          talking_head: 0.1,
          vlog_montage: 0.6,
        },
        type: "choice",
        value:
          formats[i] === "image_carousel" ? "image_carousel" : "vlog_montage",
      },
      niche_relevance: {
        confidence: 0.7,
        legend: {
          "1": "Unrelated",
          "2": "Mentions in passing",
          "3": "Partly about it",
          "4": "Mainly about it",
          "5": "Entirely about it",
        },
        probabilities: { "1": 0, "2": 0.1, "3": 0.3, "4": 0.5, "5": 0.1 },
        type: "score",
        value: 3.2 + (i % 2) * 0.6,
      },
    },
    input_tokens: 900 + i * 10,
    latency_ms: 120,
    model: "jev-1.13.0",
    pass_name: "pass_one",
    post_id: postId,
  };
}

function passTwo(postId: string, i: number): JudgeResult {
  return {
    answers: {
      format: {
        confidence: 0.9,
        probabilities: { [formats[i]]: 0.9 },
        type: "choice",
        value: formats[i],
      },
      format_guess: passOne(postId, i).answers.format_guess,
      hook_strength: {
        confidence: 0.8,
        legend: {
          "1": "No hook",
          "2": "Weak",
          "3": "Moderate",
          "4": "Strong",
          "5": "Exceptional",
        },
        probabilities: { "3": 0.6, "4": 0.4 },
        type: "score",
        value: 2.0 + i * 0.5,
      },
      hook_type: {
        confidence: 0.75,
        probabilities: { [hookTypes[i]]: 0.75, none: 0.25 },
        type: "choice",
        value: hookTypes[i],
      },
      niche_relevance: passOne(postId, i).answers.niche_relevance,
      persona_fit: {
        confidence: i === 2 ? 0.3 : 0.8,
        legend: {
          "1": "Unrelated",
          "2": "Adjacent niche",
          "3": "Same niche, different voice",
          "4": "Close match",
          "5": "Could be the user's own channel",
        },
        probabilities: { "3": 0.3, "4": 0.7 },
        type: "score",
        value: i === 4 ? 1.4 : 3.6 + (i % 2) * 0.3,
      },
      risky_claim: { type: "noul", value: 0.05 },
    },
    input_tokens: 2400 + i * 50,
    latency_ms: 380,
    model: "jev-1.13.0",
    pass_name: "pass_two",
    post_id: postId,
  };
}

export function buildFixtureEvents(): RunEvent[] {
  seq = 0;
  const brief = {
    audience: "Singaporeans relocating",
    persona: "friendly expat vlogger",
    text: "Singaporean moving to Shanghai, vlog style",
    topic: "moving to Shanghai",
  };
  const plan = {
    brief,
    persona_fit_criteria: [
      "Unrelated",
      "Adjacent niche",
      "Same niche, different voice",
      "Close match",
      "Could be the user's own channel",
    ],
    quantities: { local: 5 },
    queries: [{ lang: "en", platform: "local", query: "shanghai" }],
    rubric_pack: "creator-hooks-v1",
    run_id: RUN_ID,
  };
  const out: RunEvent[] = [];
  out.push(
    ev(0, "run_created", "planning", {
      brief,
      platforms: ["local"],
      quantities: { local: 5 },
    })
  );
  out.push(ev(500, "plan_ready", "planning", { plan }));
  out.push(ev(1500, "plan_approved", "planning", { plan }));
  out.push(
    ev(1600, "stage_changed", "collecting", {
      from: "planning",
      to: "collecting",
    })
  );
  for (const [i, post] of fixturePosts.entries()) {
    out.push(ev(2000 + i * 200, "post_collected", "collecting", { post }));
  }
  out.push(
    ev(3200, "stage_changed", "pass_one", {
      from: "collecting",
      to: "pass_one",
    })
  );
  for (const [i, post] of fixturePosts.entries()) {
    const kept = i !== 4;
    out.push(
      ev(3400 + i * 150, "pass_one_judged", "pass_one", {
        composite: kept ? 0.7 : 0.2,
        judge: passOne(post.id, i),
        kept,
      })
    );
  }
  out.push(
    ev(4300, "stage_changed", "extracting", {
      from: "pass_one",
      to: "extracting",
    })
  );
  for (const [i, post] of fixturePosts.slice(0, 4).entries()) {
    out.push(
      ev(4500 + i * 400, "evidence_ready", "extracting", {
        evidence: {
          comment_summary: {
            count: post.comments.length,
            sample: post.comments.map((c) => c.text),
            top_terms: [],
          },
          keyframes: [],
          ocr: [],
          post_id: post.id,
          token_estimate: 400,
          transcript: [
            { end_s: 2.5, start_s: 0, text: post.text.caption ?? "" },
          ],
          truncated: false,
        },
        post_id: post.id,
      })
    );
  }
  out.push(
    ev(6200, "stage_changed", "pass_two", {
      from: "extracting",
      to: "pass_two",
    })
  );
  for (const [i, post] of fixturePosts.slice(0, 4).entries()) {
    out.push(
      ev(6400 + i * 300, "judged", "pass_two", {
        composite: 0.55 + i * 0.1,
        judge: passTwo(post.id, i),
      })
    );
  }
  out.push(
    ev(7700, "error", "pass_two", {
      message: "429 after 5 retries",
      post_id: "local:fx-004",
      recoverable: true,
      where: "judge",
    })
  );
  out.push(
    ev(7800, "stage_changed", "selecting", {
      from: "pass_two",
      to: "selecting",
    })
  );
  out.push(
    ev(7900, "selected", "selecting", {
      dropped: { "local:fx-004": "judge_failed", "local:fx-005": "pass_one" },
      review: ["local:fx-003"],
      scores: {
        "local:fx-001": 0.55,
        "local:fx-002": 0.65,
        "local:fx-003": 0.75,
      },
      shortlist: ["local:fx-001", "local:fx-002"],
    })
  );
  out.push(
    ev(8000, "stage_changed", "explaining", {
      from: "selecting",
      to: "explaining",
    })
  );
  out.push(
    ev(12_000, "explained", "explaining", {
      report: {
        caveats: ["Only five posts in this fixture run."],
        clips: [
          {
            hook_quote: "租房踩了三个坑",
            post_id: "local:fx-002",
            weaknesses: "No visual hook.",
            why_it_works: "Three concrete mistakes promised in the first line.",
          },
        ],
        concepts: [
          {
            cta: "save for later",
            hook: "I signed a Shanghai lease without reading this",
            inspired_by_post_ids: ["local:fx-002"],
            proof: "contract screenshot",
            structure: "problem, three mistakes, fix",
            visual: "walk-through",
          },
        ],
        gaps: [],
        patterns: [
          {
            hypothesis: "Specific friction signals authenticity.",
            observation: "Both shortlisted clips open on a concrete pain.",
            post_ids: ["local:fx-001", "local:fx-002"],
            title: "Problem-first openings",
          },
        ],
        run_id: RUN_ID,
      },
    })
  );
  out.push(
    ev(12_100, "stage_changed", "done", { from: "explaining", to: "done" })
  );
  out.push(
    ev(12_200, "done", "done", {
      counters: {
        collected: 5,
        elapsed_s: 12.2,
        errors: 1,
        jev_cost_usd: 0.000_609,
        jev_input_tokens: 14_500,
        judged: 4,
        pass_one_kept: 4,
        review: 1,
        shortlisted: 2,
      },
    })
  );
  return out;
}

export const fixtureEvents: RunEvent[] = buildFixtureEvents();
