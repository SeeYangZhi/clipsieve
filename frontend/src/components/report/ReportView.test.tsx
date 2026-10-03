import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { fixturePosts } from "@/lib/__fixtures__/posts";
import { fixtureEvents } from "@/lib/__fixtures__/run-events";
import type { PostView } from "@/lib/api";
import { setLocale } from "@/lib/i18n";
import type { JudgeResult, Report, RunEvent } from "@/lib/types";
import { ReportView } from "./ReportView";

const explained = fixtureEvents.find((e) => e.type === "explained") as RunEvent;
const { report } = explained.payload as { report: Report };
const posts: Record<string, PostView> = Object.fromEntries(
  fixturePosts
    .slice(0, 2)
    .map((p) => [p.id, { judge: {}, post: p, state: "shortlisted" as const }])
);

afterEach(() => {
  act(() => setLocale("en"));
});

describe("ReportView", () => {
  it("renders sections and opens a post dialog from a citation", async () => {
    render(<ReportView posts={posts} report={report} />);
    expect(screen.getByText("Patterns")).toBeInTheDocument();
    expect(screen.getByText("Problem-first openings")).toBeInTheDocument();
    expect(screen.getByText("租房踩了三个坑")).toBeInTheDocument();
    await userEvent.click(
      screen.getAllByRole("button", { name: "local:fx-002" })[0]
    );
    expect(
      await screen.findByText("从新加坡搬到上海的第一周，租房踩了三个坑。")
    ).toBeInTheDocument();
  });

  it("disables citations for posts not in the run", () => {
    const broken: Report = {
      ...report,
      gaps: [{ post_ids: ["local:fx-999"], rationale: "x", title: "Missing" }],
    };
    render(<ReportView posts={posts} report={broken} />);
    const btn = screen.getByRole("button", { name: "local:fx-999" });
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute("title", "Post not found in this run");
  });

  it("never opens a dialog for an unknown citation, even a prototype key", () => {
    const broken: Report = {
      ...report,
      gaps: [
        {
          post_ids: ["local:fx-999", "constructor"],
          rationale: "x",
          title: "Missing",
        },
      ],
    };
    render(<ReportView posts={posts} report={broken} />);
    for (const name of ["local:fx-999", "constructor"]) {
      const btn = screen.getByRole("button", { name });
      expect(btn).toBeDisabled();
      fireEvent.click(btn);
    }
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("marks an empty section instead of leaving a blank card", () => {
    render(<ReportView posts={posts} report={report} />);
    const gaps = screen
      .getByText("Gaps and underused angles")
      .closest("[data-slot=card]") as HTMLElement;
    expect(within(gaps).getByText("None")).toBeInTheDocument();
  });

  it("shows judge answers in Chinese and closes with a translated button", async () => {
    const judge = fixtureEvents
      .filter((e) => e.type === "judged")
      .map((e) => e.payload.judge as JudgeResult)
      .find((j) => j.post_id === "local:fx-002") as JudgeResult;
    const judged: Record<string, PostView> = {
      ...posts,
      "local:fx-002": {
        ...(posts["local:fx-002"] as PostView),
        judge: { pass_two: judge },
      },
    };
    act(() => setLocale("zh"));
    render(<ReportView posts={judged} report={report} />);
    expect(screen.getByText("规律")).toBeInTheDocument();
    // The clip heading is the cited post's own title, unchanged in zh.
    expect(
      screen.getByRole("heading", { name: "新加坡人在上海的第一周" })
    ).toBeInTheDocument();
    await userEvent.click(
      screen.getAllByRole("button", { name: "local:fx-002" })[0]
    );
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByRole("heading", { name: "新加坡人在上海的第一周" })
    ).toBeInTheDocument();
    expect(within(dialog).getByText("钩子类型")).toBeInTheDocument();
    expect(within(dialog).getByText("抛出问题")).toBeInTheDocument();
    expect(within(dialog).queryByText("Close")).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "关闭" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
