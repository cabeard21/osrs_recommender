import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mkdir } from "node:fs/promises";
const screenshots = "../../docs/ui/gear-live";

test("live browser uses real account endpoints, preserves uncertain equipment and isolates demos", async ({
  page,
}, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.request.post("/test/reset-gear");
  await page.goto("/gear-next/");
  await expect(
    page.getByRole("button", { name: "Run optimization" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "No synchronized account" }),
  ).toBeVisible();
  await expect(
    page.getByText(
      "No equipment scan; missing observations do not mean empty slots.",
    ),
  ).toBeVisible();
  await mkdir(screenshots, { recursive: true });
  await page.screenshot({
    path: `${screenshots}/${info.project.name}-missing-scan.png`,
    fullPage: true,
  });
  const now = new Date().toISOString();
  const result = await page.request.post("/api/sync", {
    headers: { Authorization: "Bearer isolated-preview-test-token" },
    data: {
      payload_version: 1,
      observed_at: now,
      player: { username: "player", display_name: "Test account" },
      skills: [{ skill: "attack", level: 75, xp: null }],
      observed_items: [4151, 4587, 99999999, 10828].map((item_id) => ({
        item_id,
        quantity: 1,
        container: "equipment",
      })),
      container_scans: [{ container: "equipment", scanned_at: now }],
    },
  });
  expect(result.status(), await result.text()).toBe(202);
  await page.getByRole("button", { name: "Refresh account" }).click();
  await expect(
    page.getByRole("button", { name: /^weapon ambiguous/ }),
  ).toBeVisible();
  await expect(
    page.getByText("Missing physical metadata for equipped IDs: 99999999"),
  ).toBeVisible();
  await page.screenshot({
    path: `${screenshots}/${info.project.name}-partial-observations.png`,
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: /^weapon ambiguous/ }).click();
  await page
    .getByRole("button", { name: "Inspect #4151", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Abyssal whip", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Eligibility: satisfied", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: `${screenshots}/${info.project.name}-physical-inspector.png`,
    fullPage: true,
  });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.keyboard.press("Escape");
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
    await page.getByRole("button", { name: new RegExp(`^${slot} `) }).click();
    await expect(
      page.getByRole("dialog", { name: "Item inspector" }),
    ).toBeVisible();
    await page.keyboard.press("Escape");
  }
  await expect(page.getByText("Demo adventurer", { exact: true })).toHaveCount(
    0,
  );
  await page
    .getByRole("link", { name: "Open separate fixture demonstration" })
    .click();
  await expect(
    page.getByText("Demo adventurer", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Run fixture optimization" }),
  ).toBeEnabled();
  expect(errors).toEqual([]);
});
