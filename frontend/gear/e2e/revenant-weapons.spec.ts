import { expect, test } from "@playwright/test";

test("a locked charged mace gains its Wilderness passive and spends ether in both locations", async ({
  page,
}) => {
  expect((await page.request.post("/test/seed-chainmace")).ok()).toBe(true);
  await page.goto("/gear-next/");
  await page.getByRole("button", { name: "melee", exact: true }).click();
  await page.getByText("Equipment locks & exclusions", { exact: true }).click();
  await page.getByLabel("Physical item ID or empty").fill("22545");
  await page
    .getByRole("button", { name: "Set equipment lock", exact: true })
    .click();
  await page
    .locator("summary")
    .filter({ hasText: /^Tradeoff objectives/ })
    .click();
  await page
    .getByRole("checkbox", {
      name: "Running cost (GP per damage)",
      exact: true,
    })
    .check();
  async function run() {
    const pending = page.waitForResponse(
      (r) =>
        new URL(r.url()).pathname === "/ui-api/gear/optimizations" &&
        r.request().method() === "POST",
    );
    await page
      .getByRole("button", { name: /^(Run optimization|Reoptimize)$/ })
      .click();
    const reply = await pending;
    expect(reply.status(), await reply.text()).toBe(200);
    const { result } = await reply.json();
    const loadout = result.selected_solution.loadouts["role-1"];
    expect(loadout.equipment.weapon).toBe(22545);
    await expect(
      page.getByLabel("Calculated combat performance"),
    ).toContainText(`Calculated DPS${loadout.performance.dps.toFixed(2)}`);
    await expect(
      page.getByLabel("Selected combat configuration"),
    ).toContainText("Viggora's chainmace (charged)");
    await expect(
      page
        .getByText(/Revenant ether: 1 consumed per attack at 10 GP each/)
        .first(),
    ).toBeVisible();
    const checklist = page.getByRole("region", {
      name: "Acquisition checklist",
    });
    await expect(checklist).toContainText("15,000 GP/hour");
    await expect(
      checklist.getByRole("region", { name: "Prepare" }),
    ).toContainText(
      "Viggora's chainmace (uncharged) (#22542) → Viggora's chainmace (charged) (#22545)",
    );
    return loadout.performance.dps as number;
  }
  const outsideDps = await run();
  const passive = page.getByLabel("Wilderness weapon passive");
  await expect(passive).toContainText("inactive");
  await page.getByLabel("Wilderness", { exact: true }).check();
  await page.getByLabel("Max gear loss if PK’d (GP)").fill("1m");
  expect(await run()).toBeGreaterThan(outsideDps);
  await expect(passive).toContainText("+50% attack roll");
  await expect(
    page.getByRole("region", { name: "Wilderness risk" }),
  ).toContainText("Revenant ether");
  const diagnostics = await (
    await page.request.get("/test/native-diagnostics")
  ).json();
  if (diagnostics.enabled) {
    expect(diagnostics.native_requests).toBeGreaterThan(0);
    expect(diagnostics.fallback_requests).toBe(0);
  }
});
