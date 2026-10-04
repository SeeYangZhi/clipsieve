import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ReplayControls } from "./ReplayControls";

describe("ReplayControls", () => {
  it("toggles play and changes speed", async () => {
    const onToggle = vi.fn();
    const onSpeed = vi.fn();
    render(
      <ReplayControls
        done={10}
        onSpeed={onSpeed}
        onToggle={onToggle}
        playing={false}
        progress={0.25}
        speed={1}
        total={40}
      />
    );
    await userEvent.click(screen.getByRole("button", { name: "Play" }));
    expect(onToggle).toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "4x" }));
    expect(onSpeed).toHaveBeenCalledWith(4);
    expect(screen.getByText("10 / 40 events")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute(
      "aria-valuenow",
      "25"
    );
  });

  it("marks the active speed and shows Pause while playing", () => {
    render(
      <ReplayControls
        done={0}
        onSpeed={vi.fn()}
        onToggle={vi.fn()}
        playing
        progress={0}
        speed={16}
        total={0}
      />
    );
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "16x" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    expect(screen.getByRole("button", { name: "1x" })).toHaveAttribute(
      "aria-pressed",
      "false"
    );
  });
});
