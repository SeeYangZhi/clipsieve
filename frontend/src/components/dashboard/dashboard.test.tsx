import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { fixtureEvents } from "@/lib/__fixtures__/run-events";
import { type PostTile, reduceAll } from "@/lib/events";
import { setLocale } from "@/lib/i18n";
import type { RunEvent } from "@/lib/types";
import { Aggregates } from "./Aggregates";
import { Counters } from "./Counters";
import { CurrentItem } from "./CurrentItem";
import { Dashboard } from "./Dashboard";
import { PostGrid, TILE_STATE_CLASS } from "./PostGrid";
import { ReviewBucket } from "./ReviewBucket";

const done = reduceAll(fixtureEvents);
// seq 23 is the pass-two `judged` for local:fx-002 (hook type "problem", hook strength 2.5).
const midRun = reduceAll(fixtureEvents.filter((e) => e.seq <= 23));

afterEach(() => {
  act(() => setLocale("en"));
});

const FX2_CAPTION = "从新加坡搬到上海的第一周，租房踩了三个坑。";

/** A tile whose post has the given title and, optionally, caption. */
function retitled(tile: PostTile, title: string, caption?: string): PostTile {
  const text = { ...tile.post.text, title };
  if (caption !== undefined) {
    text.caption = caption;
  }
  return { ...tile, post: { ...tile.post, text } };
}

describe("Counters", () => {
  it("renders six tiles with values", () => {
    render(<Counters counters={done.counters} rate={12.5} />);
    expect(screen.getByText("Collected").nextSibling).toHaveTextContent("5");
    expect(screen.getByText("Answers / sec").nextSibling).toHaveTextContent(
      "12.5"
    );
    expect(screen.getByText("Jev cost").nextSibling).toHaveTextContent(
      "$0.0006"
    );
    expect(screen.getByText("Elapsed").nextSibling).toHaveTextContent("12.2s");
  });
});

describe("PostGrid", () => {
  it("renders one tile per post with state and Chinese titles intact", () => {
    render(<PostGrid posts={done.posts} runId="FIXTURE" total={5} />);
    const grid = screen.getByRole("list");
    expect(within(grid).getAllByRole("listitem")).toHaveLength(5);
    expect(screen.getByTitle("新加坡人在上海的第一周")).toBeInTheDocument();
    expect(screen.getByTestId("tile-local:fx-001")).toHaveAttribute(
      "data-state",
      "shortlisted"
    );
    expect(screen.getByTestId("tile-local:fx-005")).toHaveAttribute(
      "data-state",
      "dropped_pass_one"
    );
    expect(screen.getByTestId("tile-local:fx-004")).toHaveAttribute(
      "data-state",
      "judge_failed"
    );
    expect(screen.getByText("5 / 5")).toBeInTheDocument();
  });

  it("marks exactly the tile whose judge call failed", () => {
    const { container } = render(
      <PostGrid posts={done.posts} runId="FIXTURE" total={5} />
    );
    const failed = container.querySelectorAll('[data-state="judge_failed"]');
    expect(failed).toHaveLength(1);
    expect(failed[0]).toHaveAttribute("data-testid", "tile-local:fx-004");
    expect(screen.getByTestId("tile-local:fx-003")).toHaveAttribute(
      "data-state",
      "review"
    );
    expect(screen.getByTestId("tile-local:fx-004")).toHaveAccessibleName(
      "Shanghai apartment hunting checklist (judge failed)"
    );
  });

  it("gives every tile state a distinct look", () => {
    const looks = Object.values(TILE_STATE_CLASS);
    expect(looks).toHaveLength(6);
    expect(new Set(looks).size).toBe(6);
  });

  it("requests encoded thumbnails and falls back to the kind icon on error", () => {
    render(<PostGrid posts={done.posts} runId="run 1" total={5} />);
    const video = screen.getByTestId("tile-local:fx-002");
    const img = video.querySelector("img");
    expect(img).toHaveAttribute(
      "src",
      "/api/runs/run%201/media/local%3Afx-002/thumb.jpg"
    );
    fireEvent.error(img as HTMLImageElement);
    expect(video.querySelector("img")).toBeNull();
    expect(video.querySelector("svg.lucide-film")).not.toBeNull();

    const note = screen.getByTestId("tile-local:fx-005");
    fireEvent.error(note.querySelector("img") as HTMLImageElement);
    expect(note.querySelector("svg.lucide-images")).not.toBeNull();
    // The other tiles keep their thumbnails.
    expect(
      screen.getByTestId("tile-local:fx-001").querySelector("img")
    ).not.toBeNull();
  });

  it("falls back past an empty title to the caption, then the id", () => {
    const posts = {
      ...done.posts,
      "local:fx-001": retitled(done.posts["local:fx-001"], "", ""),
      "local:fx-002": retitled(done.posts["local:fx-002"], ""),
    };
    render(<PostGrid posts={posts} runId="FIXTURE" total={5} />);
    expect(screen.getByTestId("tile-local:fx-002")).toHaveAttribute(
      "title",
      FX2_CAPTION
    );
    expect(screen.getByTestId("tile-local:fx-001")).toHaveAttribute(
      "title",
      "local:fx-001"
    );
  });

  it("labels tile states in Chinese", () => {
    act(() => setLocale("zh"));
    render(<PostGrid posts={done.posts} runId="FIXTURE" total={5} />);
    expect(screen.getByTestId("tile-local:fx-002")).toHaveAccessibleName(
      "新加坡人在上海的第一周 (已入围)"
    );
    expect(screen.getByText("帖子")).toBeInTheDocument();
  });
});

