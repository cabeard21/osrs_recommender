import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { NpcTargetPicker } from "../components/NpcTargetPicker";
import {
  npcEntryLabel,
  npcStatSummary,
  sortNpcEntries,
} from "../components/npcEntries";

const entry = (patch: Record<string, unknown>) => ({
  key: "k",
  name: "Goblin",
  variant: "",
  npc_id: 1,
  combat_level: 2,
  support_status: "supported",
  reasons: [],
  ...patch,
});
const detail = {
  ...entry({ key: "goblin-13", variant: "Level 13", combat_level: 13 }),
  catalog_revision: "rev",
  wiki_url: "https://oldschool.runescape.wiki/w/Goblin",
  target: {
    name: "Goblin",
    defence_level: 7,
    magic_level: 1,
    bonuses: { stab: 4, slash: 6, crush: 8, ranged: 4, magic: 4 },
    weakness_element: "fire",
    weakness_percent: 10,
  },
};
const response = (value: unknown) => ({ ok: true, json: async () => value });

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

it("labels drop repeated levels, Standard variants and the supported status", () => {
  expect(npcEntryLabel(entry({ variant: "Level 13", combat_level: 13 }))).toBe(
    "Goblin · Level 13",
  );
  expect(npcEntryLabel(entry({ variant: "Standard" }))).toBe(
    "Goblin · Level 2",
  );
  expect(
    npcEntryLabel(entry({ variant: "Armed", support_status: "not_reviewed" })),
  ).toBe("Goblin · Armed · Level 2 · not reviewed");
  expect(npcEntryLabel(entry({ variant: "Level 2 (armed)" }))).toBe(
    "Goblin · Level 2 (armed)",
  );
});

it("shows the light/standard/heavy ranged split only when it differs", () => {
  const target = {
    name: "Goblin",
    defence_level: 1,
    magic_level: 1,
    bonuses: { stab: 0, slash: 0, crush: 0, magic: 0, ranged: -15 },
    ranged_light: -15,
    ranged_standard: -15,
    ranged_heavy: -15,
  };
  expect(npcStatSummary(target)).not.toContain("light");
  expect(npcStatSummary({ ...target, ranged_heavy: 20 })).toContain(
    "(ranged light -15 / standard -15 / heavy 20)",
  );
});

it("the selected NPC card uses the same label and hides the supported status", async () => {
  stubCatalog();
  render(
    <NpcTargetPicker
      selection={{ key: detail.key, catalog_revision: "rev" }}
      target={detail.target}
      onChange={vi.fn()}
    />,
  );
  expect(await screen.findByText("Goblin · Level 13")).toBeInTheDocument();
  expect(screen.queryByText(/supported/)).not.toBeInTheDocument();
});

it("keeps the catalog's name order and sorts each name by level", () => {
  const sorted = sortNpcEntries([
    entry({ key: "a", combat_level: 13 }),
    entry({ key: "b", name: "Goblin guard", combat_level: 42 }),
    entry({ key: "c", combat_level: 2 }),
    entry({ key: "d", combat_level: 5 }),
  ]);
  expect(sorted.map((row) => row.key)).toEqual(["c", "d", "a", "b"]);
});

function stubCatalog(items = [detail]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      response(url.includes("?") ? { items, total: items.length } : detail),
    ),
  );
}

it("arrow keys move into the results and Enter picks the top result", async () => {
  stubCatalog([detail, { ...detail, key: "other", combat_level: 20 }]);
  const change = vi.fn();
  render(<NpcTargetPicker onChange={change} />);
  const search = screen.getByLabelText("Search NPCs");
  fireEvent.change(search, { target: { value: "gob" } });
  const first = await screen.findByRole("button", {
    name: "Goblin · Level 13",
  });
  fireEvent.keyDown(search, { key: "ArrowDown" });
  expect(first).toHaveFocus();
  fireEvent.keyDown(first, { key: "ArrowDown" });
  expect(screen.getByRole("button", { name: /Level 20/ })).toHaveFocus();
  fireEvent.keyDown(document.activeElement!, { key: "ArrowUp" });
  expect(first).toHaveFocus();
  fireEvent.keyDown(first, { key: "ArrowUp" });
  expect(search).toHaveFocus();
  fireEvent.keyDown(search, { key: "Enter" });
  await waitFor(() =>
    expect(change).toHaveBeenCalledWith(
      expect.objectContaining({
        targetSelection: { key: "goblin-13", catalog_revision: "rev" },
      }),
    ),
  );
});

it("remembers chosen NPCs as recent targets", async () => {
  stubCatalog();
  const change = vi.fn();
  const view = render(<NpcTargetPicker onChange={change} />);
  fireEvent.change(screen.getByLabelText("Search NPCs"), {
    target: { value: "gob" },
  });
  fireEvent.click(
    await screen.findByRole("button", { name: "Goblin · Level 13" }),
  );
  await waitFor(() => expect(change).toHaveBeenCalled());
  view.unmount();
  const next = vi.fn();
  render(<NpcTargetPicker onChange={next} />);
  fireEvent.click(
    screen.getByRole("button", { name: "Recent target Goblin · Level 13" }),
  );
  await waitFor(() =>
    expect(next).toHaveBeenCalledWith(
      expect.objectContaining({
        targetSelection: { key: "goblin-13", catalog_revision: "rev" },
      }),
    ),
  );
});

it("summarizes NPC stats on one line and labels defence bonuses", async () => {
  stubCatalog();
  render(
    <NpcTargetPicker
      selection={{ key: detail.key, catalog_revision: "rev" }}
      target={detail.target}
      onChange={vi.fn()}
    />,
  );
  expect(
    await screen.findByText(
      "Defence 7 · Magic 1 · Defence bonuses: stab 4 / slash 6 / crush 8 / magic 4 / ranged 4 · Weak to fire (10%)",
    ),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Reset to NPC stats" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Clear NPC and use custom stats" }),
  ).toBeInTheDocument();
});

it("offers Reset once the stats differ from the NPC", async () => {
  stubCatalog();
  render(
    <NpcTargetPicker
      selection={{ key: detail.key, catalog_revision: "rev" }}
      target={{ ...detail.target, defence_level: 25 }}
      onChange={vi.fn()}
    />,
  );
  expect(
    await screen.findByRole("button", { name: "Reset to NPC stats" }),
  ).toBeInTheDocument();
});
