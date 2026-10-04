import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { fixturePosts } from "@/lib/__fixtures__/posts";
import type { PostView } from "@/lib/api";
import { PostDialog } from "./PostDialog";

const [post] = fixturePosts;

function view(title: string, caption: string): PostView {
  return {
    judge: {},
    post: { ...post, text: { ...post.text, caption, title } },
    state: "judged",
  };
}

describe("PostDialog", () => {
  it("titles the dialog by title, then caption, then id", () => {
    const noop = vi.fn();
    const { rerender } = render(
      <PostDialog
        onOpenChange={noop}
        open={true}
        view={view("A title", "A caption")}
      />
    );
    expect(
      screen.getByRole("heading", { name: "A title" })
    ).toBeInTheDocument();

    rerender(
      <PostDialog
        onOpenChange={noop}
        open={true}
        view={view("", "A caption")}
      />
    );
    expect(
      screen.getByRole("heading", { name: "A caption" })
    ).toBeInTheDocument();

    rerender(
      <PostDialog onOpenChange={noop} open={true} view={view("", "")} />
    );
    expect(screen.getByRole("heading", { name: post.id })).toBeInTheDocument();
  });
});

describe("PostDialog original link", () => {
  it("links to the original post in a new tab", () => {
    render(
      <PostDialog onOpenChange={vi.fn()} open={true} view={view("t", "c")} />
    );
    const link = screen.getByRole("link", { name: "Open original post" });
    expect(link).toHaveAttribute("href", post.url);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
  });
});

describe("PostDialog local media", () => {
  it("plays the downloaded video when a run id is given", () => {
    render(
      <PostDialog
        onOpenChange={vi.fn()}
        open={true}
        runId="run x"
        view={view("t", "c")}
      />
    );
    const video = document.querySelector("video");
    expect(video).not.toBeNull();
    expect(video?.getAttribute("src")).toBe(
      `/api/runs/run%20x/media/${encodeURIComponent(post.id)}/video.mp4`
    );
  });
  it("shows no player without a run id", () => {
    render(
      <PostDialog onOpenChange={vi.fn()} open={true} view={view("t", "c")} />
    );
    expect(document.querySelector("video")).toBeNull();
  });
});
