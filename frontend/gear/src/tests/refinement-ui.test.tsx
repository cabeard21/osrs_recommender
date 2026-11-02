import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ItemInspector } from "../components/ItemInspector";
import { TrialComparison } from "../components/TrialComparison";
import { PurchaseListCopy } from "../components/PurchaseListCopy";
import { useGear } from "../state/GearProvider";
import { newDraft, normalize } from "../state/scenario";
import { emptyEquipment, type Trial } from "../api/contracts";
import { parseContext, parseItem } from "../api/httpClient";
import context from "./live-context.json";

vi.mock("../state/GearProvider", () => ({ useGear: vi.fn() }));
const performance = {
  supported: true,
  dps: 3.5,
  max_hit: 15,
  accuracy: 0.7,
  attack_interval: 2.4,
  bonuses: {},
  limitations: [],
};
const trialExample = () =>
  ({
    source: "live",
    resultFingerprint: "original",
    solutionId: "best-found",
    roleId: "role-1",
    equipment: { ...emptyEquipment(), weapon: 1333, shield: 12954 },
    baseline: null,
    proposed: null,
    live: {
      api_version: "gear-ui-v1",
      scenario: {},
      assumptions_fingerprint: "assumptions",
      snapshot_id: context.account.snapshot_id,
      evaluated_at: context.evaluated_at,
      catalog_version: context.catalog_version,
      model_version: context.model_version,
      price_revision: context.price_revision,
      scenario_fingerprint: "original",
      items: context.items,
      baseline: {
        status: "valid",
        equipment: { weapon: 4151, shield: 12954 },
        performance,
        reasons: [],
        purchases: [],
        purchase_cost_gp: 0,
        assumed_item_ids: [],
      },
      proposed: {
        status: "valid",
        equipment: { weapon: 1333, shield: 12954 },
        performance: { ...performance, dps: 2.5 },
        reasons: [],
        purchases: [{ item_id: 1333, cost_gp: 15000, conditional: true }],
        purchase_cost_gp: 15000,
        assumed_item_ids: [],
      },
      deltas: {
        dps: -1,
        max_hit: 0,
        accuracy: 0,
        attack_interval: 0,
        purchase_cost_gp: 15000,
        equipment_changes: [
          { slot: "weapon", baseline_item_id: 4151, proposed_item_id: 1333 },
        ],
        added_purchase_ids: [1333],
        removed_purchase_ids: [],
      },
    },
  }) as Extract<Trial, { source: "live" }>;

function setupInspector({
  locked = false,
  outdated = false,
  exclusions = [] as number[],
  trialPending = false,
  trialError = null as string | null,
  trial = null as Trial | null,
} = {}) {
  const item = parseItem(context.items[0]);
  const alternative = { ...item, id: 1333, name: "Rune scimitar" };
  const draft = newDraft();
  draft.exclusions = exclusions;
  if (locked) draft.roles[0].locks = { weapon: 4151 };
  const equipment = { ...emptyEquipment(), weapon: 4151, shield: 12954 };
  const previewTrial = vi.fn(async () => undefined);
  const edit = vi.fn();
  const result = {
    source: "live",
    scenario: normalize(draft, context.account.snapshot_id),
    items: [item, alternative],
    solutions: [
      { id: "best-found", loadouts: [{ roleId: "role-1", equipment }] },
    ],
    live: {
      result: {
        alternatives: {
          weapon: [
            {
              item_id: 1333,
              score: 2.5,
              score_delta: -1,
              purchase_cost_gp: 15000,
            },
          ],
        },
      },
    },
  };
  vi.mocked(useGear).mockReturnValue({
    liveMode: true,
    state: { mode: "single", context: parseContext(context) },
    current: {
      slot: "weapon",
      activeRole: "role-1",
      solutionId: "best-found",
      draft,
      result,
      pending: false,
      outdated,
      trial,
      trialPending,
      trialError,
    },
    client: {
      getItem: vi.fn(async (id: number) => (id === 1333 ? alternative : item)),
      browseItems: vi.fn(async () => ({
        items: [alternative],
        total: 1,
        nextOffset: null,
      })),
    },
    dispatch: vi.fn(),
    edit,
    previewTrial,
    revertTrial: vi.fn(),
    cancelTrial: vi.fn(),
    itemById: (id: number | null) =>
      [item, alternative].find((row) => row.id === id),
  } as unknown as ReturnType<typeof useGear>);
  render(<ItemInspector />);
  return { previewTrial, edit, equipment, result };
}

