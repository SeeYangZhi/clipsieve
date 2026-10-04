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
