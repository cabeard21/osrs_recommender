import { expect, test } from "@playwright/test";

test("prepares an owned tome and preserves the Searing setting", async ({
  page,
}) => {
  expect((await page.request.post("/test/seed-tome")).ok()).toBe(true);
  await page.goto("/gear-next/");
  await expect(
    page.getByRole("button", { name: "Refresh account", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Run optimization", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "magic", exact: true }).click();
  await page.getByLabel("Tome of Fire pages").selectOption("searing");
  await expect
    .poll(() =>
      page.evaluate(() =>
        Object.keys(sessionStorage).some(
          (key) =>
            key.startsWith("gear-drafts-") &&
            JSON.parse(sessionStorage.getItem(key) ?? "null")?.single
              ?.fireTomePages === "searing",
        ),
      ),
    )
    .toBe(true);
  await page.reload();
  await expect(page.getByLabel("Tome of Fire pages")).toHaveValue("searing");
  const pending = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/ui-api/gear/optimizations" &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const response = await pending;
  expect(response.status(), await response.text()).toBe(200);
  expect(response.request().postDataJSON().fire_tome_pages).toBe("searing");
  const loadout = (await response.json()).result.selected_solution.loadouts[
    "role-1"
  ];
  expect(loadout.equipment.shield).toBe(20714);
  expect(loadout.performance.tome_bonus.fire_pages).toBe("searing");
  await expect(page.getByLabel("Elemental tome effect").first()).toContainText(
    "searing",
  );
  await expect(
    page
      .getByText(/page availability, consumption, and costs are excluded/i)
      .first(),
  ).toBeVisible();
});