it("previews contextual replacements from an unchanged accepted loadout", async () => {
  const user = userEvent.setup();
  const { previewTrial, equipment, result, edit } = setupInspector();
  await user.click(
    await screen.findByRole("button", { name: "Try Rune scimitar" }),
  );
  expect(previewTrial).toHaveBeenCalledWith({ ...equipment, weapon: 1333 });
  expect(result.solutions[0].loadouts[0].equipment).toEqual(equipment);
  expect(edit).not.toHaveBeenCalled();
});

it("uses an explicit unlock-and-exclude draft action", async () => {
  const user = userEvent.setup();
  const { edit } = setupInspector({ locked: true });
  await user.click(
    await screen.findByRole("button", { name: "Unlock and exclude in draft" }),
  );
  expect(edit.mock.calls[0][0].roles[0].locks).toEqual({});
  expect(edit.mock.calls[0][0].exclusions).toEqual([4151]);
});

it("blocks previews from an outdated result but still inspects items", async () => {
  const user = userEvent.setup();
  const { previewTrial } = setupInspector({ outdated: true });
  await user.click(
    await screen.findByRole("button", { name: "Try Rune scimitar" }),
  );
  expect(previewTrial).not.toHaveBeenCalled();
  expect(
    screen.getByRole("button", { name: "Preview empty slot" }),
  ).toBeDisabled();
  expect(
    screen.getByText(/Re-run before previewing alternatives/),
  ).toBeVisible();
});

it("locks an inspected alternative only in the draft", async () => {
  const user = userEvent.setup();
  const { edit, previewTrial, equipment, result } = setupInspector();
  const region = within(
    screen.getByRole("region", { name: "Contextual alternatives" }),
  );
  await user.click(region.getByRole("button", { name: "Try Rune scimitar" }));
  await screen.findByRole("heading", { name: "Rune scimitar" });
  await user.click(
    screen.getByRole("button", { name: "Lock weapon to Rune scimitar" }),
  );
  expect(edit.mock.calls[0][0].roles[0].locks).toEqual({ weapon: 1333 });
  expect(result.solutions[0].loadouts[0].equipment).toEqual(equipment);
  expect(previewTrial).toHaveBeenCalledWith({ ...equipment, weapon: 1333 });
});

it("filters exclusions from alternatives and requires correction before locking an excluded item", async () => {
  setupInspector({ exclusions: [4151, 1333] });
  expect(
    await screen.findByRole("button", { name: /^Lock weapon to / }),
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Exclude item in draft" }),
  ).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: "Try Rune scimitar" }),
  ).not.toBeInTheDocument();
});

it("provides cancellation while a manual evaluation runs", async () => {
  const user = userEvent.setup();
  setupInspector({
    trialPending: true,
    trialError: "Evaluation could not complete.",
  });
  await user.click(screen.getByRole("button", { name: "Cancel evaluation" }));
  expect(useGear().cancelTrial).toHaveBeenCalledOnce();
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Evaluation could not complete.",
  );
});

it("keeps keyboard focus inside the inspector when a trial lock clears its controls", async () => {
  const user = userEvent.setup();
  setupInspector({ trial: trialExample() });
  await user.click(
    screen.getByRole("button", { name: "Lock trial alternative in draft" }),
  );
  expect(
    screen.getByRole("button", { name: "Close Item inspector" }),
  ).toHaveFocus();
  await user.keyboard("{Escape}");
  expect(useGear().dispatch).toHaveBeenCalledWith({
    type: "ui",
    mode: "single",
    patch: { slot: null },
  });
});

