import { expect, test } from "@playwright/test";
import { npcEntryLabel } from "../src/components/npcEntries";

test("NPC current HP survives reload and reaches optimization; result explains bolt and hopper effects", async ({
  page,
}) => {
  expect((await page.request.post("/test/seed-bolt-hopper")).ok()).toBe(true);
  await page.goto("/gear-next/");
  await page.getByRole("button", { name: "ranged", exact: true }).click();
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
  await page
    .locator("summary")
    .filter({ hasText: /^Target hitpoints/ })
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
  const body = await result.json();
  expect(body.scenario.roles[0].target.current_hitpoints).toBe(1);
  const loadout = body.result.selected_solution.loadouts["role-1"];
  expect(loadout.equipment.weapon).toBe(9185);
  expect(loadout.equipment.ammunition).toBe(9242);
  expect(loadout.equipment.shield).toBe(32879);
  expect(loadout.performance.bolt_effect.family).toBe("ruby");
  expect(loadout.performance.aquanite_hopper.approximate).toBe(true);
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
        "Aquanite hopper secondary ruby damage uses the same static target HP as the primary shot.",
      )
      .first(),
  ).toBeVisible();
  const native = await (
    await page.request.get("/test/native-diagnostics")
  ).json();
  expect(native.enabled).toBe(process.env.GEAR_E2E_NATIVE === "1");
  if (native.enabled) {
    expect(native.native_requests).toBeGreaterThan(0);
    expect(native.fallback_requests).toBe(0);
    expect(
      native.events.some((event: { event: string }) => event.event === "stage"),
    ).toBe(true);
  }
});
