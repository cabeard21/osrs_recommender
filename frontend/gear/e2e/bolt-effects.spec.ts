import { expect, test } from "@playwright/test";
import { npcEntryLabel } from "../src/components/npcEntries";

test("NPC current HP survives reload and reaches optimization; result explains bolt and hopper effects", async ({
  page,
}) => {
  await page.request.post("/test/seed-optimization");
  // Server-side tests cover bolt arithmetic; this injects explanation metadata
  // into a real response to exercise the browser presentation and transport.
  await page.route("**/ui-api/gear/optimizations*", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    if (response.status() === 200 && body.result?.selected_solution) {
      for (const loadout of Object.values(
        body.result.selected_solution.loadouts,
      ) as { performance: Record<string, unknown> }[]) {
        loadout.performance.bolt_effect = {
          family: "ruby",
          proc_chance: 0.06,
          activation_probability: 0.06,
          expected_damage_per_attack: 1,
          total_max_hit: 1,
          normal_max_hit: 1,
          target_hitpoints: 1,
          diary_boosted: false,
          expected_damage_delta: -1,
        };
        loadout.performance.aquanite_hopper = {
          proc_chance: 0.11,
          secondary_accuracy: 0.6,
          secondary_max_hit: 6,
          expected_damage_delta: 0.3,
          expected_ammunition_per_attack: 1.11,
          approximate: true,
          assumptions: [
            "Secondary ruby damage and extra-bolt consumption are approximate.",
          ],
        };
      }
    }
    await route.fulfill({ response, json: body });
  });
  await page.goto("/gear-next/");
  const catalog = await (
    await page.request.get("/ui-api/gear/targets?q=Chicken")
  ).json();
  const entry = catalog.items.find(
    (row: { name: string; support_status: string }) =>
      row.name === "Chicken" && row.support_status === "supported",
  );
  await page.getByRole("searchbox", { name: "Search NPCs" }).fill("Chicken");
  await page
    .getByRole("button", { name: npcEntryLabel(entry), exact: true })
    .click();
  await expect(page.getByLabel("Target base hitpoints")).toHaveAttribute(
    "readonly",
  );
  await page.getByLabel("Target current hitpoints").fill("1");
  await page.reload();
  await expect(page.getByLabel("Target current hitpoints")).toHaveValue("1");
  const pending = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname.endsWith("/ui-api/gear/optimizations") &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const result = await pending;
  expect(result.status(), await result.text()).toBe(200);
  expect((await result.json()).scenario.roles[0].target.current_hitpoints).toBe(
    1,
  );
  await expect(page.getByLabel("Enchanted bolt effect").first()).toContainText(
    "DPS at 1 HP",
  );
  await expect(page.getByLabel("Enchanted bolt effect").first()).toContainText(
    "Primary shot: ruby bolt effect",
  );
  await expect(page.getByLabel("Aquanite hopper effect").first()).toContainText(
    "Approximate Aquanite hopper effect",
  );
  await expect(page.getByLabel("Aquanite hopper effect").first()).toContainText(
    "1.11 expected bolts per attack",
  );
  await expect(
    page
      .getByText(
        "Secondary ruby damage and extra-bolt consumption are approximate.",
      )
      .first(),
  ).toBeVisible();
});
