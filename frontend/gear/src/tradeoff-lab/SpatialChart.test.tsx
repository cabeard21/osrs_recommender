import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SpatialChart } from "./SpatialChart";
import type { LabPoint } from "./model";

const points: LabPoint[] = [
  {
    id: "offense",
    label: "Offense",
    dps: 4,
    defence: 10000,
    prayer: 5,
    costGp: 100,
    equipment: [],
    potions: [],
    attackType: "slash",
    stance: "accurate",
  },
  {
    id: "defense",
    label: "Defense",
    dps: 2,
    defence: 20000,
    prayer: 20,
    costGp: 200,
    equipment: [],
    potions: [],
    attackType: "stab",
    stance: "accurate",
  },
];

function setup() {
  const onSelect = vi.fn();
  render(
    <SpatialChart points={points} selectedId="offense" onSelect={onSelect} />,
  );
  return onSelect;
}

describe("SpatialChart", () => {
  it("exposes all three exact ranges and the shared selection", () => {
    setup();
    expect(screen.getByText("DPS")).toBeInTheDocument();
    expect(screen.getByText("Stab defense")).toBeInTheDocument();
    expect(screen.getByText("Prayer bonus")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "3D select Offense" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("button", { name: "3D select Defense" }),
    ).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText(/10,000.*20,000/)).toBeInTheDocument();
  });

  it("selects a configuration by pointer or keyboard", () => {
    const onSelect = setup();
    const point = screen.getByRole("button", { name: "3D select Defense" });
    fireEvent.click(point);
    fireEvent.keyDown(point, { key: "Enter" });
    fireEvent.keyDown(point, { key: " " });
    fireEvent.keyDown(point, { key: "ArrowDown" });
    expect(onSelect.mock.calls).toEqual([
      ["defense"],
      ["defense"],
      ["defense"],
    ]);
  });

  it("rotates, tilts, zooms and resets without changing selected loadout", () => {
    const onSelect = setup();
    const point = screen.getByRole("button", { name: "3D select Defense" });
    const original = [point.getAttribute("cx"), point.getAttribute("cy")];
    fireEvent.change(screen.getByLabelText("3D rotation"), {
      target: { value: "90" },
    });
    fireEvent.change(screen.getByLabelText("3D tilt"), {
      target: { value: "60" },
    });
    expect([point.getAttribute("cx"), point.getAttribute("cy")]).not.toEqual(
      original,
    );
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByLabelText("3D zoom")).toHaveTextContent("110%");
    fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    expect(screen.getByLabelText("3D zoom")).toHaveTextContent("100%");
    fireEvent.click(screen.getByRole("button", { name: "Reset camera" }));
    expect([point.getAttribute("cx"), point.getAttribute("cy")]).toEqual(
      original,
    );
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("supports drag rotation without selecting the point under the release", () => {
    vi.stubGlobal("PointerEvent", MouseEvent);
    const onSelect = setup();
    const chart = screen.getByRole("group", {
      name: "Interactive 3D tradeoff chart",
    });
    const point = screen.getByRole("button", { name: "3D select Defense" });
    const capture = vi.fn();
    Object.defineProperty(chart, "setPointerCapture", { value: capture });
    const original = point.getAttribute("cx");
    fireEvent.pointerDown(chart, { clientX: 100, clientY: 100, button: 0 });
    expect(capture).not.toHaveBeenCalled();
    fireEvent.pointerMove(chart, { clientX: 160, clientY: 125, button: 0 });
    expect(capture).toHaveBeenCalledTimes(1);
    fireEvent.pointerUp(chart, { clientX: 160, clientY: 125, button: 0 });
    fireEvent.click(point);
    expect(point.getAttribute("cx")).not.toEqual(original);
    expect(onSelect).not.toHaveBeenCalled();
    fireEvent.pointerDown(point, { clientX: 100, clientY: 100, button: 0 });
    fireEvent.pointerUp(point, { clientX: 100, clientY: 100, button: 0 });
    fireEvent.click(point);
    expect(onSelect).toHaveBeenCalledWith("defense");
    vi.unstubAllGlobals();
  });

  it("keeps constant-valued points finite", () => {
    render(
      <SpatialChart
        points={[points[0]]}
        selectedId="offense"
        onSelect={vi.fn()}
      />,
    );
    const point = screen.getByRole("button", { name: "3D select Offense" });
    expect(Number.isFinite(Number(point.getAttribute("cx")))).toBe(true);
    expect(Number.isFinite(Number(point.getAttribute("cy")))).toBe(true);
  });

  it("ignores secondary-button gestures and cancels an interrupted drag", () => {
    vi.stubGlobal("PointerEvent", MouseEvent);
    const onSelect = setup();
    const chart = screen.getByRole("group", {
      name: "Interactive 3D tradeoff chart",
    });
    const point = screen.getByRole("button", { name: "3D select Defense" });
    const original = point.getAttribute("cx");
    fireEvent.pointerDown(chart, { clientX: 100, clientY: 100, button: 2 });
    fireEvent.pointerMove(chart, { clientX: 160, clientY: 125 });
    expect(point.getAttribute("cx")).toEqual(original);
    fireEvent.pointerDown(chart, { clientX: 100, clientY: 100, button: 0 });
    fireEvent.pointerMove(chart, { clientX: 102, clientY: 100 });
    expect(point.getAttribute("cx")).toEqual(original);
    fireEvent.pointerCancel(chart);
    fireEvent.pointerMove(chart, { clientX: 160, clientY: 125 });
    fireEvent.click(point);
    expect(point.getAttribute("cx")).toEqual(original);
    expect(onSelect).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});
