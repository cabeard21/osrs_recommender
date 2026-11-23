import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import type { Item, JointSolutionDTO, Preparation } from "../api/contracts";
import { AcquisitionChecklist } from "../components/AcquisitionChecklist";

const roles = [
  { id: "boss", name: "Boss" },
  { id: "adds", name: "Adds" },
];
const preparation: Preparation = {
  source_item_id: null,
  usable_item_id: 28585,
  market_item_id: 28583,
  charging_required: true,
  charges: "unknown",
  activation_reserve: [],
  message: "Charging required; actual charge availability is unknown.",
};
const loadout = {
  equipment: { weapon: 28585 },
  performance: {
    supported: true,
    dps: 4,
    max_hit: 15,
    accuracy: 0.8,
    attack_interval: 2.4,
    bonuses: {},
    limitations: [],
  },
  preparations: [preparation],
};
const selected: JointSolutionDTO = {
  score: 4,
  loadouts: { boss: loadout, adds: loadout },
  purchases: [{ item_id: 28583, cost_gp: 1000, conditional: true }],
  purchase_cost_gp: 1000,
  transitions: [],
  carried_item_ids: [28585],
  distinct_items: 1,
  gear_inventory_slots: 0,
  max_gear_inventory_slots: 0,
  remaining_supply_slots: 28,
  remaining_inventory_slots: 28,
  reserved_supply_slots: 0,
  maximum_actions: 0,
  running_cost: {
    status: "known",
    gp_per_damage: 2,
    gp_per_attack: 12,
    gp_per_hour: 9000,
    resources: [],
    reasons: [],
  },
};

const names: Record<number, string> = {
  28583: "Warped sceptre",
  28585: "Warped sceptre (charged)",
  27662: "Accursed sceptre (uncharged)",
  6570: "Fire cape",
};
function itemById(id: number): Item | undefined {
  if (!names[id]) return undefined;
  return {
    id,
    name: names[id],
    slot: id === 6570 ? "cape" : "weapon",
    owned: null,
    price: null,
    requirement: "",
  };
}

it("lists a shared purchase and preparation once, using the exact market and equipped forms", async () => {
  const user = userEvent.setup();
  const copy = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
  render(
    <AcquisitionChecklist
      solution={selected}
      roles={roles}
      itemById={itemById}
      selectionKey="first"
    />,
  );
  const buy = screen.getByRole("region", { name: "Buy" });
  expect(within(buy).getAllByRole("listitem")).toHaveLength(1);
  expect(buy).toHaveTextContent("Warped sceptre · 1,000 GP");
  expect(buy).toHaveTextContent(/conditional purchase.*Boss.*Adds/s);
  const prepare = screen.getByRole("region", { name: "Prepare" });
  expect(within(prepare).getAllByRole("listitem")).toHaveLength(1);
  expect(prepare).toHaveTextContent("Warped sceptre (#28583)");
  expect(prepare).toHaveTextContent("Warped sceptre (charged) (#28585)");
  expect(prepare).toHaveTextContent(preparation.message);
  expect(prepare).toHaveTextContent("Boss, Adds");
  expect(screen.getByText("9,000 GP/hour")).toBeVisible();

  await user.click(
    within(buy).getByRole("button", { name: "Copy purchase list" }),
  );
  expect(copy).toHaveBeenCalledWith(
    "Warped sceptre (#28583) · 1,000 GP · conditional purchase: ownership uncertain",
  );
  await user.click(
    within(screen.getByRole("group", { name: "Bank tag for Adds" })).getByRole(
      "button",
      { name: "Export mobile bank tag" },
    ),
  );
  expect(screen.getByRole("textbox", { name: "Bank tag code" })).toHaveValue(
    "1,1,28585,0,2",
  );
});

it("shows untradeables and known Wilderness loss with zero upfront purchase GP", () => {
  render(
    <AcquisitionChecklist
      solution={{
        ...selected,
        loadouts: {
          boss: {
            ...loadout,
            equipment: { cape: 6570 },
            preparations: [],
          },
        },
        purchases: [],
        purchase_cost_gp: 0,
        running_cost: undefined,
        carried_item_ids: [6570],
        unowned_untradeable_item_ids: [6570],
        wilderness_risk: {
          loss_gp: 300,
          without_protect_item_gp: null,
          items: [],
          quantities: [],
          rules_revision: "reviewed",
        },
      }}
      roles={[roles[0]]}
      itemById={itemById}
      selectionKey="untradeable"
    />,
  );
  const checklist = screen.getByRole("region", {
    name: "Acquisition checklist",
  });
  expect(checklist).toHaveTextContent("0 GP additional purchases");
  expect(checklist).toHaveTextContent(/Wilderness loss.*300 GP/);
  expect(
    screen.getByRole("region", { name: "Untradeables to obtain" }),
  ).toHaveTextContent("Fire cape");
  expect(screen.queryByRole("region", { name: "Prepare" })).toBeNull();
});

it("shows activation reserves while keeping unavailable upkeep explicit", () => {
  render(
    <AcquisitionChecklist
      solution={{
        ...selected,
        loadouts: {
          boss: {
            ...loadout,
            preparations: [
              {
                ...preparation,
                activation_reserve: [{ item_id: 21820, quantity: 1000 }],
              },
            ],
          },
        },
        running_cost: {
          status: "unavailable",
          gp_per_damage: null,
          gp_per_attack: null,
          gp_per_hour: null,
          reasons: ["Price unavailable"],
          resources: [
            {
              item_id: 21820,
              name: "Revenant ether",
              required_quantity: 1,
              consumed_quantity: 1,
              supplied_quantity: 0,
              supplied_by: null,
              unit_price_gp: null,
              price_layer: "missing",
            },
          ],
        },
      }}
      roles={[roles[0]]}
      itemById={itemById}
      selectionKey="reserve"
    />,
  );
  expect(screen.getByRole("region", { name: "Prepare" })).toHaveTextContent(
    "Activation reserve · 1,000 × Revenant ether",
  );
  expect(screen.getByText("Estimated upkeep").parentElement).toHaveTextContent(
    "Estimated upkeepUnavailable",
  );
});

