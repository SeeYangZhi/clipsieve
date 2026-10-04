import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fixtureEvents } from "@/lib/__fixtures__/run-events";
import { ApiError } from "@/lib/api";
import { type DashboardState, reduceAll } from "@/lib/events";
import { setLocale } from "@/lib/i18n";
import type { Plan, Run, RunEvent } from "@/lib/types";
import RunPage from "./page";

const mocks = vi.hoisted(() => ({
  events: [] as unknown[],
  getRun: vi.fn(),
  pauseRun: vi.fn(),
  resumeRun: vi.fn(),
  state: null as unknown,
  toastError: vi.fn(),
  useRunEvents: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "run 1" }),
}));
vi.mock("sonner", () => ({ toast: { error: mocks.toastError } }));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api: {
    getRun: mocks.getRun,
    pauseRun: mocks.pauseRun,
    resumeRun: mocks.resumeRun,
  },
}));
vi.mock("@/lib/useRunEvents", () => ({
  useRunEvents: (id: string, opts: unknown) => {
    mocks.useRunEvents(id, opts);
    return {
      connected: true,
      events: mocks.events,
      progress: 0,
      state: mocks.state,
    };
  },
}));

const midEvents = fixtureEvents.filter((e) => e.seq <= 23);
const run = {
  id: "run 1",
  paused: false,
  quantities: { local: 5 },
  stage: "pass_two",
} as unknown as Run;
const plan = { quantities: { local: 6, youtube: 2 } } as unknown as Plan;

function live(events: RunEvent[]) {
  mocks.events = events;
  mocks.state = reduceAll(events) satisfies DashboardState;
}

beforeEach(() => {
  live(midEvents);
  for (const fn of [
    mocks.getRun,
    mocks.pauseRun,
    mocks.resumeRun,
    mocks.toastError,
    mocks.useRunEvents,
  ]) {
    fn.mockReset();
  }
});
afterEach(() => {
  act(() => setLocale("en"));
});

describe("RunPage", () => {
  it("tails the run live and counts against the plan's quantities", async () => {
    mocks.getRun.mockResolvedValue({ plan, run });
    render(<RunPage />);
    expect(mocks.useRunEvents).toHaveBeenCalledWith("run 1", { mode: "live" });
    expect(mocks.getRun).toHaveBeenCalledWith("run 1");
    expect(await screen.findByText("5 / 8")).toBeInTheDocument();
    expect(screen.getByText("Pass two")).toBeInTheDocument();
  });

  it("pauses and resumes through the API, showing the intent before the server agrees", async () => {
    // The real API answers a pause with `paused` still false (the pipeline pauses
    // cooperatively) and a resume while busy with `paused` still true; the run only
    // reaches the requested state a little later, which GET /runs/{id} then shows.
    let server: Run = run;
    mocks.getRun.mockImplementation(async () => ({ plan, run: server }));
    mocks.pauseRun.mockImplementation(() => {
      const before = server;
      server = { ...server, paused: true };
      return Promise.resolve(before);
    });
    mocks.resumeRun.mockImplementation(() => {
      const before = server;
      server = { ...server, paused: false };
      return Promise.resolve(before);
    });
    render(<RunPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Pause" }));
    expect(mocks.pauseRun).toHaveBeenCalledWith("run 1");
    expect(
      await screen.findByRole("button", { name: "Resume" })
    ).toBeInTheDocument();
    // It re-polls the run until the server reports the requested state.
    await waitFor(
      () => expect(mocks.getRun.mock.calls.length).toBeGreaterThan(1),
      {
        timeout: 2000,
      }
    );
    expect(screen.getByRole("button", { name: "Resume" })).toBeInTheDocument();

    const polls = mocks.getRun.mock.calls.length;
    await userEvent.click(screen.getByRole("button", { name: "Resume" }));
    expect(mocks.resumeRun).toHaveBeenCalledWith("run 1");
    expect(
      await screen.findByRole("button", { name: "Pause" })
    ).toBeInTheDocument();
    await waitFor(
      () => expect(mocks.getRun.mock.calls.length).toBeGreaterThan(polls),
      { timeout: 2000 }
    );
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();
  });

  it("shows the failure message of a failed run", async () => {
    live(fixtureEvents);
    mocks.getRun.mockResolvedValue({
      plan,
      run: { ...run, error: "explain backend exited 1", stage: "failed" },
    });
    mocks.state = {
      ...(reduceAll(fixtureEvents) as DashboardState),
      done: true,
      errors: [],
      stage: "failed",
    };
    render(<RunPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "explain backend exited 1"
    );
  });

  it("toasts the API detail when pausing fails", async () => {
    mocks.getRun.mockResolvedValue({ plan, run });
    mocks.pauseRun.mockRejectedValue(new ApiError(409, "run is not running"));
    render(<RunPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Pause" }));
    await waitFor(() =>
      expect(mocks.toastError).toHaveBeenCalledWith("run is not running")
    );
    expect(screen.getByRole("button", { name: "Pause" })).toBeEnabled();
  });

  it("links to the encoded report and hides pause once done", async () => {
    live(fixtureEvents);
    mocks.getRun.mockResolvedValue({ plan, run: { ...run, stage: "done" } });
    render(<RunPage />);
    expect(
      await screen.findByRole("link", { name: "View report" })
    ).toHaveAttribute("href", "/runs/run%201/report");
    expect(
      screen.queryByRole("button", { name: "Pause" })
    ).not.toBeInTheDocument();
  });

  it("still shows the live dashboard when the run cannot be loaded", async () => {
    mocks.getRun.mockRejectedValue(new ApiError(404, "run not found"));
    render(<RunPage />);
    await waitFor(() =>
      expect(mocks.toastError).toHaveBeenCalledWith("run not found")
    );
    expect(screen.getByText("5 / 5")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Pause" })
    ).not.toBeInTheDocument();
  });

  it("switches locale without refetching the run", async () => {
    mocks.getRun.mockResolvedValue({ plan, run });
    render(<RunPage />);
    await screen.findByRole("button", { name: "Pause" });
    act(() => setLocale("zh"));
    expect(screen.getByRole("button", { name: "暂停" })).toBeInTheDocument();
    expect(screen.getByText("第二轮")).toBeInTheDocument();
    expect(mocks.getRun).toHaveBeenCalledTimes(1);
  });
});
