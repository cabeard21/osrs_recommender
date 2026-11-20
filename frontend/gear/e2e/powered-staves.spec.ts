import { expect, test } from "@playwright/test";

test("owned uncharged staff selection persists and discloses preparation", async ({
  page,
}) => {
  await page.request.post("/test/seed-powered");
  await page.goto("/gear-next/");
  await page.getByRole("button", { name: "magic", exact: true }).click();
  await page
    .locator("summary")
    .filter({ hasText: /^Combat Options/ })
    .click();
  const staff = page.getByRole("checkbox", {
    name: "Warped sceptre",
    exact: true,
  });
  await expect(staff).toBeChecked();
  await staff.uncheck();
  await page.reload();
  await page
    .locator("summary")
    .filter({ hasText: /^Combat Options/ })
    .click();
  await expect(staff).not.toBeChecked();
  await staff.check();
  await page.getByText("Equipment locks & exclusions", { exact: true }).click();
  await page.getByLabel("Physical item ID or empty").fill("28583");
  await page
    .getByRole("button", { name: "Set equipment lock", exact: true })
    .click();
  const pending = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname === "/ui-api/gear/optimizations" &&
      r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const response = await pending;
  expect(response.request().postDataJSON().roles[0].locks.weapon).toBe(28583);
  expect(response.status(), await response.text()).toBe(200);
  const result = await response.json();
  expect(
    (
      Object.values(result.result.selected_solution.loadouts)[0] as {
        equipment: { weapon: number };
      }
    ).equipment.weapon,
  ).toBe(28585);
  const loadout = Object.values(
    result.result.selected_solution.loadouts,
  )[0] as {
    preparations: {
      source_item_id: number;
      usable_item_id: number;
      charging_required: boolean;
    }[];
  };
  expect(loadout.preparations).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        source_item_id: 28583,
        usable_item_id: 28585,
        charging_required: true,
      }),
    ]),
  );
  await expect(
    page
      .getByText("Charging required; actual charge availability is unknown.")
      .first(),
  ).toBeVisible();
  await expect(page.getByLabel("Selected combat configuration")).toContainText(
    "Built-in spell",
  );
  await expect(
    page.getByRole("button", { name: /^weapon Owned source · Prepare/ }),
  ).toBeVisible();
});

test("unowned powered staff purchases its market form and renders charging preparation", async ({
  page,
}) => {
  await page.request.post("/test/seed-powered-purchase");
  await page.goto("/gear-next/");
  await page.getByRole("button", { name: "magic", exact: true }).click();
  await page.getByLabel("Additional purchase budget (GP)").fill("1000");
  await page.getByText("Equipment locks & exclusions", { exact: true }).click();
  await page.getByLabel("Physical item ID or empty").fill("28583");
  await page
    .getByRole("button", { name: "Set equipment lock", exact: true })
    .click();
  const pending = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname === "/ui-api/gear/optimizations" &&
      r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const response = await pending;
  expect(response.status(), await response.text()).toBe(200);
  const result = await response.json();
  const selected = result.result.selected_solution;
  expect(selected.purchase_cost_gp).toBe(1000);
  expect(selected.purchases).toEqual([
    { item_id: 28583, cost_gp: 1000, conditional: false },
  ]);
  expect(selected.carried_item_ids).toContain(28585);
  expect(selected.carried_item_ids).not.toContain(28583);
  await expect(
    page.getByText("Best configuration found", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".purchase-rows")).toContainText(
    "Warped sceptre · 1,000 GP",
  );
  await expect(page.locator(".purchase-rows")).not.toContainText("Item #28583");
  await expect(
    page.getByRole("button", { name: /^weapon Buy base · Prepare/ }),
  ).toBeVisible();
  await expect(
    page
      .getByText("Charging required; actual charge availability is unknown.")
      .first(),
  ).toBeVisible();
  const checklist = page.getByRole("region", { name: "Acquisition checklist" });
  await expect(
    checklist.getByRole("region", { name: "Prepare" }),
  ).toContainText("Charging required; actual charge availability is unknown.");
  expect(
    await checklist.evaluate(
      (section) => section.scrollWidth <= section.clientWidth,
    ),
  ).toBe(true);
  await checklist
    .getByRole("button", { name: "Export mobile bank tag" })
    .click();
  const code = await page.getByLabel("Bank tag code").inputValue();
  expect(code.split(",")).toContain("28585");
  expect(code.split(",")).not.toContain("28583");
});
