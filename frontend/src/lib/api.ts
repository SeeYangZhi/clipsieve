import type { JudgeResult, Plan, Post, Report, Run } from "./types";

export const API_BASE = "/api";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export interface CreateRunBody {
  brief: string;
  language_hint?: string;
  platforms: string[];
  quantities: Record<string, number>;
  rubric_pack: string;
}

export type PostState =
  | "collected"
  | "dropped_pass_one"
  | "judged"
  | "shortlisted"
  | "review"
  | "judge_failed";

export interface PostView {
  composite?: number;
  judge: Record<string, JudgeResult>;
  post: Post;
  state: PostState;
}

export interface Selection {
  dropped: Record<string, string>;
  review: string[];
  scores: Record<string, number>;
  shortlist: string[];
}

export interface AdapterStatus {
  healthy: boolean;
  message: string;
  platform: string;
}
export interface RubricPackSummary {
  description: string;
  name: string;
  question_ids: string[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown } | null;
      const raw = body?.detail;
      if (typeof raw === "string") {
        detail = raw;
      }
    } catch {
      // non-JSON error body
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

const enc = encodeURIComponent;

export const api = {
  approveRun: (id: string) =>
    request<Run>(`/runs/${enc(id)}/approve`, { method: "POST" }),
  createRun: (body: CreateRunBody) =>
    request<Run>("/runs", { body: JSON.stringify(body), method: "POST" }),
  getPosts: (id: string, offset = 0, limit = 100) =>
    request<{ items: PostView[]; total: number }>(
      `/runs/${enc(id)}/posts?offset=${offset}&limit=${limit}`
    ),
  getReport: (id: string) => request<Report>(`/runs/${enc(id)}/report`),
  getRun: (id: string) =>
    request<{ run: Run; plan: Plan | null }>(`/runs/${enc(id)}`),
  listAdapters: () => request<AdapterStatus[]>("/adapters"),
  listRubrics: () => request<RubricPackSummary[]>("/rubrics"),
  listRuns: () => request<Run[]>("/runs"),
  pauseRun: (id: string) =>
    request<Run>(`/runs/${enc(id)}/pause`, { method: "POST" }),
  reselect: (id: string, weights: Record<string, number>) =>
    request<Selection>(`/runs/${enc(id)}/reselect`, {
      body: JSON.stringify({ weights }),
      method: "POST",
    }),
  resumeRun: (id: string) =>
    request<Run>(`/runs/${enc(id)}/resume`, { method: "POST" }),
  savePlan: (id: string, plan: Plan) =>
    request<Plan>(`/runs/${enc(id)}/plan`, {
      body: JSON.stringify(plan),
      method: "PUT",
    }),
};

export function mediaUrl(
  runId: string,
  postId: string,
  filename: string
): string {
  return `${API_BASE}/runs/${enc(runId)}/media/${enc(postId)}/${enc(filename)}`;
}

export function eventsUrl(runId: string, after: number): string {
  return `${API_BASE}/runs/${enc(runId)}/events?after=${after}`;
}
