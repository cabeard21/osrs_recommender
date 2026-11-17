import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { ObjectiveFrontier } from "../components/ObjectiveFrontier";
import type { OptimizationReply } from "../api/contracts";
import { loadLabSnapshot } from "../tradeoff-lab/snapshot";

afterEach(() => vi.unstubAllGlobals());

it("lists the default defence-roll setup separately from a tradeoff with the same DPS", () => {
  const baseline = {
    ...solution,
    score: 4.093,
    objective_values: { "defence_roll:minimum:stab": 22792 },
  };
  const tradeoff = {
    ...baseline,
    objective_values: { "defence_roll:minimum:stab": 27100 },
  };
  const scoped = {
    ...result,
    scenario: {
      ...result.scenario,
      request: {
        ...result.scenario.request,
        objectives: [
          { kind: "defence_roll", styles: ["stab"], aggregation: "minimum" },
        ],
      },
    },
    live: {
      ...result.live!,
      run_id: undefined,
      result: {
        ...result.live!.result,
        selected_solution: baseline,
        objective_definitions: [
          {
            id: "defence_roll:minimum:stab",
            kind: "defence_roll",
            label: "Stab defence roll (minimum)",
            unit: "roll",
          },
        ],
        objective_frontiers: [
          {
            ...result.live!.result.objective_frontiers![0],
            points: [
              {
                id: "sample",
                solution: tradeoff,
                dps_loss: 0,
                dps_loss_pct: 0,
              },
              {
                id: "defence",
                solution: {
                  ...tradeoff,
                  score: 3.5,
                  objective_values: { "defence_roll:minimum:stab": 37048 },
                },
                dps_loss: 0.593,
                dps_loss_pct: 14.49,
              },
            ],
          },
        ],
      },
    },
  } as unknown as OptimizationReply;
  const onSelect = vi.fn();
  render(
    <ObjectiveFrontier
      result={scoped}
      swapLimit={0}
      selectedId="best-found"
      onSelect={onSelect}
    />,
  );
  const table = screen.getByRole("table", { name: "All objective tradeoffs" });
  const row = within(table).getByRole("row", { selected: true });
  expect(within(row).getByRole("cell", { name: "22.79k" })).toBeVisible();
  expect(within(row).getByRole("cell", { name: "4.093" })).toBeVisible();
  expect(within(table).getByRole("cell", { name: "27.10k" })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Highest DPS" }));
  expect(onSelect).toHaveBeenCalledWith("sample", tradeoff);
});

it("highlights the starting setup and preserves chart points and bounds when selecting tradeoffs", async () => {
  const baseline = { ...solution, objective_values: { prayer_bonus: 2 } };
  const initial = {
    ...result,
    solutions: [{ id: "best-found", live: baseline }],
  } as unknown as OptimizationReply;
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            points: [{ id: "sample", ...solution }],
            total: 1,
            next_cursor: null,
          }),
          { status: 200 },
        ),
    ),
  );
  function Selection() {
    const [id, setId] = useState("best-found");
    return (
      <ObjectiveFrontier
        result={initial}
        swapLimit={0}
        selectedId={id}
        onSelect={setId}
      />
    );
  }
  render(<Selection />);
  const table = screen.getByRole("table", { name: "All objective tradeoffs" });
  const selectedRow = within(table).getByRole("row", { selected: true });
  expect(
    within(selectedRow).getByRole("button", { name: "Current selection" }),
  ).toHaveAttribute("aria-pressed", "true");
  expect(
    within(selectedRow).getByRole("cell", { name: "2.000" }),
  ).toBeVisible();
  await waitFor(() => expect(table).toHaveAttribute("aria-busy", "false"));
  expect(within(table).getAllByRole("row", { selected: true })).toHaveLength(1);
  const baselinePoint = screen.getByRole("button", {
    name: /Select tradeoff best-found,/,
  });
  expect(baselinePoint).toHaveAttribute("aria-pressed", "true");
  const point = screen.getByRole("button", { name: /Select tradeoff sample,/ });
  const position = [point.getAttribute("cx"), point.getAttribute("cy")];
  const chart = screen.getByRole("group", { name: "DPS vs Prayer bonus" });
  const ticks = Array.from(
    chart.querySelectorAll("text"),
    (node) => node.textContent,
  );
  fireEvent.click(point);
  await waitFor(() => expect(point).toHaveAttribute("aria-pressed", "true"));
  expect(
    screen.queryByRole("button", { name: "Current selection" }),
  ).not.toBeInTheDocument();
  expect(
    within(table).getByRole("button", { name: "Select setup 1" }),
  ).toHaveAttribute("aria-pressed", "true");
  expect(baselinePoint).toBeInTheDocument();
  expect(baselinePoint).toHaveAttribute("aria-pressed", "false");
  expect([point.getAttribute("cx"), point.getAttribute("cy")]).toEqual(
    position,
  );
  expect(
    Array.from(chart.querySelectorAll("text"), (node) => node.textContent),
  ).toEqual(ticks);
  fireEvent.click(baselinePoint);
  await waitFor(() =>
    expect(baselinePoint).toHaveAttribute("aria-pressed", "true"),
  );
  expect(point).toHaveAttribute("aria-pressed", "false");
  expect(
    within(table).getByRole("button", { name: "Current selection" }),
  ).toHaveAttribute("aria-pressed", "true");
});

