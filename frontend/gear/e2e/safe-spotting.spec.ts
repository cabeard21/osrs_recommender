import { expect, test } from "@playwright/test";

test("safe spotting persists and restricts optimization and exact weapon trials", async ({
  page,
}) => {
  expect((await page.request.post("/test/seed-safespot")).ok()).toBe(true);
  await page.goto("/gear-next/");
  await expect(
    page.getByRole("button", { name: "Run optimization", exact: true }),
  ).toBeEnabled();
  const toggle = page.getByRole("checkbox", {
    name: "Safe spotting",
    exact: true,
  });
  await toggle.check();
  await expect
    .poll(() => page.evaluate(() => JSON.stringify(sessionStorage)))
    .toContain('safeSpotting\\\":true');
  await page.reload();
  await expect(toggle).toBeChecked();
  const pending = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname.endsWith("/ui-api/gear/optimizations") &&
      r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const optimized = await pending;
  expect(optimized.status(), await optimized.text()).toBe(200);
  const result = await optimized.json();
  expect(result.scenario.roles[0].safe_spotting).toBe(true);
  expect(result.scenario.roles[0].fight_duration_seconds).toBe(60);
  const loadout = result.result.selected_solution.loadouts["role-1"];
  expect([3198, 3202]).toContain(loadout.equipment.weapon);
  await page.getByRole("button", { name: /^weapon .*halberd/i }).click();
  const alternative =
    loadout.equipment.weapon === 3202 ? "Mithril halberd" : "Rune halberd";
  const trial = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname.endsWith("/ui-api/gear/evaluations") &&
      r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: `Try ${alternative}`, exact: true })
    .click();
  const response = await trial;
  expect(response.status(), await response.text()).toBe(200);
  const evaluated = await response.json();
  expect(evaluated.proposed.status).toBe("valid");
  expect(evaluated.scenario_fingerprint).toBe(result.scenario_fingerprint);
  expect(evaluated.assumptions_fingerprint).toBe(
    result.result.assumptions_fingerprint,
  );
  await expect(
    page.getByRole("table", { name: "Manual trial comparison" }),
  ).toBeVisible();
  const native = await (
    await page.request.get("/test/native-diagnostics")
  ).json();
  if (native.enabled) {
    expect(native.native_requests).toBeGreaterThan(0);
    expect(native.fallback_requests).toBe(0);
  }
});
