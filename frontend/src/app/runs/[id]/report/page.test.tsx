import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fixturePosts } from "@/lib/__fixtures__/posts";
import { fixtureEvents } from "@/lib/__fixtures__/run-events";
import { ApiError, type PostView } from "@/lib/api";
import { setLocale } from "@/lib/i18n";
import type { Report, RunEvent } from "@/lib/types";
import ReportPage from "./page";

const mocks = vi.hoisted(() => ({
  getPosts: vi.fn(),
  getReport: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "run 1" }),
}));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api: { getPosts: mocks.getPosts, getReport: mocks.getReport },
}));

const explained = fixtureEvents.find((e) => e.type === "explained") as RunEvent;
const { report } = explained.payload as { report: Report };
const views: PostView[] = fixturePosts
  .slice(0, 2)
  .map((p) => ({ judge: {}, post: p, state: "shortlisted" }));

beforeEach(() => {
  mocks.getPosts.mockReset();
  mocks.getReport.mockReset();
});
afterEach(() => {
  act(() => setLocale("en"));
});

describe("ReportPage", () => {
  it("says the report is not ready on 404 and links back to the run", async () => {
    mocks.getReport.mockRejectedValue(new ApiError(404, "report not found"));
    act(() => setLocale("zh"));
    render(<ReportPage />);
    expect(screen.getByText("正在加载报告…")).toBeInTheDocument();
    expect(await screen.findByText("报告还没有准备好")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "返回任务" })).toHaveAttribute(
      "href",
      "/runs/run%201"
    );
    expect(mocks.getReport).toHaveBeenCalledWith("run 1");
    expect(mocks.getPosts).not.toHaveBeenCalled();
  });

  it("pages through every post so each citation resolves", async () => {
    mocks.getReport.mockResolvedValue(report);
    mocks.getPosts
      .mockResolvedValueOnce({ items: [views[0]], total: 2 })
      .mockResolvedValueOnce({ items: [views[1]], total: 2 });
    render(<ReportPage />);
    expect(
      await screen.findByText("Problem-first openings")
    ).toBeInTheDocument();
    expect(mocks.getPosts).toHaveBeenNthCalledWith(1, "run 1", 0, 500);
    expect(mocks.getPosts).toHaveBeenNthCalledWith(2, "run 1", 1, 500);
    expect(mocks.getPosts).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: "local:fx-001" })).toBeEnabled();
    for (const btn of screen.getAllByRole("button", { name: "local:fx-002" })) {
      expect(btn).toBeEnabled();
    }
    expect(
      screen.getByRole("link", { name: "Back to the run" })
    ).toHaveAttribute("href", "/runs/run%201");
  });

  it("shows the API error and retries", async () => {
    mocks.getReport
      .mockRejectedValueOnce(new ApiError(500, "explain backend crashed"))
      .mockResolvedValueOnce(report);
    mocks.getPosts.mockResolvedValue({ items: views, total: 2 });
    render(<ReportPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "explain backend crashed"
    );
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(
      await screen.findByText("Problem-first openings")
    ).toBeInTheDocument();
    expect(mocks.getReport).toHaveBeenCalledTimes(2);
  });
});