it("keeps a selected chart configuration visible while browsing and sorting other table results", async () => {
  const fetcher = vi.fn(
    async (input: string) =>
      new Response(
        JSON.stringify({
          points:
            input.includes("cursor=") || input.includes("direction=asc")
              ? [{ id: "other", ...solution, score: 8 }]
              : [{ id: "sample", ...solution }],
          total: 51,
          next_cursor: input.includes("cursor=") ? null : "next",
        }),
        { status: 200 },
      ),
  );
  vi.stubGlobal("fetch", fetcher);
  render(
    <ObjectiveFrontier
      result={result}
      swapLimit={0}
      selectedId="sample"
      onSelect={() => {}}
    />,
  );
  const table = screen.getByRole("table", { name: "All objective tradeoffs" });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Next page" })).toBeEnabled(),
  );
  expect(within(table).getAllByRole("row", { selected: true })).toHaveLength(1);
  expect(
    screen.queryByRole("button", { name: "Current selection" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  await screen.findByRole("button", { name: "Select setup 51" });
  const pinned = await screen.findByRole("button", {
    name: "Current selection",
  });
  expect(pinned).toHaveAttribute("aria-pressed", "true");
  expect(
    within(pinned.closest("tr")!).getByRole("cell", {
      name: "10.000",
    }),
  ).toBeVisible();
  fireEvent.change(screen.getByRole("combobox", { name: "Sort direction" }), {
    target: { value: "asc" },
  });
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(([url]) => url.includes("direction=asc")),
    ).toBe(true),
  );
  await waitFor(() => expect(table).toHaveAttribute("aria-busy", "false"));
  expect(
    screen.getByRole("button", { name: "Current selection" }),
  ).toHaveAttribute("aria-pressed", "true");
  expect(
    screen.getByRole("button", { name: "Select setup 1" }),
  ).toHaveAttribute("aria-pressed", "false");
  expect(within(table).getAllByRole("row", { selected: true })).toHaveLength(1);
});

it.each(["run", "group", "swap limit"])(
  "retains unsampled selections until the %s changes",
  (scope) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              points: [],
              total: 0,
              next_cursor: null,
            }),
            { status: 200 },
          ),
      ),
    );
    const unsampled = {
      ...solution,
      score: 8,
      objective_values: { prayer_bonus: 8 },
    };
    const selectedResult = {
      ...result,
      solutions: [{ id: "unsampled", live: unsampled }],
    } as unknown as OptimizationReply;
    const props = { result: selectedResult, swapLimit: 0, onSelect: vi.fn() };
    const { rerender } = render(
      <ObjectiveFrontier {...props} selectedId="unsampled" />,
    );
    const point = screen.getByRole("button", {
      name: /Select tradeoff sample,/,
    });
    const position = [point.getAttribute("cx"), point.getAttribute("cy")];
    rerender(<ObjectiveFrontier {...props} selectedId="sample" />);
    expect(
      screen.getByRole("button", { name: /Select tradeoff unsampled,/ }),
    ).toHaveAttribute("aria-pressed", "false");
    expect([point.getAttribute("cx"), point.getAttribute("cy")]).toEqual(
      position,
    );
    const next = {
      ...selectedResult,
      live: {
        ...selectedResult.live!,
        run_id: scope === "run" ? "next-run" : selectedResult.live!.run_id,
        result: {
          ...selectedResult.live!.result,
          objective_frontiers: [
            {
              ...selectedResult.live!.result.objective_frontiers![0],
              id: scope === "group" ? "next-group" : "group",
              swap_limit: scope === "swap limit" ? 1 : 0,
            },
          ],
        },
      },
    };
    rerender(
      <ObjectiveFrontier
        {...props}
        result={next}
        swapLimit={scope === "swap limit" ? 1 : 0}
        selectedId="sample"
      />,
    );
    expect(
      screen.queryByRole("button", { name: /Select tradeoff unsampled,/ }),
    ).not.toBeInTheDocument();
  },
);

