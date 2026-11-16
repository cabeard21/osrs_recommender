import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { PotionTimelinePanel } from "../components/PotionTimelinePanel";
import type {
  GearClient,
  JointSolutionDTO,
  OptimizationReply,
  PotionTimeline,
} from "../api/contracts";

const result = {
  source: "live",
  snapshotId: "s",
  catalogVersion: "c",
  modelVersion: "m",
  scenario: {
    request: {
      secondary_priority: "accuracy",
      roles: [{ id: "r", name: "Melee" }],
    },
  },
} as unknown as OptimizationReply;
const solution = {
  score: 5,
  potions: { selected_ids: ["super_strength"] },
  loadouts: { r: { equipment: { weapon: 1 } } },
} as unknown as JointSolutionDTO;
const sample = (
  time_seconds: number,
  dps: number | null,
  secondary_value = 0.5,
) => ({
  time_seconds,
  levels: { strength: 99 },
  dps,
  secondary_value,
  roles: {
    r: {
      dps,
      secondary_value,
      reasons: dps === null ? ["Spell level too low"] : [],
    },
  },
});
const timeline = {
  baseline: sample(0, 4),
  samples: [sample(0, 5), sample(60, 4.5), sample(120, null)],
  secondary_priority: "accuracy",
} as unknown as PotionTimeline;

it("switches independent objective decay charts without recalculating the setup", async () => {
  const measure = (time: number, prayer: number, accuracy: number) => ({
    ...sample(time, 5),
    objective_values: { prayer_bonus: prayer, accuracy },
  });
  const data = {
    ...timeline,
    secondary_priority: "default",
    objective_definitions: [
      {
        id: "prayer_bonus",
        kind: "prayer_bonus",
        label: "Prayer bonus",
        unit: "bonus",
      },
      {
        id: "accuracy",
        kind: "accuracy",
        label: "Accuracy",
        unit: "probability",
      },
    ],
    baseline: measure(0, 5, 0.5),
    samples: [measure(0, 5, 0.6), measure(60, 5, 0.5)],
  };
  const calculate = vi.fn().mockResolvedValue(data);
  render(
    <PotionTimelinePanel
      result={result}
      solution={solution}
      client={{ potionTimeline: calculate } as unknown as GearClient}
    />,
  );
  expect(
    await screen.findByRole("img", { name: "Prayer bonus (bonus) over time" }),
  ).toBeVisible();
  await userEvent.selectOptions(
    screen.getByLabelText("Graph objective"),
    "accuracy",
  );
  expect(screen.getByRole("img", { name: "Accuracy over time" })).toBeVisible();
  expect(calculate).toHaveBeenCalledTimes(1);
});

it("labels both y-axes as relative percent gains while keeping exact point values", async () => {
  const data = {
    ...timeline,
    baseline: sample(0, 4, 0.5),
    samples: [sample(0, 5, 0.6), sample(60, 4, 0.5)],
  };
  render(
    <PotionTimelinePanel
      result={result}
      solution={solution}
      client={
        {
          potionTimeline: vi.fn().mockResolvedValue(data),
        } as unknown as GearClient
      }
    />,
  );
  const dps = await screen.findByRole("img", { name: "DPS over time" });
  expect(within(dps).getByText("+25.00%")).toHaveAttribute("y", "39");
  const accuracy = screen.getByRole("img", { name: "Accuracy over time" });
  expect(within(accuracy).getByText("+20.00%")).toHaveAttribute("y", "39");
  for (const chart of [dps, accuracy]) {
    expect(within(chart).getByText("0.00%")).toHaveAttribute("y", "159");
    expect(chart.querySelector('path[stroke-dasharray="5 5"]')).toHaveAttribute(
      "d",
      "M70 155 H570",
    );
    expect(chart.querySelectorAll("circle")[1]).toHaveAttribute("cy", "155");
    expect(chart.querySelectorAll("circle")[0]).toHaveAttribute("cy", "35");
  }
  expect(
    within(dps).getByText("0:00: 5.000 · No stat boosts"),
  ).toBeInTheDocument();
  expect(
    screen.getAllByText(/Y-axis: % above unboosted baseline/),
  ).toHaveLength(2);
});

it.each([0, null])(
  "uses an explained absolute scale when baseline is %s",
  async (baseline) => {
    const data = {
      ...timeline,
      baseline: sample(0, baseline),
      samples: [sample(0, 5), sample(60, 4)],
    };
    render(
      <PotionTimelinePanel
        result={result}
        solution={solution}
        client={
          {
            potionTimeline: vi.fn().mockResolvedValue(data),
          } as unknown as GearClient
        }
      />,
    );
    const chart = await screen.findByRole("img", { name: "DPS over time" });
    expect(within(chart).getByText("5.000")).toBeInTheDocument();
    expect(
      screen.getByText(/Percentage gain unavailable.*showing absolute values/),
    ).toBeVisible();
    expect(chart.innerHTML).not.toMatch(/NaN|Infinity/);
  },
);

