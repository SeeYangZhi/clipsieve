import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { setLocale } from "@/lib/i18n";
import type { Plan, Run, RunEvent } from "@/lib/types";
import PlanPage from "./page";

const mocks = vi.hoisted(() => ({
  approveRun: vi.fn(),
  events: [] as unknown[],
  getRun: vi.fn(),
  push: vi.fn(),
  savePlan: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
  useRunEvents: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "run 1" }),
  useRouter: () => ({ push: mocks.push }),
}));
vi.mock("sonner", () => ({
  toast: { error: mocks.toastError, success: mocks.toastSuccess },
}));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api: {
    approveRun: mocks.approveRun,
    getRun: mocks.getRun,
    savePlan: mocks.savePlan,
  },
}));
vi.mock("@/lib/useRunEvents", () => ({
  useRunEvents: (id: string, opts: unknown) => {
    mocks.useRunEvents(id, opts);
    return { connected: true, events: mocks.events, progress: 0 };
  },
}));

const plan: Plan = {
  brief: {
    audience: "Singaporeans relocating",
    persona: "friendly expat vlogger",
    text: "Singaporean in Shanghai vlog",
    topic: "moving to Shanghai",
  },
  persona_fit_criteria: [
    "Unrelated",
    "Adjacent niche",
    "Same niche, different voice",
    "Close match",
    "Could be the user's own channel",
  ],
  quantities: { xiaohongshu: 500, youtube: 500 },
  queries: [
    { lang: "en", platform: "youtube", query: "Singaporean in Shanghai vlog" },
    { lang: "zh", platform: "xiaohongshu", query: "新加坡人 上海 生活 vlog" },
  ],
  rubric_pack: "creator-hooks-v1",
  run_id: "run 1",
};
const run = { id: "run 1", stage: "planning" } as Run;

function planReady(p: Plan): RunEvent {
  return {
    payload: { plan: p },
    run_id: "run 1",
    seq: 2,
    stage: "planning",
    ts: "2026-10-03T10:00:01Z",
    type: "plan_ready",
  };
}

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

beforeEach(() => {
  mocks.events = [];
  for (const fn of [
    mocks.approveRun,
    mocks.getRun,
    mocks.push,
    mocks.savePlan,
    mocks.toastError,
    mocks.toastSuccess,
    mocks.useRunEvents,
  ]) {
    fn.mockReset();
  }
});
afterEach(() => {
  act(() => setLocale("en"));
});

describe("PlanPage", () => {
  it("tails the run live and waits for plan_ready while planning", async () => {
    mocks.getRun.mockResolvedValue({ plan: null, run });
    const { rerender } = render(<PlanPage />);
    expect(mocks.useRunEvents).toHaveBeenCalledWith("run 1", { mode: "live" });
    expect(
      await screen.findByText("Claude is turning your brief into a plan…")
    ).toBeInTheDocument();
    mocks.events = [planReady(plan)];
    rerender(<PlanPage />);
    expect(
      screen.getByDisplayValue("新加坡人 上海 生活 vlog")
    ).toBeInTheDocument();
    expect(mocks.getRun).toHaveBeenCalledTimes(1);
    expect(mocks.getRun).toHaveBeenCalledWith("run 1");
  });

  it("shows the stored plan, not the planner's original from the log", async () => {
    const stored = deferred<{ plan: Plan; run: Run }>();
    mocks.getRun.mockReturnValue(stored.promise);
    mocks.events = [planReady(plan)];
    render(<PlanPage />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    const edited = {
      ...plan,
      queries: [
        { lang: "zh", platform: "xiaohongshu", query: "新加坡人 搬到上海" },
      ],
    };
    await act(async () => stored.resolve({ plan: edited, run }));
    expect(screen.getByDisplayValue("新加坡人 搬到上海")).toBeInTheDocument();
    expect(
      screen.queryByDisplayValue("新加坡人 上海 生活 vlog")
    ).not.toBeInTheDocument();
  });

  it("saves, then approves, then opens the encoded dashboard", async () => {
    mocks.getRun.mockResolvedValue({ plan, run });
    mocks.savePlan.mockResolvedValue(plan);
    mocks.approveRun.mockResolvedValue(run);
    render(<PlanPage />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Approve and run" })
    );
    await waitFor(() =>
      expect(mocks.push).toHaveBeenCalledWith("/runs/run%201")
    );
    expect(mocks.savePlan).toHaveBeenCalledWith("run 1", plan);
    expect(mocks.approveRun).toHaveBeenCalledWith("run 1");
    expect(mocks.savePlan.mock.invocationCallOrder[0]).toBeLessThan(
      mocks.approveRun.mock.invocationCallOrder[0]
    );
  });

  it("reports a refused approval and lets the user try again", async () => {
    mocks.getRun.mockResolvedValue({ plan, run });
    mocks.savePlan.mockResolvedValue(plan);
    mocks.approveRun.mockRejectedValue(
      new ApiError(409, "run already approved")
    );
    render(<PlanPage />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Approve and run" })
    );
    await waitFor(() =>
      expect(mocks.toastError).toHaveBeenCalledWith("run already approved")
    );
    expect(
      screen.getByRole("button", { name: "Approve and run" })
    ).toBeEnabled();
    expect(mocks.push).not.toHaveBeenCalled();
  });

  it("saves the plan and confirms", async () => {
    mocks.getRun.mockResolvedValue({ plan, run });
    mocks.savePlan.mockResolvedValue(plan);
    render(<PlanPage />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Save plan" })
    );
    await waitFor(() =>
      expect(mocks.toastSuccess).toHaveBeenCalledWith("Plan saved")
    );
    expect(mocks.savePlan).toHaveBeenCalledWith("run 1", plan);
  });

  it("offers a retry when the run cannot be loaded", async () => {
    mocks.getRun.mockRejectedValueOnce(new ApiError(404, "run not found"));
    mocks.getRun.mockResolvedValueOnce({ plan, run });
    render(<PlanPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("run not found");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(
      await screen.findByDisplayValue("新加坡人 上海 生活 vlog")
    ).toBeInTheDocument();
    expect(mocks.getRun).toHaveBeenCalledTimes(2);
  });

  it("switches language without refetching", async () => {
    mocks.getRun.mockResolvedValue({ plan, run });
    render(<PlanPage />);
    await screen.findByRole("button", { name: "Approve and run" });
    act(() => setLocale("zh"));
    expect(
      screen.getByRole("button", { name: "批准并运行" })
    ).toBeInTheDocument();
    expect(mocks.getRun).toHaveBeenCalledTimes(1);
  });
});