it("shows exact comparisons and trial purchases without relabeling the recommendation", async () => {
  const user = userEvent.setup();
  const revert = vi.fn(),
    lock = vi.fn();
  render(
    <TrialComparison
      trial={trialExample()}
      onRevert={revert}
      onLock={lock}
      itemName={(id) => `Item #${id}`}
    />,
  );
  const comparison = within(
    screen.getByRole("table", { name: "Manual trial comparison" }),
  );
  expect(comparison.getByText("DPS")).toBeVisible();
  expect(comparison.getByText("-1.00")).toBeVisible();
  expect(comparison.getByText("+15,000 GP")).toBeVisible();
  expect(
    screen.getByText(/ownership uncertain/, { selector: "span" }),
  ).toBeVisible();
  expect(screen.getByText(/weapon: Item #4151 → Item #1333/)).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Clear preview" }));
  expect(revert).toHaveBeenCalledOnce();
  await user.click(
    screen.getByRole("button", { name: "Lock trial alternative in draft" }),
  );
  expect(lock).toHaveBeenCalledOnce();
});

it("shows invalid trial explanations with no numeric comparison", () => {
  const trial = trialExample();
  trial.live.proposed.status = "invalid";
  trial.live.proposed.performance = null;
  trial.live.proposed.reasons = [
    {
      path: "proposed.weapon",
      message: "Two-handed weapon cannot be equipped with a shield.",
    },
  ];
  trial.live.deltas = null;
  render(
    <TrialComparison
      trial={trial}
      onRevert={vi.fn()}
      onLock={vi.fn()}
      itemName={(id) => `Item #${id}`}
    />,
  );
  expect(screen.getByText(/Two-handed weapon/)).toBeVisible();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Lock trial alternative in draft" }),
  ).toBeDisabled();
});

it("preserves unsupported explanations, unknown costs and hypothetical acquisitions", () => {
  const trial = trialExample();
  trial.live.baseline.status = "unsupported";
  trial.live.baseline.performance = null;
  trial.live.baseline.reasons = [
    { path: "baseline", message: "Unsupported weapon effect." },
  ];
  trial.live.proposed.status = "unsupported";
  trial.live.proposed.performance = null;
  trial.live.proposed.purchase_cost_gp = null;
  trial.live.proposed.purchases[0].cost_gp = null;
  trial.live.proposed.assumed_item_ids = [1333];
  trial.live.deltas = null;
  render(
    <TrialComparison
      trial={trial}
      onRevert={vi.fn()}
      onLock={vi.fn()}
      itemName={(id) => `Item #${id}`}
    />,
  );
  expect(
    screen.getByText("Original: Unsupported weapon effect."),
  ).toBeVisible();
  expect(screen.getByText("Total acquisition cost unavailable.")).toBeVisible();
  expect(screen.getByText(/Hypothetically acquired IDs: 1333/)).toBeVisible();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});

it("reports successful copy of an empty acquisition list", async () => {
  const user = userEvent.setup();
  const copy = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
  render(<PurchaseListCopy purchases={[]} itemName={(id) => `Item #${id}`} />);
  await user.click(screen.getByRole("button", { name: "Copy purchase list" }));
  expect(copy).toHaveBeenCalledWith("No additional purchases required.");
  expect(await screen.findByRole("status")).toHaveTextContent(
    "Purchase list copied.",
  );
});

it("copies real purchase IDs and reports clipboard failure", async () => {
  const user = userEvent.setup();
  const copy = vi
    .spyOn(navigator.clipboard, "writeText")
    .mockRejectedValue(new Error("Denied"));
  render(
    <PurchaseListCopy
      purchases={[{ item_id: 1333, cost_gp: 15000, conditional: true }]}
      itemName={() => "Rune scimitar"}
    />,
  );
  await user.click(screen.getByRole("button", { name: "Copy purchase list" }));
  expect(copy).toHaveBeenCalledWith(
    expect.stringContaining("Rune scimitar (#1333)"),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(/Could not copy/);
  expect(screen.getByText(/Rune scimitar \(#1333\)/)).toBeVisible();
});