describe("CurrentItem", () => {
  it("renders one row per answer with the right metric", () => {
    render(<CurrentItem latest={midRun.latest} />);
    expect(screen.getByText("Hook type")).toBeInTheDocument();
    expect(screen.getByText("Problem")).toBeInTheDocument();
    expect(screen.getByText("2.5 / 5")).toBeInTheDocument();
    expect(screen.getAllByRole("progressbar").length).toBeGreaterThanOrEqual(7);
  });
  it("falls back past an empty title to the caption", () => {
    const latest = midRun.latest as NonNullable<typeof midRun.latest>;
    const post = { ...latest.post, text: { ...latest.post.text, title: "" } };
    render(<CurrentItem latest={{ ...latest, post }} />);
    expect(screen.getByText(FX2_CAPTION)).toBeInTheDocument();
  });
  it("shows the empty state", () => {
    render(<CurrentItem latest={null} />);
    expect(
      screen.getByText("Waiting for the first judged post…")
    ).toBeInTheDocument();
  });
  it("keeps a Chinese title unchanged in both locales", () => {
    const cut = fixtureEvents.findIndex(
      (e) =>
        e.type === "judged" &&
        (e.payload.judge as { post_id: string }).post_id === "local:fx-002"
    );
    const { latest } = reduceAll(fixtureEvents.slice(0, cut + 1));
    const { rerender } = render(<CurrentItem latest={latest} />);
    expect(screen.getByText("新加坡人在上海的第一周")).toBeInTheDocument();
    act(() => setLocale("zh"));
    rerender(<CurrentItem latest={latest} />);
    expect(screen.getByText("新加坡人在上海的第一周")).toBeInTheDocument();
    expect(screen.getByText("钩子类型")).toBeInTheDocument();
    expect(screen.getByText("抛出问题")).toBeInTheDocument();
  });
});

describe("Aggregates", () => {
  it("renders distributions with percentages", () => {
    render(<Aggregates aggregates={done.aggregates} />);
    expect(screen.getByText("Opening hook")).toBeInTheDocument();
    expect(screen.getByText("Vlog montage")).toBeInTheDocument();
    expect(screen.getAllByText("50%").length).toBeGreaterThanOrEqual(1);
  });
  it("shows hook type, format and persona fit only", () => {
    render(<Aggregates aggregates={done.aggregates} />);
    expect(screen.getByText("Format")).toBeInTheDocument();
    expect(screen.getByText("Persona fit")).toBeInTheDocument();
    expect(screen.getByText("Level 4")).toBeInTheDocument();
    expect(screen.getByText("100%")).toBeInTheDocument();
    // format_guess is a pass-one guess, not part of the category picture.
    expect(screen.queryByText("Format guess")).not.toBeInTheDocument();
  });
  it("shows the empty state before pass two", () => {
    render(<Aggregates aggregates={{}} />);
    expect(screen.getByText("No pass-two results yet")).toBeInTheDocument();
  });
});

