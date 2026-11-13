import { expect, test } from "@playwright/test";

test("owned elemental amulet is recommended with its evaluated damage bonus", async ({
  page,
}) => {
  const seeded = await page.request.post("/test/seed-elemental-amulet");
  expect(seeded.ok()).toBe(true);
  await page.goto("/gear-next/");
  await page.getByRole("button", { name: "magic", exact: true }).click();
  const pending = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/ui-api/gear/optimizations" &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const reply = await pending;
  expect(reply.status(), await reply.text()).toBe(200);
  const data = await reply.json();
  const loadout = data.result.selected_solution.loadouts["role-1"];
  expect(loadout.equipment.neck).toBe(34428);
  expect(loadout.performance.elemental_amulet_bonus).toMatchObject({
    item_id: 34428,
    base_max_hit_bonus: 2,
  });
  await expect(
    page.getByText(/Elemental amulet/, { exact: false }).first(),
  ).toBeVisible();
  await expect(page.getByLabel("Elemental amulet effect")).toContainText(
    "+2 base max hit",
  );
  await expect(page.getByLabel("Elemental amulet effect")).toContainText(
    "before damage and weakness bonuses",
  );
  await page.getByRole("button", { name: /^neck .*Elemental amulet/ }).click();
  await expect(
    page.getByRole("heading", { name: "Elemental amulet", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Elemental amulet bonus")).toContainText(
    "+2 base max hit",
  );
});
