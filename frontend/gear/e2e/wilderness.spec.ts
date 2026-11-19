import { expect, test } from "@playwright/test";

test("uses the Wilderness risk budget with Protect Item and saves its assumptions", async ({
  page,
}) => {
  await page.request.post("/test/seed-optimization");
  await page.goto("/gear-next/");
  await page.getByLabel("Wilderness", { exact: true }).check();
  await page.getByLabel("Wilderness depth").selectOption("level_1_20");
  await page.getByLabel("Skulled at death").check();
  await page.getByLabel("Assume Protect Item is active at death").check();
  await page.getByLabel("Additional purchase budget (GP)").fill("1k");
  await page.getByLabel("Max gear loss if PK’d (GP)").fill("0");
  const response = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname === "/ui-api/gear/optimizations" &&
      r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const result = await response;
  expect(result.status(), await result.text()).toBe(200);
  const body = await result.json();
  expect(body.scenario.budget_gp).toBe(1_000);
  expect(body.scenario.wilderness).toEqual({
    depth: "level_1_20",
    skulled: true,
    protect_item: true,
    max_loss_gp: 0,
    spell_casts: 100,
  });
  expect(body.result.selected_solution.wilderness_risk.loss_gp).toBe(0);
  const risk = page.getByRole("region", { name: "Wilderness risk" });
  await expect(risk).toContainText("0 GP estimated loss if PK’d");
  await expect(risk).toContainText("Same setup without Protect Item");
  await page.reload();
  await expect(page.getByLabel("Wilderness depth")).toHaveValue("level_1_20");
  await expect(page.getByLabel("Skulled at death")).toBeChecked();
  await expect(
    page.getByLabel("Assume Protect Item is active at death"),
  ).toBeChecked();
  await expect(page.getByLabel("Additional purchase budget (GP)")).toHaveValue(
    "1k",
  );
  await expect(page.getByLabel("Max gear loss if PK’d (GP)")).toHaveValue("0");
});

test("packs loose runes for a Magic setup and enforces their loss", async ({
  page,
}) => {
  expect((await page.request.post("/test/seed-wilderness-magic")).ok()).toBe(
    true,
  );
  await page.goto("/gear-next/");
  await page.getByRole("button", { name: "magic", exact: true }).click();
  await page
    .locator("summary")
    .filter({ hasText: /^Combat Options/ })
    .click();
  await page
    .getByRole("checkbox", {
      name: "Optimize attack type, stance and spell with equipment",
    })
    .uncheck();
  await page
    .getByRole("combobox", { name: "Spell", exact: true })
    .selectOption("fire_strike");
  await page.getByLabel("Wilderness", { exact: true }).check();
  await page.getByLabel("Skulled at death").check();
  await page.getByLabel("Assume Protect Item is active at death").check();
  const casts = page.getByLabel("Casts to pack per Magic setup");
  await expect(casts).toHaveValue("100");
  await casts.fill("20");
  const cap = page.getByLabel("Max gear loss if PK’d (GP)");
  await cap.fill("320");

  async function run() {
    const result = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/ui-api/gear/optimizations" &&
        response.request().method() === "POST",
    );
    await page
      .getByRole("button", { name: /^(Run optimization|Reoptimize)$/ })
      .click();
    const response = await result;
    expect(response.status(), await response.text()).toBe(200);
    return response.json();
  }
  const body = await run();
  expect(body.scenario.wilderness.spell_casts).toBe(20);
  expect(body.result.selected_solution.wilderness_risk).toMatchObject({
    loss_gp: 320,
    quantities: [
      { item_id: 554, resource_id: 554, kind: "rune", quantity: 60 },
      { item_id: 558, resource_id: 558, kind: "rune", quantity: 20 },
    ],
  });
  const risk = page.getByRole("region", { name: "Wilderness risk" });
  await expect(risk).toContainText("20 casts per Magic setup");
  await expect(risk).toContainText("60 × Fire rune");
  await expect(risk).toContainText("20 × Mind rune");
  await page.reload();
  await expect(casts).toHaveValue("20");

  await cap.fill("319");
  const overBudget = await run();
  expect(overBudget.result.selected_solution).toBeNull();
  await expect(
    page.getByRole("heading", {
      name: "No feasible solution found within this search",
    }),
  ).toBeVisible();
});

test("reports the ammo quantity to pack on a ranged loadout", async ({
  page,
}) => {
  expect((await page.request.post("/test/seed-ammo")).ok()).toBe(true);
  await page.goto("/gear-next/");
  await page.getByRole("button", { name: "ranged", exact: true }).click();
  await page.getByLabel("Wilderness", { exact: true }).check();
  await page.getByLabel("Skulled at death").check();
  await page.getByLabel("Assume Protect Item is active at death").check();
  await page.getByLabel("Max gear loss if PK’d (GP)").fill("300");
  const result = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/ui-api/gear/optimizations" &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const response = await result;
  expect(response.status(), await response.text()).toBe(200);
  const body = await response.json();
  expect(body.scenario.budget_gp).toBe(0);
  expect(body.scenario.wilderness.max_loss_gp).toBe(300);
  const risk = body.result.selected_solution.wilderness_risk;
  expect(risk.loss_gp).toBe(300);
  expect(risk.quantities).toEqual([
    expect.objectContaining({ resource_id: 892, quantity: 3, kind: "ammo" }),
  ]);
  await expect(
    page.getByRole("region", { name: "Wilderness risk" }),
  ).toContainText(/3 × rune arrow/i);
  if (process.env.GEAR_E2E_NATIVE === "1") {
    const diagnostics = await (
      await page.request.get("/test/native-diagnostics")
    ).json();
    expect(diagnostics.native_requests).toBeGreaterThan(0);
    expect(diagnostics.fallback_requests).toBe(0);
  }
});