it("zooms each y-axis to its plotted range, including the unboosted baseline", async () => {
  const data = {
    ...timeline,
    baseline: sample(0, 4.007, 0.5),
    samples: [
      sample(0, 4.628, 0.55),
      sample(60, 4.3, 0.53),
      sample(120, 4.007, 0.5),
    ],
  };
  render(
    <PotionTimelinePanel
      result={result}
      solution={solution}
      client={
        {
          potionTimeline: vi.fn().mockResolvedValue(data),
        } as unknown as GearClient
      }
    />,
  );
  for (const label of ["DPS over time", "Accuracy over time"]) {
    const chart = await screen.findByRole("img", { name: label });
    const points = chart.querySelectorAll("circle");
    const firstY = Number(points[0].getAttribute("cy"));
    const lastY = Number(points[2].getAttribute("cy"));
    expect(lastY - firstY).toBeGreaterThan(85);
    expect(firstY).toBe(35);
    expect(lastY).toBe(155);
    expect(within(chart).queryByText("0.000")).toBeNull();
  }
});

it.each([0, 5, -5])(
  "keeps a finite y-axis for a constant value %s",
  async (value) => {
    const data = {
      ...timeline,
      baseline: sample(0, value),
      samples: [sample(0, value), sample(60, value)],
    };
    render(
      <PotionTimelinePanel
        result={result}
        solution={solution}
        client={
          {
            potionTimeline: vi.fn().mockResolvedValue(data),
          } as unknown as GearClient
        }
      />,
    );
    const chart = await screen.findByRole("img", { name: "DPS over time" });
    for (const point of chart.querySelectorAll("circle")) {
      const y = Number(point.getAttribute("cy"));
      expect(Number.isFinite(y)).toBe(true);
      expect(y).toBeGreaterThanOrEqual(35);
      expect(y).toBeLessThanOrEqual(155);
    }
    expect(chart.innerHTML).not.toMatch(/NaN|Infinity/);
    if (value !== 0)
      expect(chart.querySelectorAll('text[text-anchor="end"]')).toHaveLength(1);
  },
);

it("shows remaining stat bonuses at every point and when hovering or selecting time", async () => {
  const data = {
    ...timeline,
    baseline: {
      ...sample(0, 4),
      levels: { strength: 99, defence: 80, magic: 75 },
    },
    samples: [
      { ...sample(0, 5), levels: { strength: 108, defence: 89, magic: 75 } },
      { ...sample(60, 4.5), levels: { strength: 107, defence: 88, magic: 75 } },
      { ...sample(300, 4), levels: { strength: 99, defence: 80, magic: 75 } },
    ],
  };
  render(
    <PotionTimelinePanel
      result={result}
      solution={solution}
      client={
        {
          potionTimeline: vi.fn().mockResolvedValue(data),
        } as unknown as GearClient
      }
    />,
  );
  const chart = await screen.findByRole("img", { name: "DPS over time" });
  expect(
    within(chart).getByText("0:00: 5.000 · +9 Str · +9 Def"),
  ).toBeInTheDocument();
  expect(
    within(chart).getByText("1:00: 4.500 · +8 Str · +8 Def"),
  ).toBeInTheDocument();
  expect(
    within(chart).getByText("5:00: 4.000 · +0 Str · +0 Def"),
  ).toBeInTheDocument();
  fireEvent.mouseEnter(chart.querySelectorAll("circle")[1]);
  expect(screen.getByText("Remaining boosts: +8 Str · +8 Def")).toBeVisible();
  await userEvent.selectOptions(screen.getByLabelText("Inspect time"), "2");
  expect(screen.getByText("Remaining boosts: +0 Str · +0 Def")).toBeVisible();
  const table = screen.getByRole("table", { name: "Potion decay values" });
  expect(
    within(table).getByRole("columnheader", { name: "Stat boosts" }),
  ).toBeInTheDocument();
  expect(within(table).getByText("+9 Str · +9 Def")).toBeInTheDocument();
  expect(within(table).queryByText(/Mag/)).toBeNull();
});

