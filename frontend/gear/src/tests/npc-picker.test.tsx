import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { NpcTargetPicker } from "../components/NpcTargetPicker";
afterEach(() => vi.unstubAllGlobals());

it("searches NPC variants and selects the exact catalog identity", async () => {
  const entry = {
    key: "npc-1-standard",
    name: "Goblin",
    variant: "Standard",
    npc_id: 1,
    combat_level: 2,
    support_status: "supported",
    reasons: [],
    catalog_revision: "rev",
    target: { name: "Goblin", defence_level: 1, magic_level: 1, bonuses: {} },
    source_url: "https://oldschool.runescape.wiki/w/Goblin",
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      json: async () =>
        url.includes("?")
          ? { items: [entry], total: 1, catalog_revision: "rev" }
          : entry,
    })),
  );
  const change = vi.fn();
  render(<NpcTargetPicker onChange={change} />);
  fireEvent.change(screen.getByLabelText("Search NPCs"), {
    target: { value: "Goblin" },
  });
  fireEvent.click(
    await screen.findByRole("button", { name: /Goblin · Standard/ }),
  );
  await waitFor(() => expect(change).toHaveBeenCalled());
  expect(change).toHaveBeenCalledWith(
    expect.objectContaining({
      targetSelection: { key: entry.key, catalog_revision: "rev" },
      combatTarget: entry.target,
    }),
  );
  vi.unstubAllGlobals();
});

const detail = {
  key: "1-standard",
  name: "Goblin",
  variant: "Standard",
  npc_id: 1,
  combat_level: 2,
  support_status: "supported",
  reasons: [],
  catalog_revision: "rev",
  target: {
    name: "Goblin",
    defence_level: 1,
    magic_level: 1,
    bonuses: { stab: 0 },
  },
  source_url: "https://oldschool.runescape.wiki/w/Goblin",
};
const selection = { key: detail.key, catalog_revision: "rev" };
const response = (value: unknown) => ({ ok: true, json: async () => value });

it("prominently explains that unreviewed NPCs cannot be optimized", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      response({
        ...detail,
        name: "Lizardman",
        support_status: "not_reviewed",
        reasons: [
          "NPC-specific mechanics have not been reviewed for ordinary attacks.",
        ],
      }),
    ),
  );
  render(
    <NpcTargetPicker
      selection={selection}
      target={detail.target}
      onChange={vi.fn()}
    />,
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    /Lizardman.*cannot be optimized.*Choose a supported NPC/,
  );
});

it("retains incomplete overrides without losing mechanic metadata and resets them", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(detail)),
  );
  const change = vi.fn();
  render(
    <NpcTargetPicker
      selection={selection}
      target={detail.target}
      onChange={change}
    />,
  );
  fireEvent.click(await screen.findByRole("button", { name: "Edit stats" }));
  fireEvent.change(screen.getByLabelText("defence level"), {
    target: { value: "" },
  });
  expect(change).toHaveBeenLastCalledWith({
    targetInputs: { defence_level: "" },
    combatTarget: detail.target,
  });
  fireEvent.change(screen.getByLabelText("bonuses.stab"), {
    target: { value: "20" },
  });
  expect(change).toHaveBeenLastCalledWith(
    expect.objectContaining({
      combatTarget: { ...detail.target, bonuses: { stab: 20 } },
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Reset to NPC stats" }));
  expect(change).toHaveBeenLastCalledWith({
    combatTarget: detail.target,
    targetSelection: selection,
    targetInputs: {},
  });
  fireEvent.click(screen.getByRole("button", { name: "Custom target" }));
  expect(change).toHaveBeenLastCalledWith(
    expect.objectContaining({ targetSelection: undefined }),
  );
});

it("reports catalog failures and retries", async () => {
  const fetcher = vi
    .fn()
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValue(response({ items: [], total: 0 }));
  vi.stubGlobal("fetch", fetcher);
  render(<NpcTargetPicker onChange={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("Search NPCs"), {
    target: { value: "missing" },
  });
  await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await screen.findByText("No NPCs found.");
});

it("selects missing-stat identities without keeping the previous effective target", async () => {
  const missing = {
    ...detail,
    target: null,
    support_status: "not_reviewed",
    reasons: ["Missing stats"],
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      response(url.includes("?") ? { items: [missing], total: 1 } : missing),
    ),
  );
  const change = vi.fn();
  render(<NpcTargetPicker target={detail.target} onChange={change} />);
  fireEvent.change(screen.getByLabelText("Search NPCs"), {
    target: { value: "goblin" },
  });
  fireEvent.click(await screen.findByRole("button", { name: /Goblin/ }));
  await waitFor(() =>
    expect(change).toHaveBeenCalledWith({
      combatTarget: undefined,
      targetSelection: selection,
      targetInputs: {},
    }),
  );
});

it("uses the latest callback after a delayed detail response", async () => {
  let resolve!: (value: ReturnType<typeof response>) => void;
  const pending = new Promise<ReturnType<typeof response>>((done) => {
    resolve = done;
  });
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      url.includes("?")
        ? Promise.resolve(response({ items: [detail], total: 1 }))
        : pending,
    ),
  );
  const oldChange = vi.fn(),
    latestChange = vi.fn();
  const view = render(<NpcTargetPicker onChange={oldChange} />);
  fireEvent.change(screen.getByLabelText("Search NPCs"), {
    target: { value: "goblin" },
  });
  fireEvent.click(await screen.findByRole("button", { name: /Goblin/ }));
  view.rerender(<NpcTargetPicker onChange={latestChange} />);
  resolve(response(detail));
  await waitFor(() => expect(latestChange).toHaveBeenCalled());
  expect(oldChange).not.toHaveBeenCalled();
});
