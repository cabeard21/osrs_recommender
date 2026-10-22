import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mkdir } from "node:fs/promises";
const screenshots = "../../docs/ui/gear-preview";
test("five cohesive states, keyboard inspector, persistence, and responsive layout", async ({
  page,
}, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/gear-next/?mode=fixture");
  await expect(
    page.getByText("Demo adventurer", { exact: true }),
  ).toBeVisible();
  await mkdir(screenshots, { recursive: true });
  await expect(
    page.getByRole("button", { name: "Run fixture optimization" }),
  ).toBeEnabled();
  await page.screenshot({
    path: `${screenshots}/${testInfo.project.name}-baseline.png`,
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  const budget = page.getByLabel("Additional purchase budget (GP)");
  await budget.fill("12345");
  await page.getByRole("button", { name: "Run fixture optimization" }).click();
  await expect(
    page.getByText("Submitted scenario // fixture result"),
  ).toBeVisible();
  await page.screenshot({
    path: `${screenshots}/${testInfo.project.name}-result.png`,
    fullPage: true,
  });
  for (const slot of [
    "head",
    "cape",
    "neck",
    "ammo",
    "weapon",
    "body",
    "shield",
    "legs",
    "hands",
    "feet",
    "ring",
  ]) {
    const button = page.getByRole("button", { name: new RegExp(`^${slot} `) });
    await button.focus();
    await page.keyboard.press("Enter");
    await expect(
      page.getByRole("dialog", { name: "Item inspector" }),
    ).toBeVisible();
    if (slot === "weapon") {
      await page
        .getByRole("button", { name: "Preview comparison", exact: true })
        .first()
        .click();
      await expect(
        page.getByText("Manual trial · fixture preview"),
      ).toBeVisible();
      await page.screenshot({
        path: `${screenshots}/${testInfo.project.name}-inspector.png`,
        fullPage: true,
      });
      const accessibility = await new AxeBuilder({ page }).analyze();
      expect(accessibility.violations).toEqual([]);
      // Browser-native dialog must trap focus.
      await page.keyboard.press("Tab");
      if (testInfo.project.name === "mobile")
        expect(
          await page.evaluate(
            () => !!document.activeElement?.closest("dialog"),
          ),
        ).toBe(true);
    }
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(button).toBeFocused();
  }
  await page.getByRole("button", { name: "Multi-style", exact: true }).click();
  await expect(budget).toHaveValue("12345");
  await page.getByRole("button", { name: "Run fixture optimization" }).click();
  await expect(
    page.getByRole("button", { name: /Configuration 2 weapon / }),
  ).toBeVisible();
  await page.screenshot({
    path: `${screenshots}/${testInfo.project.name}-multi-side.png`,
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Interactive switching", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Configuration 2", exact: true })
    .click();
  await expect(
    page.getByRole("button", {
      name: /Configuration 2 weapon .*Rune crossbow/,
    }),
  ).toBeVisible();
  await page.screenshot({
    path: `${screenshots}/${testInfo.project.name}-multi-interactive.png`,
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
  await page.getByRole("button", { name: "Single-style", exact: true }).click();
  await expect(
    page.getByText("Submitted scenario // fixture result"),
  ).toBeVisible();
  await expect(budget).toHaveValue("12345");
  await page.reload();
  await expect(budget).toHaveValue("12345");
  await expect(
    page.getByText("Submitted scenario // fixture result"),
  ).toHaveCount(0);
  expect(errors).toEqual([]);
});
test("retained Gear, dashboard, health and API boundary remain available", async ({
  page,
  request,
}) => {
  expect((await request.get("/healthz")).status()).toBe(200);
  expect((await request.post("/api/sync", { data: {} })).status()).toBe(401);
  expect((await request.get("/ui-api/gear/context")).status()).toBe(200);
  await page.goto("/gear");
  await expect(page.locator("[data-testid=gear-optimizer]")).toBeVisible();
  await page.goto("/");
  await expect(
    page.getByRole("link", { name: "Gear", exact: true }),
  ).toBeVisible();
});
