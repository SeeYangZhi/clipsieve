import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { BriefForm } from "./BriefForm";

const adapters = [
  { healthy: true, message: "ok", platform: "youtube" },
  {
    healthy: false,
    message: "Chrome CDP port 9222 unreachable",
    platform: "xiaohongshu",
  },
  { healthy: true, message: "ok", platform: "local" },
];
const rubrics = [
  {
    description: "Hooks, format, persona fit",
    name: "creator-hooks-v1",
    question_ids: ["hook_type"],
  },
];

describe("BriefForm", () => {
  it("submits brief, ticked platforms with quantities, and rubric", async () => {
    const onSubmit = vi.fn();
    render(
      <BriefForm
        adapters={adapters}
        busy={false}
        onSubmit={onSubmit}
        rubrics={rubrics}
      />
    );
    await userEvent.type(
      screen.getByLabelText("Brief"),
      "新加坡人搬到上海 vlog"
    );
    await userEvent.click(screen.getByLabelText("youtube"));
    const qty = screen.getByLabelText("Posts per platform: youtube");
    await userEvent.clear(qty);
    await userEvent.type(qty, "200");
    await userEvent.click(
      screen.getByRole("button", { name: "Start research" })
    );
    expect(onSubmit).toHaveBeenCalledWith({
      brief: "新加坡人搬到上海 vlog",
      language_hint: undefined,
      platforms: ["youtube"],
      quantities: { youtube: 200 },
      rubric_pack: "creator-hooks-v1",
    });
  });

  it("disables unhealthy adapters and shows their message", () => {
    render(
      <BriefForm
        adapters={adapters}
        busy={false}
        onSubmit={vi.fn()}
        rubrics={rubrics}
      />
    );
    expect(screen.getByLabelText("xiaohongshu")).toBeDisabled();
    expect(
      screen.getByText("Chrome CDP port 9222 unreachable")
    ).toBeInTheDocument();
  });

  it("blocks submit without a brief or platform", async () => {
    const onSubmit = vi.fn();
    render(
      <BriefForm
        adapters={adapters}
        busy={false}
        onSubmit={onSubmit}
        rubrics={rubrics}
      />
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Start research" })
    );
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText("Write a brief first")).toBeInTheDocument();
  });

  it("uses the first rubric when rubrics arrive after mount", async () => {
    const onSubmit = vi.fn();
    const { rerender } = render(
      <BriefForm adapters={[]} busy={false} onSubmit={onSubmit} rubrics={[]} />
    );
    rerender(
      <BriefForm
        adapters={adapters}
        busy={false}
        onSubmit={onSubmit}
        rubrics={rubrics}
      />
    );
    await userEvent.type(screen.getByLabelText("Brief"), "vlog hooks");
    await userEvent.click(screen.getByLabelText("local"));
    await userEvent.click(
      screen.getByRole("button", { name: "Start research" })
    );
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        quantities: { local: 500 },
        rubric_pack: "creator-hooks-v1",
      })
    );
  });
});
