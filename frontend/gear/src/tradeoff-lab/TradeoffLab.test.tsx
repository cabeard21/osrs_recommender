import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import TradeoffLab from "./TradeoffLab";
import { example, type LabExample } from "./model";

const dynamic: LabExample = {
  ...example,
  target: "Dynamic target",
  sampled: false,
  totalCount: 2,
  sourceDescription: "Current optimization result",
  metrics: [
    { key: "dps", label: "DPS", shortLabel: "DPS" },
    {
      key: "accuracy",
      label: "Accuracy",
      shortLabel: "Accuracy",
      unit: "probability",
    },
    {
      key: "magic",
      label: "Magic damage",
      shortLabel: "Magic damage",
      unit: "percent",
    },
    {
      key: "prayer_bonus",
      label: "Prayer bonus",
      shortLabel: "Prayer bonus",
      unit: "bonus",
    },
  ],
  points: example.points.slice(0, 2).map((p, i) => ({
    ...p,
    id: i ? "other" : example.selectedId,
    values: {
      dps: p.dps,
      accuracy: i ? 0.9 : 0.8,
      magic: i ? 12 : 8,
      prayer_bonus: i ? 10 : 5,
    },
  })),
};

describe("temporary tradeoff lab", () => {
  it("keeps the Lab open when the original tab is unavailable or the browser blocks closing", async () => {
    const close = vi.spyOn(window, "close").mockImplementation(() => {});
    const checkOrigin = vi
      .fn()
      .mockRejectedValueOnce(
        new Error("The original Gear optimizer tab is unavailable."),
      )
      .mockResolvedValueOnce(undefined);
    try {
      render(<TradeoffLab data={dynamic} onBackToResults={checkOrigin} />);
      const back = screen.getByRole("button", { name: "Back to Gear results" });
      fireEvent.click(back);
      expect(
        await screen.findByText(
          "The original Gear optimizer tab is unavailable.",
        ),
      ).toHaveAttribute("role", "status");
      expect(close).not.toHaveBeenCalled();
      fireEvent.click(back);
      expect(
        await screen.findByText(
          "Switch to the original Gear optimizer tab to see your results.",
        ),
      ).toHaveAttribute("role", "status");
      expect(close).toHaveBeenCalledOnce();
    } finally {
      close.mockRestore();
    }
  });

  it("offers the return action only for snapshots with an originating optimizer", async () => {
    const action = "Use this setup in Gear optimizer";
    const { rerender } = render(<TradeoffLab />);
    expect(screen.queryByRole("button", { name: action })).toBeNull();
    const apply = vi
      .fn()
      .mockRejectedValueOnce(new Error("The optimization run has changed."))
      .mockResolvedValueOnce(undefined);
    rerender(<TradeoffLab key="current" data={dynamic} onUseSetup={apply} />);
    fireEvent.click(
      screen.getByRole("button", {
        name: `Color select ${dynamic.points[1].label}`,
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: action }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The optimization run has changed.",
    );
    expect(apply).toHaveBeenCalledExactlyOnceWith("other");
    fireEvent.click(screen.getByRole("button", { name: action }));
    const sent = await screen.findByText(
      /selected in the original Gear optimizer tab/,
    );
    expect(sent).toHaveAttribute("role", "status");
  });
  it("retains fractional objective values and small deltas in the inspector and table", () => {
    const data: LabExample = {
      ...dynamic,
      metrics: [
        dynamic.metrics![0],
        {
          key: "mean_roll",
          label: "Mean defense roll",
          shortLabel: "Mean defense roll",
          unit: "roll",
        },
        {
          key: "weighted_prayer",
          label: "Weighted prayer bonus",
          shortLabel: "Weighted prayer bonus",
          unit: "bonus",
        },
      ],
      points: dynamic.points.map((point, i) => ({
        ...point,
        values: {
          dps: point.dps,
          mean_roll: i ? 17390.5 : 17390.25,
          weighted_prayer: i ? 20.25 : 20,
        },
      })),
    };
    render(<TradeoffLab data={data} />);
    fireEvent.click(
      screen.getByRole("button", {
        name: `Color select ${data.points[1].label}`,
      }),
    );
    const inspector = screen.getByRole("complementary", {
      name: "Selected configuration",
    });
    expect(within(inspector).getByText("17,390.5")).toBeVisible();
    expect(within(inspector).getByText("20.25")).toBeVisible();
    expect(within(inspector).getAllByText("+0.25")).toHaveLength(2);
    fireEvent.click(screen.getByText("Browse saved configurations"));
    const table = screen.getByRole("table", {
      name: "Saved configurations",
    });
    expect(within(table).getByText("17,390.25")).toBeVisible();
    expect(within(table).getByText("17,390.5")).toBeVisible();
    expect(within(table).getByText("20.25")).toBeVisible();
  });
  it("supports dynamic units and projection choices while keeping every objective in its table", () => {
    render(<TradeoffLab data={dynamic} />);
    expect(screen.getByText("Dynamic target")).toBeVisible();
    expect(screen.getByText(/Current optimization result/)).toBeVisible();
    expect(
      screen.getByRole("group", {
        name: "DPS vs Accuracy, colored by Magic damage",
      }),
    ).toBeVisible();
    fireEvent.change(screen.getByLabelText("Chart objective 3"), {
      target: { value: "prayer_bonus" },
    });
    expect(
      screen.getByRole("group", {
        name: "DPS vs Accuracy, colored by Prayer bonus",
      }),
    ).toBeVisible();
    fireEvent.click(screen.getByText("Browse saved configurations"));
    const table = screen.getByRole("table", {
      name: "Saved configurations",
    });
    expect(
      within(table).getByRole("columnheader", { name: "Magic damage" }),
    ).toBeVisible();
    expect(within(table).getByText("80.00%")).toBeVisible();
    expect(within(table).getByText("8.00%")).toBeVisible();
  });
  it("shows two objectives without inventing a third axis", () => {
    render(
      <TradeoffLab
        data={{ ...dynamic, metrics: dynamic.metrics!.slice(0, 2) }}
      />,
    );
    expect(
      screen.getByText(
        "A 3D view requires three objectives. This result has fewer than three.",
      ),
    ).toBeVisible();
    expect(screen.queryByLabelText("Color represents")).not.toBeInTheDocument();
    expect(
      within(
        screen.getByRole("region", { name: "Color-coded scatter" }),
      ).getByRole("group", { name: "DPS vs Accuracy" }),
    ).toBeVisible();
  });
  it("shows the saved scenario and all five views with honest sample coverage", () => {
    render(<TradeoffLab />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Tradeoff lab",
    );
    expect(screen.getByText(example.target)).toBeVisible();
    expect(
      screen.getByText(/128 representative frontier points of 185/),
    ).toBeVisible();
    for (const name of [
      "Linked pairwise charts",
      "Color-coded scatter",
      "Parallel coordinates",
      "Interactive 3D scatter",
      "Pinned comparisons",
    ])
      expect(screen.getByRole("heading", { name })).toBeVisible();
  });

  it("selects one configuration consistently across every chart and inspector", () => {
    render(<TradeoffLab />);
    const point = example.points.find((p) => p.id !== example.selectedId)!;
    fireEvent.click(
      screen.getByRole("button", {
        name: `DPS vs Stab defense select ${point.label}`,
      }),
    );
    expect(
      screen.getByRole("button", { name: `Color select ${point.label}` }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("button", { name: `Parallel select ${point.label}` }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("button", { name: `3D select ${point.label}` }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      within(
        screen.getByRole("complementary", { name: "Selected configuration" }),
      ).getByRole("heading", { name: point.label }),
    ).toBeVisible();
  });

  it("pins the selected loadout and supports removing pins without changing selection", () => {
    render(<TradeoffLab />);
    fireEvent.click(screen.getByRole("button", { name: "Clear pins" }));
    expect(
      screen.getByText(
        "Pin up to four configurations to compare their metrics and equipment.",
      ),
    ).toBeVisible();
    fireEvent.click(
      screen.getByRole("button", { name: "Pin selected configuration" }),
    );
    const selected = example.points.find((p) => p.id === example.selectedId)!;
    expect(
      screen.getByRole("article", { name: `Compare ${selected.label}` }),
    ).toBeVisible();
    fireEvent.click(
      screen.getByRole("button", { name: `Unpin ${selected.label}` }),
    );
    expect(
      screen.queryByRole("article", { name: `Compare ${selected.label}` }),
    ).not.toBeInTheDocument();
    expect(
      within(
        screen.getByRole("complementary", { name: "Selected configuration" }),
      ).getByRole("heading", { name: selected.label }),
    ).toBeVisible();
  });

  it("allows keyboard point selection, color-axis changes and full example table browsing", () => {
    render(<TradeoffLab />);
    const point = example.points.find((p) => p.id !== example.selectedId)!;
    fireEvent.keyDown(
      screen.getByRole("button", { name: `Parallel select ${point.label}` }),
      { key: "Enter" },
    );
    expect(
      screen.getByRole("button", { name: `Color select ${point.label}` }),
    ).toHaveAttribute("aria-pressed", "true");
    fireEvent.change(screen.getByLabelText("Color represents"), {
      target: { value: "dps" },
    });
    expect(
      screen.getByRole("group", {
        name: "Stab defense vs Prayer bonus, colored by DPS",
      }),
    ).toBeVisible();
    fireEvent.click(screen.getByText("Browse saved configurations"));
    expect(
      within(
        screen.getByRole("table", { name: "Saved example configurations" }),
      ).getAllByRole("row"),
    ).toHaveLength(example.points.length + 1);
  });
});
