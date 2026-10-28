import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ItemInspector } from "../components/ItemInspector";
import { useGear } from "../state/GearProvider";
import { initialState, newRole } from "../state/scenario";
import { emptyEquipment } from "../api/contracts";
import { parseContext, parseItem } from "../api/httpClient";
import context from "./live-context.json";

vi.mock("../state/GearProvider", () => ({ useGear: vi.fn() }));

function setup() {
  const state = initialState();
  state.mode = "multi";
  state.context = parseContext(context);
  const current = state.multi;
  current.draft.roles = [newRole(1), newRole(2)];
  current.activeRole = "role-2";
  current.solutionId = "curve-1";
  current.slot = "weapon";
  const original = parseItem(context.items[0]);
  const alternate = {
    ...original,
    id: 1333,
    name: "Rune scimitar",
    facts: { ...original.facts!, item_id: 1333, numeric_item_id: 1333 },
  };
  const equipment = { ...emptyEquipment(), weapon: original.id };
  const result = {
    fingerprint: "joint-result",
    solutions: [
      { id: "curve-0", loadouts: [{ roleId: "role-1", equipment }] },
      {
        id: "curve-1",
        loadouts: [
          { roleId: "role-1", equipment },
          { roleId: "role-2", equipment: { ...equipment, weapon: 1333 } },
        ],
      },
    ],
    live: { result: { alternatives: { weapon: [] } } },
  };
  current.result = result as unknown as typeof current.result;
  const edit = vi.fn();
  const previewTrial = vi.fn();
  const getItem = vi.fn(async (id: number) =>
    id === 1333 ? alternate : original,
  );
  const gear = {
    liveMode: true,
    state,
    current,
    edit,
    previewTrial,
    dispatch: vi.fn(),
    revertTrial: vi.fn(),
    cancelTrial: vi.fn(),
    itemById: (id: number) => (id === 1333 ? alternate : original),
    client: {
      getItem,
      browseItems: vi.fn(async () => ({
        items: [],
        total: 0,
        nextOffset: null,
      })),
    },
  } as unknown as ReturnType<typeof useGear>;
  vi.mocked(useGear).mockReturnValue(gear);
  const view = render(<ItemInspector />);
  return { gear, edit, previewTrial, getItem, ...view };
}

it("inspects the active role of the selected joint curve point and offers no single-role trial", async () => {
  const { getItem, previewTrial } = setup();
  expect(
    await screen.findByRole("heading", { name: "Rune scimitar" }),
  ).toBeVisible();
  expect(getItem).toHaveBeenCalledWith(1333, "community_best_effort");
  expect(
    screen.queryByRole("region", { name: "Contextual alternatives" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /Preview/ }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByText(/Exact multi-role manual evaluation is unavailable/),
  ).toBeVisible();
  expect(previewTrial).not.toHaveBeenCalled();
});

it("locks the inspected item globally without changing any role equipment", async () => {
  const user = userEvent.setup();
  const { edit } = setup();
  await screen.findByRole("heading", { name: "Rune scimitar" });
  await user.selectOptions(screen.getByLabelText("Lock scope"), "global");
  await user.click(
    screen.getByRole("button", { name: "Lock weapon to #1333" }),
  );
  expect(edit.mock.calls[0][0].globalLocks).toEqual({ weapon: 1333 });
  expect(
    edit.mock.calls[0][0].roles.every(
      (role: { locks: object }) => Object.keys(role.locks).length === 0,
    ),
  ).toBe(true);
});

it("explicitly unlocks global and role conflicts before excluding a physical ID", async () => {
  const user = userEvent.setup();
  const { gear, rerender, edit } = setup();
  gear.current.draft.globalLocks = { weapon: 1333 };
  gear.current.draft.roles[0].locks = { weapon: 1333 };
  rerender(<ItemInspector />);
  await user.click(
    await screen.findByRole("button", { name: "Unlock and exclude in draft" }),
  );
  expect(edit.mock.calls[0][0].globalLocks).toEqual({});
  expect(edit.mock.calls[0][0].roles[0].locks).toEqual({});
  expect(edit.mock.calls[0][0].exclusions).toEqual([1333]);
});

it("withholds a role lock if the submitted role was removed from the draft", async () => {
  const { gear, rerender } = setup();
  gear.current.draft.roles = [gear.current.draft.roles[0]];
  rerender(<ItemInspector />);
  expect(
    await screen.findByRole("button", { name: "Lock weapon to #1333" }),
  ).toBeDisabled();
  expect(screen.getByText(/no longer exists in the draft/)).toBeVisible();
});
