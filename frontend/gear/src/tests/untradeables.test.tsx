import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import App from "../App";
import { GearProvider } from "../state/GearProvider";
import { FixtureGearClient } from "../fixtures/client";
import { newDraft, normalize, upgradeStoredDraft } from "../state/scenario";
import { optimizationRequest } from "../api/httpClient";
import { describeDraftChanges } from "../state/draftChanges";
import { UntradeablesToObtain } from "../components/UntradeablesToObtain";
import { validateUntradeables } from "../api/untradeables";

it("defaults old drafts off, validates storage, and sends explicit untradeable access", () => {
  const draft = newDraft();
  expect(draft.includeUntradeables).toBe(false);
  const legacy = { ...draft, includeUntradeables: undefined };
  expect(upgradeStoredDraft(legacy)?.includeUntradeables).toBe(false);
  expect(
    upgradeStoredDraft({ ...draft, includeUntradeables: "yes" }),
  ).toBeNull();
  const enabled = { ...draft, includeUntradeables: true };
  const scenario = normalize(enabled, "snapshot");
  expect(scenario.request.include_untradeables).toBe(true);
  expect(optimizationRequest(scenario).include_untradeables).toBe(true);
  expect(
    describeDraftChanges(enabled, normalize(draft, "snapshot").request),
  ).toContain("Unowned untradeables: excluded → considered");
});
it("preserves the toggle while owned-only access temporarily disables it", async () => {
  render(
    <GearProvider client={new FixtureGearClient("none", 0)}>
      <App />
    </GearProvider>,
  );
  const toggle = await screen.findByRole("checkbox", {
    name: "Consider unowned untradeables",
  });
  expect(toggle).not.toBeChecked();
  fireEvent.click(toggle);
  fireEvent.change(screen.getByLabelText("Equipment access"), {
    target: { value: "owned" },
  });
  expect(toggle).toBeChecked();
  expect(toggle).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Equipment access"), {
    target: { value: "usable" },
  });
  expect(toggle).toBeChecked();
  expect(toggle).toBeEnabled();
});
it("lists required untradeables separately without pricing or claiming ownership", () => {
  render(<UntradeablesToObtain ids={[6570]} itemName={() => "Fire cape"} />);
  expect(
    screen.getByRole("heading", { name: "Untradeables to obtain" }),
  ).toBeVisible();
  expect(screen.getByText("Fire cape")).toBeVisible();
  expect(screen.getByText(/Obtain these separately/)).toBeVisible();
  expect(screen.queryByText(/0 GP/)).not.toBeInTheDocument();
});
it("omits the acquisition section when no untradeables need obtaining", () => {
  render(<UntradeablesToObtain itemName={() => "Fire cape"} />);
  expect(
    screen.queryByRole("region", { name: "Untradeables to obtain" }),
  ).not.toBeInTheDocument();
});
it("validates acquisition IDs against equipment, purchase lists, and explicit access", () => {
  expect(validateUntradeables(undefined, [6570], [], false)).toEqual([]);
  expect(validateUntradeables([6570], [6570], [], true)).toEqual([6570]);
  for (const [value, equipped, purchases, enabled] of [
    [[6570], [6570], [], false],
    [[6570, 6570], [6570], [], true],
    [[6570], [1], [], true],
    [[6570], [6570], [6570], true],
    [["6570"], [6570], [], true],
  ] as const)
    expect(() =>
      validateUntradeables(value, [...equipped], [...purchases], enabled),
    ).toThrow();
});
