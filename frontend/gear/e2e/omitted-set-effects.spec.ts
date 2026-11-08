import { expect, test } from "@playwright/test";

test("single result reveals omitted bonus disclosure without hiding supported metrics", async ({
  page,
}) => {
  const omission = "Obsidian set bonus is omitted; ordinary base stats only.";
  await page.request.post("/test/seed-optimization");
  // Exercise the browser disclosure with the real optimization transport;
  // catalog/combat tests independently establish the obsidian omission metadata.
  await page.route("**/ui-api/gear/optimizations*", async (route) => {
    const response = await route.fetch();
    expect(response.status()).toBe(200);
    const body = await response.json();
    const loadouts = body.result.selected_solution.loadouts as Record<
      string,
      { performance: { supported: boolean; limitations: string[] } }
    >;
    for (const loadout of Object.values(loadouts)) {
      expect(loadout.performance.supported).toBe(true);
      loadout.performance.limitations = [
        ...loadout.performance.limitations,
        omission,
      ];
    }
    await route.fulfill({ response, json: body });
  });
  await page.goto("/gear-next/");
  await page.getByLabel("Additional purchase budget (GP)").fill("0");
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "Best configuration found",
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByText(omission, { exact: true })).not.toBeVisible();
  await page.getByText("Combat model limitations", { exact: true }).click();
  await expect(page.getByText(omission, { exact: true })).toBeVisible();
  await expect(page.getByText("Calculated DPS", { exact: true })).toBeVisible();
});
