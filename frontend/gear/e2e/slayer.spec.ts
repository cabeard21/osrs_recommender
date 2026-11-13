import { expect, test } from "@playwright/test";

test("Slayer task survives reload, reaches optimization and explains the applied mask bonus", async ({
  page,
}) => {
  expect((await page.request.post("/test/seed-slayer")).ok()).toBe(true);
  await page.goto("/gear-next/");
  await expect(
    page.getByRole("button", { name: "Run optimization", exact: true }),
  ).toBeEnabled();
  const checkbox = page.getByRole("checkbox", {
    name: "On a Slayer task",
    exact: true,
  });
  await expect(checkbox).not.toBeChecked();
  await checkbox.check();
  await page.reload();
  await expect(checkbox).toBeChecked();
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
  expect(body.scenario.roles[0].on_slayer_task).toBe(true);
  const loadout = body.result.selected_solution.loadouts["role-1"];
  expect(loadout.equipment.head).toBe(8921);
  expect(loadout.performance.slayer_effects[0].item_id).toBe(8921);
  await expect(page.getByLabel("Slayer task effect").first()).toContainText(
    "+16.67% accuracy and damage",
  );
  const native = await (
    await page.request.get("/test/native-diagnostics")
  ).json();
  if (native.enabled) {
    expect(native.native_requests).toBeGreaterThan(0);
    expect(native.fallback_requests).toBe(0);
  }
});