describe("ReviewBucket", () => {
  it("shows the count", () => {
    render(
      <ReviewBucket posts={done.posts} review={done.review} runId="FIXTURE" />
    );
    expect(screen.getByText("1 posts")).toBeInTheDocument();
  });
  it("lists the review posts in a dialog with a translated close", () => {
    act(() => setLocale("zh"));
    render(
      <ReviewBucket posts={done.posts} review={done.review} runId="FIXTURE" />
    );
    fireEvent.click(screen.getByRole("button", { name: "打开列表" }));
    const dialog = screen.getByRole("dialog");
    expect(
      within(dialog).getByText("上海地铁早高峰 vlog｜一个新加坡人的日常")
    ).toBeInTheDocument();
    expect(within(dialog).queryByText("Close")).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "关闭" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
  it("lists a post with an empty title by its caption", () => {
    const posts = {
      ...done.posts,
      "local:fx-002": retitled(done.posts["local:fx-002"], ""),
    };
    render(
      <ReviewBucket posts={posts} review={["local:fx-002"]} runId="FIXTURE" />
    );
    fireEvent.click(screen.getByRole("button", { name: "Open list" }));
    expect(
      within(screen.getByRole("dialog")).getByText(FX2_CAPTION)
    ).toBeInTheDocument();
  });
  it("disables the list when nothing is in review", () => {
    render(<ReviewBucket posts={done.posts} review={[]} runId="FIXTURE" />);
    expect(screen.getByRole("button", { name: "Open list" })).toBeDisabled();
  });
});

describe("ReviewBucket inspection", () => {
  it("opens the post dialog with answers and the original link from a review item", () => {
    render(
      <ReviewBucket posts={done.posts} review={done.review} runId="FIXTURE" />
    );
    fireEvent.click(screen.getByRole("button", { name: "Open list" }));
    const [reviewId] = done.review;
    const reviewed = done.posts[reviewId];
    const title =
      reviewed.post.text.title || reviewed.post.text.caption || reviewId;
    fireEvent.click(screen.getByRole("button", { name: title }));
    const dialogs = screen.getAllByRole("dialog");
    const post = dialogs.at(-1) as HTMLElement;
    expect(
      within(post).getByRole("heading", { name: title })
    ).toBeInTheDocument();
    expect(within(post).getByText("Hook strength")).toBeInTheDocument();
    const link = within(post).getByRole("link", { name: "Open original post" });
    expect(link).toHaveAttribute("href", reviewed.post.url);
    expect(link).toHaveAttribute("target", "_blank");
  });
});

describe("PostGrid inspection", () => {
  it("reports the clicked tile", () => {
    const seen: string[] = [];
    const onSelect = (id: string) => {
      seen.push(id);
    };
    render(
      <PostGrid
        onSelect={onSelect}
        posts={done.posts}
        runId="FIXTURE"
        total={5}
      />
    );
    fireEvent.click(
      within(screen.getByTestId("tile-local:fx-001")).getByRole("button")
    );
    expect(seen).toEqual(["local:fx-001"]);
  });
});

describe("Dashboard", () => {
  it("opens the post dialog when a tile is clicked", () => {
    render(
      <Dashboard
        connected={false}
        events={fixtureEvents}
        mode="live"
        runId="FIXTURE"
        state={done}
      />
    );
    fireEvent.click(
      within(screen.getByTestId("tile-local:fx-001")).getByRole("button")
    );
    expect(
      within(screen.getByRole("dialog")).getByRole("heading", {
        name: done.posts["local:fx-001"].post.text.title,
      })
    ).toBeInTheDocument();
  });
  it("composes the four regions mid-run, without the report link", () => {
    render(
      <Dashboard
        connected={true}
        controls={<button type="button">Pause</button>}
        events={fixtureEvents.filter((e) => e.seq <= 23)}
        mode="live"
        runId="run 1"
        state={midRun}
      />
    );
    expect(screen.getByText("Pass two")).toBeInTheDocument();
    expect(screen.getByText("live")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();
    expect(screen.getByText("Collected")).toBeInTheDocument();
    expect(screen.getByText("Posts")).toBeInTheDocument();
    expect(screen.getByText("Now answered")).toBeInTheDocument();
    expect(screen.getByText("The category so far")).toBeInTheDocument();
    expect(screen.getByText("Too close to call")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Replay" })).toHaveAttribute(
      "href",
      "/runs/run%201/replay"
    );
    expect(
      screen.queryByRole("link", { name: "View report" })
    ).not.toBeInTheDocument();
    // Without a planned total, the grid counts against what was collected.
    expect(screen.getByText("5 / 5")).toBeInTheDocument();
  });

  it("links to the encoded report once done and drops the connection badge", () => {
    render(
      <Dashboard
        connected={false}
        events={fixtureEvents}
        mode="live"
        runId="run 1"
        state={done}
        total={8}
      />
    );
    expect(screen.getByRole("link", { name: "View report" })).toHaveAttribute(
      "href",
      "/runs/run%201/report"
    );
    expect(screen.getByText("Done")).toBeInTheDocument();
    expect(screen.queryByText("reconnecting…")).not.toBeInTheDocument();
    expect(screen.getByText("5 / 8")).toBeInTheDocument();
  });

  it("offers no report for a failed run", () => {
    render(
      <Dashboard
        connected={false}
        events={[]}
        mode="live"
        runId="run 1"
        state={{ ...midRun, done: true, stage: "failed" }}
      />
    );
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "View report" })
    ).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Replay" })).toBeInTheDocument();
  });

  it("shows a dropped stream as reconnecting while the run is going", () => {
    render(
      <Dashboard
        connected={false}
        events={[]}
        mode="live"
        runId="run 1"
        state={midRun}
      />
    );
    expect(screen.getByText("reconnecting…")).toBeInTheDocument();
  });

  it("never shows the connection badge in replay, and links back to the run", () => {
    render(
      <Dashboard
        connected={false}
        events={[]}
        mode="replay"
        runId="run 1"
        state={midRun}
      />
    );
    expect(screen.queryByText("reconnecting…")).not.toBeInTheDocument();
    expect(screen.queryByText("live")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Replay" })
    ).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to run" })).toHaveAttribute(
      "href",
      "/runs/run%201"
    );
  });

  it("explains a failed run with the pipeline's last unrecoverable error", () => {
    // What the runner's `_fail` writes: the error first, then the failed stage.
    const failedEvents: RunEvent[] = [
      ...fixtureEvents.filter((e) => e.seq <= 23),
      {
        payload: {
          message: "nothing to explain: no post reached the shortlist",
          recoverable: false,
          where: "explain",
        },
        run_id: "FIXTURE",
        seq: 24,
        stage: "explaining",
        ts: "2026-10-03T10:00:30Z",
        type: "error",
      },
      {
        payload: { from: "explaining", to: "failed" },
        run_id: "FIXTURE",
        seq: 25,
        stage: "failed",
        ts: "2026-10-03T10:00:31Z",
        type: "stage_changed",
      },
    ];
    const failed = reduceAll(failedEvents);
    render(
      <Dashboard
        connected={false}
        events={failedEvents}
        mode="live"
        runId="run 1"
        state={failed}
      />
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Run failed");
    expect(alert).toHaveTextContent(
      "nothing to explain: no post reached the shortlist"
    );
    act(() => setLocale("zh"));
    expect(screen.getByRole("alert")).toHaveTextContent("任务失败");
  });

  it("falls back to the stored run's error when the log carries none", () => {
    render(
      <Dashboard
        connected={false}
        error="explain backend exited 1"
        events={[]}
        mode="live"
        runId="run 1"
        state={{ ...midRun, done: true, stage: "failed" }}
      />
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "explain backend exited 1"
    );
  });

  it("shows no failure alert while the run is going", () => {
    render(
      <Dashboard
        connected={true}
        events={[]}
        mode="live"
        runId="run 1"
        state={midRun}
      />
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
