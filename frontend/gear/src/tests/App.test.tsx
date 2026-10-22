import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import App from "../App";
import { GearProvider } from "../state/GearProvider";
import { FixtureGearClient } from "../fixtures/client";
import { slots } from "../api/contracts";
function setup(client = new FixtureGearClient("none", 0)) {
  render(
    <GearProvider client={client}>
      <App />
    </GearProvider>,
  );
  return userEvent.setup();
}
async function run(user: ReturnType<typeof userEvent.setup>) {
  await user.click(
    await screen.findByRole("button", { name: "Run fixture optimization" }),
  );
  await screen.findByText("Submitted scenario // fixture result");
}
it("preserves configuration across Single/Multi navigation and reload", async () => {
  const user = setup();
  const budget = await screen.findByLabelText(
    "Additional purchase budget (GP)",
  );
  await user.clear(budget);
  await user.type(budget, "12345");
  await user.click(screen.getByRole("button", { name: "Multi-style" }));
  expect(screen.getByLabelText("Additional purchase budget (GP)")).toHaveValue(
    12345,
  );
  await user.clear(screen.getByLabelText("Additional purchase budget (GP)"));
  await user.type(
    screen.getByLabelText("Additional purchase budget (GP)"),
    "678",
  );
  await user.click(screen.getByRole("button", { name: "Single-style" }));
  expect(screen.getByLabelText("Additional purchase budget (GP)")).toHaveValue(
    12345,
  );
});
it("selects all eleven slots and closes inspectors without changing results", async () => {
  const user = setup();
  await run(user);
  for (const slot of slots) {
    await user.click(
      screen.getByRole("button", { name: new RegExp(`^${slot} `) }),
    );
    expect(
      screen.getByRole("dialog", { name: "Item inspector" }),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Close Item inspector" }),
    );
  }
  expect(
    screen.getByText("Submitted scenario // fixture result"),
  ).toBeInTheDocument();
});
it("previews an isolated equipment trial and edits draft locks explicitly", async () => {
  const user = setup();
  await run(user);
  await user.click(screen.getByRole("button", { name: /^weapon / }));
  await user.click(
    (await screen.findAllByRole("button", { name: "Preview comparison" }))[0],
  );
  await screen.findByText("Manual trial · fixture preview");
  expect(
    screen.getByRole("button", { name: /^weapon .*Abyssal whip/ }),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Revert trial" }));
  expect(
    screen.queryByText("Manual trial · fixture preview"),
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Lock item in draft" }));
  await user.click(
    screen.getByRole("button", { name: "Close Item inspector" }),
  );
  expect(screen.getByText(/Result outdated/)).toBeInTheDocument();
});
it("keeps submitted inputs frozen when draft fields change and retains previous result", async () => {
  const user = setup();
  await run(user);
  const target = screen.getByLabelText("Custom target");
  await user.clear(target);
  await user.type(target, "New target");
  expect(
    screen.getByText("Custom ordinary-attack target", { selector: "strong" }),
  ).toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: "Re-run fixture optimization" }),
  );
  await screen.findByRole("heading", {
    name: "Previous configuration comparison",
  });
  expect(
    screen.getByText("New target", { selector: "strong" }),
  ).toBeInTheDocument();
});
it.each(["busy", "error", "no-solution"] as const)(
  "renders %s fixture outcomes while preserving draft",
  async (failure) => {
    const user = setup(new FixtureGearClient("none", 0));
    await screen.findByText("Demo adventurer");
    await user.selectOptions(screen.getByLabelText("Demo outcome"), failure);
    await user.click(
      screen.getByRole("button", { name: "Run fixture optimization" }),
    );
    if (failure === "no-solution")
      await screen.findByRole("heading", { name: /No feasible solution/ });
    else await screen.findByRole("alert");
    expect(
      screen.getByLabelText("Additional purchase budget (GP)"),
    ).toHaveValue(0);
  },
);
it("renders context failures with retry", async () => {
  setup(new FixtureGearClient("none", 0, true));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Fixture context unavailable",
  );
  expect(screen.getByRole("button", { name: "Retry context" })).toBeEnabled();
  expect(
    screen.getByRole("button", { name: "Run fixture optimization" }),
  ).toBeDisabled();
});
it("switches multi visualizations and active configuration over the same solution", async () => {
  const user = setup();
  await screen.findByText("Demo adventurer");
  await user.click(screen.getByRole("button", { name: "Multi-style" }));
  await run(user);
  expect(screen.getAllByRole("button", { name: /head / })).toHaveLength(2);
  await user.click(
    screen.getByRole("button", { name: "Interactive switching" }),
  );
  await user.click(screen.getByRole("button", { name: "Configuration 2" }));
  expect(
    screen.getByRole("button", {
      name: /Configuration 2 weapon .*Rune crossbow/,
    }),
  ).toBeInTheDocument();
  await user.selectOptions(
    screen.getByLabelText("Swap-efficiency fixture"),
    "compact",
  );
  expect(
    screen.getByRole("button", {
      name: /Configuration 2 body .*Fighter torso/,
    }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: /Shared equipment/ }),
  ).toBeInTheDocument();
});
it("reports invalid fields without running or discarding an existing result", async () => {
  const user = setup();
  await run(user);
  await user.clear(screen.getByLabelText("Additional purchase budget (GP)"));
  await user.click(
    screen.getByRole("button", { name: "Re-run fixture optimization" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("Budget must be");
  expect(
    screen.getByText("Submitted scenario // fixture result"),
  ).toBeInTheDocument();
});
it("supports dialog keyboard cancellation and focus restoration", async () => {
  const user = setup();
  await run(user);
  const weapon = screen.getByRole("button", { name: /^weapon / });
  weapon.focus();
  await user.keyboard("{Enter}");
  const dialog = screen.getByRole("dialog");
  fireEvent(dialog, new Event("cancel", { bubbles: false, cancelable: true }));
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
  expect(weapon).toHaveFocus();
});
it("keeps missing and partial observations distinct from empty equipment", async () => {
  const user = setup();
  await screen.findByText("Demo adventurer");
  await user.selectOptions(
    screen.getByLabelText("Demo equipment observations"),
    "unknown",
  );
  expect(
    await screen.findByRole("heading", { name: "Current equipment unknown" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByText("Illustrative combat telemetry"),
  ).not.toBeInTheDocument();
  await user.selectOptions(
    screen.getByLabelText("Demo equipment observations"),
    "partial",
  );
  expect(
    await screen.findByRole("heading", {
      name: "Partial equipment observation",
    }),
  ).toBeInTheDocument();
});