it("lists two purchases and two activation reserves for independently prepared sceptres", () => {
  const powered = {
    ...preparation,
    usable_item_id: 27665,
    market_item_id: 27662,
    activation_reserve: [{ item_id: 21820, quantity: 1000 }],
    message: "Charge the sceptre.",
  };
  const autocast = {
    ...powered,
    usable_item_id: 27679,
    message: "Swap to autocast.",
  };
  render(
    <AcquisitionChecklist
      solution={{
        ...selected,
        loadouts: {
          boss: {
            ...loadout,
            equipment: { weapon: 27665 },
            preparations: [powered],
          },
          adds: {
            ...loadout,
            equipment: { weapon: 27679 },
            preparations: [autocast],
          },
        },
        purchases: [
          { item_id: 27662, quantity: 2, cost_gp: 1000, conditional: false },
        ],
        carried_item_ids: [27665, 27679],
      }}
      roles={roles}
      itemById={itemById}
      selectionKey="sceptre"
    />,
  );
  const prepare = screen.getByRole("region", { name: "Prepare" });
  expect(prepare).toHaveTextContent("Charge the sceptre.");
  expect(prepare).toHaveTextContent("Swap to autocast.");
  expect(within(prepare).getAllByText(/Activation reserve/)).toHaveLength(2);
  expect(prepare).toHaveTextContent("1,000 × Revenant ether");
  const buy = screen.getByRole("region", { name: "Buy" });
  expect(buy).toHaveTextContent("2 × Accursed sceptre (uncharged) · 1,000 GP");
  expect(buy).toHaveTextContent(
    "2 × Accursed sceptre (uncharged) (#27662) · 1,000 GP",
  );
});

it("attributes an additional copy only to the role using that purchase", () => {
  const owned = {
    ...preparation,
    usable_item_id: 27665,
    source_item_id: 27662,
    market_item_id: 27662,
  };
  const purchased = { ...owned, usable_item_id: 27679, source_item_id: null };
  render(
    <AcquisitionChecklist
      solution={{
        ...selected,
        loadouts: {
          boss: {
            ...loadout,
            equipment: { weapon: 27665 },
            preparations: [owned],
          },
          adds: {
            ...loadout,
            equipment: { weapon: 27679 },
            preparations: [purchased],
          },
        },
        purchases: [{ item_id: 27662, cost_gp: 1000, conditional: false }],
      }}
      roles={roles}
      itemById={itemById}
      selectionKey="additional"
    />,
  );
  const buy = screen.getByRole("region", { name: "Buy" });
  expect(buy).toHaveTextContent("Used by Adds");
  expect(buy).not.toHaveTextContent("Boss");
});

it("replaces acquisition steps and closes the old export when the selection changes", async () => {
  const user = userEvent.setup();
  const { rerender } = render(
    <AcquisitionChecklist
      solution={selected}
      roles={[roles[0]]}
      itemById={itemById}
      selectionKey="first"
    />,
  );
  await user.click(
    screen.getByRole("button", { name: "Export mobile bank tag" }),
  );
  rerender(
    <AcquisitionChecklist
      solution={{
        ...selected,
        loadouts: {
          boss: { ...loadout, equipment: { cape: 6570 }, preparations: [] },
        },
        carried_item_ids: [6570],
        purchases: [],
        purchase_cost_gp: 0,
      }}
      roles={[roles[0]]}
      itemById={itemById}
      selectionKey="second"
    />,
  );
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.queryByRole("region", { name: "Prepare" })).toBeNull();
  await user.click(
    screen.getByRole("button", { name: "Export mobile bank tag" }),
  );
  expect(screen.getByRole("textbox", { name: "Bank tag code" })).toHaveValue(
    "1,1,6570,0,1",
  );
});
it("keeps automatic worn forms out of charging tasks and exports their inventory ID", async () => {
  const row: Preparation = {
    ...preparation,
    source_item_id: null,
    usable_item_id: 10074,
    market_item_id: 10071,
    charges: "not_applicable",
    charging_required: false,
  };
  const cape = {
    id: 10074,
    name: "Spottier cape",
    facts: { equipment: { inventory_form_id: 10071 } },
  } as unknown as Item;
  render(
    <AcquisitionChecklist
      solution={{
        ...selected,
        loadouts: {
          boss: { ...loadout, equipment: { cape: 10074 }, preparations: [row] },
        },
        purchases: [{ item_id: 10071, cost_gp: 500, conditional: false }],
      }}
      roles={[roles[0]]}
      itemById={(id) => (id === 10074 ? cape : undefined)}
      selectionKey="cape"
    />,
  );
  expect(screen.getByRole("region", { name: "Buy" })).toHaveTextContent(
    "Spottier cape",
  );
  expect(screen.queryByRole("region", { name: "Prepare" })).toBeNull();
  await userEvent.click(
    screen.getByRole("button", { name: "Export mobile bank tag" }),
  );
  expect(screen.getByLabelText("Bank tag code")).toHaveValue("1,1,10071,0,1");
});