it("renders step graphs, baseline and keyboard-selectable event values", async () => {
  const client = {
    potionTimeline: vi.fn().mockResolvedValue(timeline),
  } as unknown as GearClient;
  const user = userEvent.setup();
  render(
    <PotionTimelinePanel result={result} solution={solution} client={client} />,
  );
  expect(
    await screen.findByRole("img", { name: "DPS over time" }),
  ).toBeVisible();
  expect(screen.getByRole("img", { name: "Accuracy over time" })).toBeVisible();
  await user.selectOptions(screen.getByLabelText("Inspect time"), "2");
  expect(screen.getAllByText(/Spell level too low/).length).toBeGreaterThan(0);
  expect(
    screen.getByRole("table", { name: "Potion decay values" }),
  ).toBeInTheDocument();
  expect(screen.getAllByText(/Same gear, unboosted/).length).toBeGreaterThan(0);
});

it("retries failed requests and hides secondary graph for default priority", async () => {
  const load = vi
    .fn()
    .mockRejectedValueOnce(new Error("Busy"))
    .mockResolvedValue({ ...timeline, secondary_priority: "default" });
  render(
    <PotionTimelinePanel
      result={result}
      solution={solution}
      client={{ potionTimeline: load } as unknown as GearClient}
    />,
  );
  await screen.findByText("Busy");
  await userEvent.click(screen.getByRole("button", { name: "Retry graph" }));
  await screen.findByRole("img", { name: "DPS over time" });
  expect(screen.queryByRole("img", { name: "Accuracy over time" })).toBeNull();
});

it("aborts stale selections and does not display their responses", async () => {
  let resolve!: (value: PotionTimeline) => void;
  const load = vi
    .fn()
    .mockImplementationOnce(
      () =>
        new Promise<PotionTimeline>((r) => {
          resolve = r;
        }),
    )
    .mockResolvedValue(timeline);
  const client = { potionTimeline: load } as unknown as GearClient;
  const view = render(
    <PotionTimelinePanel result={result} solution={solution} client={client} />,
  );
  view.rerender(
    <PotionTimelinePanel
      result={result}
      solution={{ ...solution, score: 6 }}
      client={client}
    />,
  );
  await screen.findByRole("img", { name: "DPS over time" });
  resolve({ ...timeline, samples: [sample(0, 999)] });
  await waitFor(() => expect(load.mock.calls[0][2].aborted).toBe(true));
  expect(screen.queryByText("999.000")).toBeNull();
});

it("shows unavailable state for old configurations and stale results", () => {
  const view = render(
    <PotionTimelinePanel result={result} solution={solution} />,
  );
  expect(
    screen.getByText(/unavailable for this saved or demo result/),
  ).toBeVisible();
  view.rerender(
    <PotionTimelinePanel result={result} solution={solution} outdated />,
  );
  expect(screen.getByText(/Rerun optimization/)).toBeVisible();
});

it("marks divine expiry and never calls an interrupted curve constant", async () => {
  const data = {
    ...timeline,
    samples: [
      sample(0, 5),
      { ...sample(300, null), secondary_value: null },
      { ...sample(360, null), secondary_value: null },
    ],
  };
  render(
    <PotionTimelinePanel
      result={result}
      solution={{
        ...solution,
        potions: {
          ...solution.potions!,
          selected_ids: ["divine_super_strength"],
        },
      }}
      client={
        {
          potionTimeline: vi.fn().mockResolvedValue(data),
        } as unknown as GearClient
      }
    />,
  );
  expect(await screen.findAllByText("Divine expiry · 5:00")).toHaveLength(2);
  expect(screen.queryByText(/stays constant/)).toBeNull();
  expect(screen.getByText(/0.000 percentage points from fresh/)).toBeVisible();
});

it("shows weighted and role values and reuses cached configurations", async () => {
  const multiSample = {
    ...sample(0, 5),
    roles: {
      r: { dps: 4, secondary_value: 0.4, reasons: [] },
      other: { dps: 6, secondary_value: 0.6, reasons: [] },
    },
  };
  const data = {
    ...timeline,
    baseline: { ...multiSample, dps: null },
    samples: [multiSample, { ...multiSample, time_seconds: 60 }],
  };
  const load = vi.fn().mockResolvedValue(data);
  const client = { potionTimeline: load } as unknown as GearClient;
  const view = render(
    <PotionTimelinePanel result={result} solution={solution} client={client} />,
  );
  await screen.findByRole("img", { name: "Weighted DPS over time" });
  await userEvent.selectOptions(
    screen.getByLabelText("Graph configuration"),
    "r",
  );
  expect(screen.getByRole("img", { name: "DPS over time" })).toBeVisible();
  expect(screen.getAllByText(/stays constant/)).toHaveLength(2);
  view.rerender(
    <PotionTimelinePanel
      result={result}
      solution={solution}
      client={client}
      outdated
    />,
  );
  view.rerender(
    <PotionTimelinePanel result={result} solution={solution} client={client} />,
  );
  await screen.findByRole("img", { name: "Weighted DPS over time" });
  expect(load).toHaveBeenCalledTimes(1);
});