it("opens the full lab with the current scoped result and selected point", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({ points: [], total: 51, next_cursor: null }),
          { status: 200 },
        ),
    ),
  );
  render(
    <ObjectiveFrontier
      result={result}
      swapLimit={0}
      selectedId="sample"
      onSelect={() => {}}
    />,
  );
  const link = screen.getByRole("link", { name: /Open full tradeoff lab/ });
  fireEvent.contextMenu(link);
  const url = new URL(link.getAttribute("href")!, location.href);
  expect(url.searchParams.get("view")).toBe("tradeoff-lab");
  const data = loadLabSnapshot(url.searchParams.get("session")!);
  expect(data.selectedId).toBe("sample");
  expect(data.points[0].values).toEqual({ dps: 10, prayer_bonus: 5 });
  expect(data.sampled).toBe(true);
  expect(data.totalCount).toBe(51);
  expect(data.scope).toContain("0");
});

it("keeps the result visible and explains blocked browser storage", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({ points: [], total: 51, next_cursor: null }),
          { status: 200 },
        ),
    ),
  );
  render(
    <ObjectiveFrontier
      result={result}
      swapLimit={0}
      selectedId="sample"
      onSelect={() => {}}
    />,
  );
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("Storage blocked");
  });
  fireEvent.contextMenu(
    screen.getByRole("link", { name: /Open full tradeoff lab/ }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    /storage|save|store/i,
  );
  expect(
    screen.getByRole("table", { name: "All objective tradeoffs" }),
  ).toBeVisible();
});

