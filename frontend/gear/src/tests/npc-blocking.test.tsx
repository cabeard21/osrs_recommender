import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { HttpGearClient } from "../api/httpClient";
import type { Draft } from "../api/contracts";
import { GearProvider, useGear } from "../state/GearProvider";
import { newDraft, newRole, normalize } from "../state/scenario";
import context from "./live-context.json";

const target = {
  name: "Lizardman (Level 53)",
  defence_level: 43,
  magic_level: 1,
  bonuses: { stab: -20, slash: 25, crush: 0, ranged: 0, magic: 0 },
  unsupported_mechanics: [
    "NPC-specific mechanics have not been reviewed for ordinary attacks.",
  ],
};
const selection = {
  key: "c4b35626ceb46d21a4dc6ee8",
  catalog_revision:
    "e3ae4f3d865d73e2befb755fc1fc1cd30d7e3c80725812fc95629c3eec8a2167",
};
function blockedDraft(multi: boolean): Draft {
  const draft = newDraft();
  if (multi) {
    draft.roles = [
      newRole(1),
      { ...newRole(2), combatTarget: target, targetSelection: selection },
    ];
  } else {
    draft.target = target.name;
    draft.defence = "43";
    draft.combatTarget = target;
    draft.targetSelection = selection;
    draft.secondaryPriority = "balanced_defence";
    draft.optimizationMode = "thorough";
  }
  return draft;
}
function Harness({ draft }: { draft: Draft }) {
  const { edit, run, current, state } = useGear();
  return (
    <>
      {state.context && <button onClick={() => edit(draft)}>Set target</button>}
      <button onClick={() => void run()}>Run</button>
      {current.error && <p role="alert">{current.error}</p>}
    </>
  );
}
it.each([false, true])(
  "blocks an unreviewed target before optimization transport (Multi=%s)",
  async (multi) => {
    const fetcher = vi.fn(
      async (_url: RequestInfo | URL) => new Response(JSON.stringify(context)),
    );
    render(
      <GearProvider client={new HttpGearClient("/ui-api/gear", fetcher)}>
        <Harness draft={blockedDraft(multi)} />
      </GearProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Set target" }));
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /Cannot optimize against Lizardman \(Level 53\).*Choose a supported NPC/,
    );
    expect(
      fetcher.mock.calls.every(
        ([url]) => !String(url).endsWith("/optimizations"),
      ),
    ).toBe(true);
  },
);
it("keeps supported NPC targets available", () => {
  const draft = blockedDraft(false);
  draft.combatTarget = { ...target, unsupported_mechanics: [] };
  expect(normalize(draft, "snapshot").request.roles[0].targetSelection).toEqual(
    selection,
  );
});
