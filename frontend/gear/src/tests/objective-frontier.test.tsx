import {
  act,
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
  expect(onSelect).toHaveBeenCalledWith(
    "sample",
    tradeoff,
    undefined,
    "group",
    undefined,
  );
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
    within(selectedRow).getByRole("button", { name: "Starting setup" }),
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
  const rowLabels = within(table)
    .getAllByRole("button")
    .map((button) => button.textContent);
  fireEvent.click(
    within(table).getByRole("button", { name: "Select setup 1" }),
  );
  await waitFor(() => expect(point).toHaveAttribute("aria-pressed", "true"));
  expect(selectedRow).toBeInTheDocument();
  expect(selectedRow).toHaveAttribute("aria-selected", "false");
  expect(
    within(table)
      .getAllByRole("button")
      .map((button) => button.textContent),
  ).toEqual(rowLabels);
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
  fireEvent.click(within(selectedRow).getByRole("button"));
  await waitFor(() =>
    expect(baselinePoint).toHaveAttribute("aria-pressed", "true"),
  );
  expect(point).toHaveAttribute("aria-pressed", "false");
  expect(
    within(table).getByRole("button", { name: "Starting setup" }),
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
    screen.getByRole("button", { name: "Starting setup" }),
  ).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  await screen.findByRole("button", { name: "Select setup 51" });
  const pinned = await screen.findByRole("button", {
    name: "Starting setup",
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
    screen.getByRole("button", { name: "Starting setup" }),
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
    expect(
      screen.getByRole("button", { name: "Starting setup" }),
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
    expect(
      screen.getByRole("button", { name: "Starting setup" }),
    ).toHaveAttribute("aria-pressed", "true");
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
  const link = screen.getByRole("link", { name: "Explore this run" });
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
  fireEvent.contextMenu(screen.getByRole("link", { name: "Explore this run" }));
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
      selectionRevision={3}
      onSelect={onSelect}
    />,
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Next page" })).toBeEnabled(),
  );
  await user.click(screen.getByRole("button", { name: "Select setup 1" }));
  expect(onSelect).toHaveBeenCalledWith(
    "unsampled",
    solution,
    "test-run",
    "group",
    3,
  );
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
  expect(onSelect).toHaveBeenCalledWith(
    "sample",
    solution,
    "test-run",
    "group",
    undefined,
  );
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

it("selects the cheapest point and the unpriced cap DPS winner independently", async () => {
  const cost = (dps: number, gp: number | null) => ({
    ...solution,
    score: dps,
    objective_values: { gp_per_damage: gp },
  });
  const [baseline, pricey, cheap] = [cost(12, null), cost(11, 3), cost(9, 0)];
  const scoped = {
    ...result,
    scenario: { request: { objectives: [{ kind: "gp_per_damage" }] } },
    live: {
      result: {
        objective_definitions: [
          {
            kind: "gp_per_damage",
            id: "gp_per_damage",
            label: "Running cost",
            unit: "GP/damage",
            direction: "minimize",
          },
        ],
        objective_frontiers: [
          {
            swap_limit: 0,
            baseline_dps: 12,
            baseline_solution: baseline,
            baseline_solution_id: "unpriced",
            points: [
              { id: "priced", solution: pricey },
              { id: "free", solution: cheap },
            ],
          },
        ],
      },
    },
    solutions: [{ id: "unpriced", live: baseline }],
  } as unknown as OptimizationReply;
  const onSelect = vi.fn();
  render(
    <ObjectiveFrontier
      result={scoped}
      swapLimit={0}
      selectedId="unpriced"
      onSelect={onSelect}
    />,
  );
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Lowest GP/damage" }));
  expect(onSelect).toHaveBeenLastCalledWith(
    "free",
    cheap,
    undefined,
    undefined,
    undefined,
  );
  await user.click(screen.getByRole("button", { name: "Highest DPS" }));
  expect(onSelect).toHaveBeenLastCalledWith(
    "unpriced",
    baseline,
    undefined,
    undefined,
    undefined,
  );
  await user.selectOptions(
    screen.getByLabelText("Sort tradeoffs"),
    "gp_per_damage",
  );
  expect(screen.getByLabelText("Sort direction")).toHaveValue("asc");
  expect(screen.getByRole("cell", { name: "Unavailable" })).toBeVisible();
});

it("starts a replacement run with the default sort and the first page", async () => {
  const fetcher = vi.fn(async (input: string) => {
    const url = new URL(input, location.href);
    return Response.json({
      points: [],
      total: 51,
      next_cursor: url.searchParams.has("cursor") ? null : "old-cursor",
    });
  });
  vi.stubGlobal("fetch", fetcher);
  const props = { swapLimit: 0, selectedId: "sample", onSelect: vi.fn() };
  const { rerender } = render(<ObjectiveFrontier {...props} result={result} />);
  const sort = screen.getByLabelText("Sort tradeoffs");
  fireEvent.change(sort, { target: { value: "prayer_bonus" } });
  fireEvent.change(screen.getByLabelText("Sort direction"), {
    target: { value: "asc" },
  });
  const next = screen.getByRole("button", { name: "Next page" });
  await waitFor(() => expect(next).toBeEnabled());
  fireEvent.click(next);
  await waitFor(() =>
    expect(fetcher.mock.calls.at(-1)?.[0]).toContain("cursor=old-cursor"),
  );
  const replacement = {
    ...result,
    scenario: {
      ...result.scenario,
      request: { ...result.scenario.request, objectives: [] },
    },
    live: {
      ...result.live!,
      run_id: "replacement",
      result: { ...result.live!.result, objective_definitions: [] },
    },
  };
  rerender(<ObjectiveFrontier {...props} result={replacement} />);
  await waitFor(() =>
    expect(fetcher.mock.calls.at(-1)?.[0]).toContain("/replacement/"),
  );
  expect(
    fetcher.mock.calls
      .map(([url]) => url)
      .filter((url) => url.includes("/replacement/")),
  ).toEqual([
    "/ui-api/gear/optimization-runs/replacement/frontiers/group/points?sort=dps&direction=desc&limit=50",
  ]);
  expect(screen.getByLabelText("Sort tradeoffs")).toHaveValue("dps");
  expect(screen.getByLabelText("Sort direction")).toHaveValue("desc");
});

it("retains the archive page when only the selected solution changes", async () => {
  const fetcher = vi.fn(async (_input: string) =>
    Response.json({
      points: [{ id: "sample", ...solution }],
      total: 1,
      next_cursor: null,
    }),
  );
  vi.stubGlobal("fetch", fetcher);
  const props = { swapLimit: 0, selectedId: "sample", onSelect: vi.fn() };
  const { rerender } = render(<ObjectiveFrontier {...props} result={result} />);
  const table = screen.getByRole("table", { name: "All objective tradeoffs" });
  await waitFor(() => expect(table).toHaveAttribute("aria-busy", "false"));
  rerender(
    <ObjectiveFrontier
      {...props}
      result={{ ...result, solutions: [...result.solutions] }}
    />,
  );
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it.each(["a new run", "a newer selection in the same run"])(
  "cancels a pending selection after %s",
  async (change) => {
    const onSelect = vi.fn();
    let resolveSelection!: (response: Response) => void;
    let selectionSignal: AbortSignal | null | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, options?: RequestInit) => {
        if (url.includes("/solutions/")) {
          selectionSignal = options?.signal;
          return new Promise<Response>(
            (resolve) => (resolveSelection = resolve),
          );
        }
        return Response.json({
          points: [{ id: "unsampled", ...solution }],
          total: 1,
          next_cursor: null,
        });
      }),
    );
    const props = { swapLimit: 0, selectedId: "sample", onSelect };
    const { rerender } = render(
      <ObjectiveFrontier {...props} result={result} selectionRevision={0} />,
    );
    const select = await screen.findByRole("button", {
      name: "Select setup 1",
    });
    fireEvent.click(select);
    expect(screen.getByRole("button", { name: "Highest DPS" })).toBeDisabled();
    const newRun = change === "a new run";
    rerender(
      <ObjectiveFrontier
        {...props}
        result={
          newRun
            ? {
                ...result,
                live: { ...result.live!, run_id: "replacement" },
              }
            : result
        }
        selectionRevision={newRun ? 0 : 1}
        selectedId={newRun ? "sample" : "lab-selection"}
        selectedSolution={
          newRun
            ? undefined
            : {
                ...result.live!.result.objective_frontiers![0].points[0]
                  .solution,
                score: 11,
              }
        }
      />,
    );
    expect(selectionSignal?.aborted).toBe(true);
    expect(screen.getByRole("button", { name: "Highest DPS" })).toBeEnabled();
    await act(async () => resolveSelection(Response.json({ solution })));
    expect(onSelect).not.toHaveBeenCalled();
    if (!newRun)
      expect(
        screen.getByRole("button", { name: /Select tradeoff lab-selection/ }),
      ).toHaveAttribute("aria-pressed", "true");
  },
);

it("compares the selection against its stable starting setup", async () => {
  const alternative = {
    ...solution,
    score: 9,
    purchase_cost_gp: 25,
    objective_values: { prayer_bonus: 8 },
    loadouts: {
      "role-1": {
        equipment: { weapon: 4151 },
        discipline: "melee",
        combat_option: { attack_type: "stab", stance: "accurate" },
      },
    },
  };
  const initial = {
    ...result,
    live: {
      ...result.live!,
      run_id: undefined,
      result: {
        ...result.live!.result,
        objective_frontiers: [
          {
            ...result.live!.result.objective_frontiers![0],
            points: [
              { id: "sample", solution },
              { id: "alternative", solution: alternative },
            ],
          },
        ],
      },
    },
  } as unknown as OptimizationReply;
  const props = { result: initial, swapLimit: 0, onSelect: vi.fn() };
  const { rerender } = render(
    <ObjectiveFrontier {...props} selectedId="sample" />,
  );
  const withinSummary = within(
    screen.getByRole("region", { name: "Selected setup comparison" }),
  );
  expect(withinSummary.getByText(/starting setup/i)).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Starting setup" }),
  ).toHaveAttribute("aria-pressed", "true");
  rerender(<ObjectiveFrontier {...props} selectedId="alternative" />);
  expect(withinSummary.getByText("9.000")).toBeVisible();
  expect(withinSummary.getByText("−1.000")).toBeVisible();
  expect(withinSummary.getByText("25 GP")).toBeVisible();
  expect(withinSummary.getByText("Melee")).toBeVisible();
  const changes = withinSummary.getByText("Gear and combat changes · 2");
  fireEvent.click(changes);
  expect(withinSummary.getByText(/Empty → Item #4151/)).toBeVisible();
  expect(
    withinSummary.getByText(/slash · accurate → stab · accurate/),
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Starting setup" }),
  ).toHaveAttribute("aria-pressed", "false");
});