it("formats magic damage percentage points without multiplying by 100", async () => {
  const raw = { ...solution, objective_values: { magic_damage_bonus: 3.5 } };
  const magic = {
    ...result,
    scenario: { request: { objectives: [{ kind: "magic_damage_bonus" }] } },
    live: {
      run_id: "magic-run",
      result: {
        objective_definitions: [
          {
            id: "magic_damage_bonus",
            kind: "magic_damage_bonus",
            label: "Magic damage",
            unit: "percent",
          },
        ],
        objective_frontiers: [
          {
            id: "magic",
            swap_limit: 0,
            baseline_dps: 10,
            sampled: false,
            total_count: 1,
            points: [
              { id: "sample", solution: raw, dps_loss: 0, dps_loss_pct: 0 },
            ],
          },
        ],
      },
    },
  } as unknown as OptimizationReply;
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            points: [{ id: "sample", ...raw }],
            total: 1,
            next_cursor: null,
          }),
          { status: 200 },
        ),
    ),
  );
  render(
    <ObjectiveFrontier
      result={magic}
      swapLimit={0}
      selectedId="sample"
      onSelect={() => {}}
    />,
  );
  expect(await screen.findByRole("cell", { name: "3.50%" })).toBeVisible();
});
const solution = {
  score: 10,
  objective_values: { prayer_bonus: 5 },
  purchase_cost_gp: 0,
  maximum_actions: 0,
  loadouts: {
    "role-1": {
      equipment: {},
      combat_option: { attack_type: "slash", stance: "accurate" },
    },
  },
};
const result = {
  evaluatedAt: "2026-11-16T16:48:56Z",
  scenario: {
    request: {
      objectives: [{ kind: "prayer_bonus" }],
      roles: [{ id: "role-1", name: "Melee" }],
      budget_gp: 1000,
      target: { name: "Test target" },
    },
  },
  solutions: [],
  live: {
    run_id: "test-run",
    result: {
      objective_definitions: [
        {
          id: "prayer_bonus",
          kind: "prayer_bonus",
          label: "Prayer bonus",
          unit: "bonus",
        },
      ],
      objective_frontiers: [
        {
          id: "group",
          swap_limit: 0,
          baseline_dps: 10,
          sampled: true,
          total_count: 51,
          points: [{ id: "sample", solution, dps_loss: 0, dps_loss_pct: 0 }],
        },
      ],
    },
  },
} as unknown as OptimizationReply;
it("paginates all results and selects a complete unsampled solution", async () => {
  const user = userEvent.setup(),
    onSelect = vi.fn();
  const fetcher = vi.fn(
    async (input: string) =>
      new Response(
        JSON.stringify(
          input.includes("/solutions/")
            ? { solution }
            : {
                points: [
                  {
                    id: input.includes("cursor=") ? "second" : "unsampled",
                    ...solution,
                  },
                ],
                total: 51,
                next_cursor: input.includes("cursor=") ? null : "next",
              },
        ),
        { status: 200 },
      ),
  );
  vi.stubGlobal("fetch", fetcher);
  render(
    <ObjectiveFrontier
      result={result}
      swapLimit={0}
      selectedId="sample"
      onSelect={onSelect}
    />,
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Next page" })).toBeEnabled(),
  );
  await user.click(screen.getByRole("button", { name: "Select setup 1" }));
  expect(onSelect).toHaveBeenCalledWith("unsampled", solution);
  await user.click(screen.getByRole("button", { name: "Next page" }));
  await screen.findByRole("button", { name: "Select setup 51" });
  expect(fetcher.mock.calls.some(([url]) => url.includes("cursor=next"))).toBe(
    true,
  );
});
it("changes chart axes locally without rerunning or changing selection", async () => {
  const onSelect = vi.fn(),
    fetcher = vi.fn(
      async () =>
        new Response(
          JSON.stringify({ points: [], total: 51, next_cursor: null }),
          { status: 200 },
        ),
    );
  vi.stubGlobal("fetch", fetcher);
  render(
    <ObjectiveFrontier
      result={result}
      swapLimit={0}
      selectedId="sample"
      onSelect={onSelect}
    />,
  );
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  fireEvent.change(screen.getByRole("combobox", { name: "Horizontal axis" }), {
    target: { value: "prayer_bonus" },
  });
  expect(onSelect).not.toHaveBeenCalled();
  expect(fetcher).toHaveBeenCalledTimes(1);
});
it("shows a clear expired-session error without replacing existing results", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: string) => new Response("{}", { status: 410 })),
  );
  render(
    <ObjectiveFrontier
      result={result}
      swapLimit={0}
      selectedId="sample"
      onSelect={() => {}}
    />,
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "session has expired",
  );
});
it("selects chart points by keyboard and sorts the full table", async () => {
  const user = userEvent.setup(),
    onSelect = vi.fn();
  const fetcher = vi.fn(
    async (_input: string) =>
      new Response(
        JSON.stringify({
          points: [{ id: "sample", ...solution }],
          total: 1,
          next_cursor: null,
        }),
        { status: 200 },
      ),
  );
  vi.stubGlobal("fetch", fetcher);
  render(
    <ObjectiveFrontier
      result={result}
      swapLimit={0}
      selectedId="sample"
      onSelect={onSelect}
    />,
  );
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  fireEvent.keyDown(
    screen.getByRole("button", { name: /Select tradeoff sample/ }),
    { key: "Enter" },
  );
  expect(onSelect).toHaveBeenCalledWith("sample", solution);
  await user.selectOptions(
    screen.getByRole("combobox", { name: "Sort tradeoffs" }),
    "prayer_bonus",
  );
  await user.selectOptions(
    screen.getByRole("combobox", { name: "Sort direction" }),
    "asc",
  );
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(([url]) => String(url).includes("direction=asc")),
    ).toBe(true),
  );
});
it("reports malformed result pages", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async (_input: string) =>
        new Response(
          JSON.stringify({ points: [], total: -1, next_cursor: null }),
          { status: 200 },
        ),
    ),
  );
  render(
    <ObjectiveFrontier
      result={result}
      swapLimit={0}
      selectedId="sample"
      onSelect={() => {}}
    />,
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Invalid objective result page",
  );
});
it("reports failed detail requests without selecting a different configuration", async () => {
  const user = userEvent.setup(),
    onSelect = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      url.includes("/solutions/")
        ? new Response("{}", { status: 500 })
        : new Response(
            JSON.stringify({
              points: [{ id: "unsampled", ...solution }],
              total: 1,
              next_cursor: null,
            }),
            { status: 200 },
          ),
    ),
  );
  render(
    <ObjectiveFrontier
      result={result}
      swapLimit={0}
      selectedId="sample"
      onSelect={onSelect}
    />,
  );
  await screen.findByRole("button", { name: "Select setup 1" });
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: "Next page" })).toBeDisabled(),
  );
  await user.click(screen.getByRole("button", { name: "Select setup 1" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Unable to load");
  expect(onSelect).not.toHaveBeenCalled();
});
