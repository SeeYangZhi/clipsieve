import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Plan } from "@/lib/types";
import { PlanEditor } from "./PlanEditor";

const LEVEL_LABEL = /^Level \d$/;

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
  run_id: "r1",
};

describe("PlanEditor", () => {
  it("edits a query and saves", async () => {
    const onSave = vi.fn();
    render(
      <PlanEditor
        busy={false}
        onApprove={vi.fn()}
        onSave={onSave}
        plan={plan}
      />
    );
    const input = screen.getByDisplayValue("新加坡人 上海 生活 vlog");
    await userEvent.clear(input);
    await userEvent.type(input, "新加坡人 搬到上海");
    await userEvent.click(screen.getByRole("button", { name: "Save plan" }));
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave.mock.calls[0][0].queries[1].query).toBe("新加坡人 搬到上海");
  });

  it("adds and removes queries", async () => {
    const onSave = vi.fn();
    render(
      <PlanEditor
        busy={false}
        onApprove={vi.fn()}
        onSave={onSave}
        plan={plan}
      />
    );
    await userEvent.click(screen.getByRole("button", { name: "Add query" }));
    expect(screen.getAllByRole("button", { name: "Remove" })).toHaveLength(3);
    await userEvent.click(screen.getAllByRole("button", { name: "Remove" })[0]);
    await userEvent.click(screen.getByRole("button", { name: "Save plan" }));
    expect(onSave.mock.calls[0][0].queries).toHaveLength(2);
  });

  it("approves with the current edits", async () => {
    const onApprove = vi.fn();
    render(
      <PlanEditor
        busy={false}
        onApprove={onApprove}
        onSave={vi.fn()}
        plan={plan}
      />
    );
    const crit = screen.getByDisplayValue("Close match");
    await userEvent.clear(crit);
    await userEvent.type(crit, "Very close match");
    await userEvent.click(
      screen.getByRole("button", { name: "Approve and run" })
    );
    expect(onApprove.mock.calls[0][0].persona_fit_criteria[3]).toBe(
      "Very close match"
    );
  });
  it("saves an unchanged plan as-is: five levels, Query fields only", async () => {
    const onSave = vi.fn();
    render(
      <PlanEditor
        busy={false}
        onApprove={vi.fn()}
        onSave={onSave}
        plan={plan}
      />
    );
    expect(screen.getAllByRole("textbox", { name: LEVEL_LABEL })).toHaveLength(
      5
    );
    await userEvent.click(screen.getByRole("button", { name: "Save plan" }));
    expect(onSave.mock.calls[0][0]).toEqual(plan);
  });

  it("parses quantities at save: capped, blank keeps the planned number", async () => {
    const onSave = vi.fn();
    render(
      <PlanEditor
        busy={false}
        onApprove={vi.fn()}
        onSave={onSave}
        plan={plan}
      />
    );
    const yt = screen.getByLabelText("youtube");
    await userEvent.clear(yt);
    await userEvent.type(yt, "300");
    await userEvent.clear(screen.getByLabelText("xiaohongshu"));
    await userEvent.click(screen.getByRole("button", { name: "Save plan" }));
    expect(onSave.mock.calls[0][0].quantities).toEqual({
      xiaohongshu: 500,
      youtube: 300,
    });
    await userEvent.clear(yt);
    await userEvent.type(yt, "99999");
    await userEvent.click(screen.getByRole("button", { name: "Save plan" }));
    expect(onSave.mock.calls[1][0].quantities.youtube).toBe(5000);
  });

  it("changes a query's platform among the plan's platforms", async () => {
    const onSave = vi.fn();
    render(
      <PlanEditor
        busy={false}
        onApprove={vi.fn()}
        onSave={onSave}
        plan={plan}
      />
    );
    await userEvent.selectOptions(
      screen.getByLabelText("Platform 1"),
      "xiaohongshu"
    );
    await userEvent.click(screen.getByRole("button", { name: "Save plan" }));
    expect(onSave.mock.calls[0][0].queries[0].platform).toBe("xiaohongshu");
  });

  it("will not approve a blank query or level", async () => {
    const onApprove = vi.fn();
    render(
      <PlanEditor
        busy={false}
        onApprove={onApprove}
        onSave={vi.fn()}
        plan={plan}
      />
    );
    await userEvent.click(screen.getByRole("button", { name: "Add query" }));
    await userEvent.click(
      screen.getByRole("button", { name: "Approve and run" })
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Every search query needs text"
    );
    await userEvent.click(screen.getAllByRole("button", { name: "Remove" })[2]);
    await userEvent.clear(screen.getByDisplayValue("Adjacent niche"));
    await userEvent.click(
      screen.getByRole("button", { name: "Approve and run" })
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Describe all five persona fit levels"
    );
    await userEvent.click(screen.getAllByRole("button", { name: "Remove" })[0]);
    await userEvent.click(screen.getAllByRole("button", { name: "Remove" })[0]);
    await userEvent.click(
      screen.getByRole("button", { name: "Approve and run" })
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Add at least one search query"
    );
    expect(onApprove).not.toHaveBeenCalled();
  });

  it("disables both actions while busy", () => {
    render(
      <PlanEditor busy onApprove={vi.fn()} onSave={vi.fn()} plan={plan} />
    );
    expect(screen.getByRole("button", { name: "Save plan" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Starting…" })).toBeDisabled();
  });

  it("locks an approved plan and links to its run", () => {
    const approved: Plan = {
      ...plan,
      approved_at: "2026-10-03T10:00:00Z",
      run_id: "run/1",
    };
    render(
      <PlanEditor
        busy={false}
        onApprove={vi.fn()}
        onSave={vi.fn()}
        plan={approved}
      />
    );
    expect(screen.getByRole("button", { name: "Save plan" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Approve and run" })
    ).toBeDisabled();
    expect(screen.getByDisplayValue("Close match")).toBeDisabled();
    expect(screen.getByRole("link", { name: "Open the run" })).toHaveAttribute(
      "href",
      "/runs/run%2F1"
    );
  });
});
