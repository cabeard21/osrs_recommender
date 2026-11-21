import { expect, test, type Page } from "@playwright/test";
import { npcEntryLabel } from "../src/components/npcEntries";

async function selectNpc(page: Page, npcId: number) {
  const response = await page.request.get(`/ui-api/gear/targets?q=${npcId}`);
  expect(response.ok()).toBe(true);
  const { items } = await response.json();
  const entry = items.find((item: { npc_id: number }) => item.npc_id === npcId);
  expect(entry).toBeTruthy();
  await page
    .getByRole("searchbox", { name: "Search NPCs" })
    .fill(String(npcId));
  await page
    .getByRole("button", { name: npcEntryLabel(entry), exact: true })
    .click();
  return entry;
}

test("a restored Feral Vampyre target accepts ordinary gear and reports its tier", async ({
  page,
}) => {
  expect((await page.request.post("/test/seed-optimization")).ok()).toBe(true);
  await page.goto("/gear-next/");
  const feral = await selectNpc(page, 3237);
  await expect(page.getByLabel("Vampyre target restrictions")).toContainText(
    /tier 1/i,
  );
  await page.reload();
  await expect(page.getByLabel("Vampyre target restrictions")).toBeVisible();
  const result = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname.endsWith("/ui-api/gear/optimizations") &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const response = await result;
  expect(response.status(), await response.text()).toBe(200);
  const body = await response.json();
  const role = body.scenario.roles[0];
  expect(role.target_selection.key).toBe(feral.key);
  expect(role.target.traits).toContain("vampyre1");
  expect(
    body.result.selected_solution.loadouts[role.id].performance.vampyre_bonus,
  ).toMatchObject({
    tier: 1,
    attack_source: "ordinary",
    ring_active: false,
  });
  await expect(page.getByLabel("Vampyre effect").first()).toContainText(
    "Tier 1 vampyre · Ordinary attack",
  );
});

test("the NPC picker explains the restriction on the Vanstrom quest encounter", async ({
  page,
}) => {
  await page.goto("/gear-next/");
  const vanstrom = await selectNpc(page, 9567);
  expect(vanstrom.support_status).toBe("unsupported");
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: /Vanstrom Klause cannot be optimized/ }),
  ).toBeVisible();
  await expect(
    page.getByText(vanstrom.reasons[0], { exact: true }).first(),
  ).toBeVisible();
});

test("a draft with the former blocked NPC profile can be reselected and scored", async ({
  page,
}) => {
  expect((await page.request.post("/test/seed-optimization")).ok()).toBe(true);
  const detailRoute = "**/ui-api/gear/targets/*";
  await page.route(detailRoute, async (route) => {
    const response = await route.fetch();
    const current = await response.json();
    await route.fulfill({
      response,
      json: {
        ...current,
        catalog_revision: "before-vampyre-support",
        support_status: "unsupported",
        reasons: ["Vampyre targets have weapon-specific damage adjustments."],
        target: { ...current.target, traits: [] },
      },
    });
  });
  await page.goto("/gear-next/");
  await selectNpc(page, 3237);
  await expect(
    page.getByText(/Feral Vampyre cannot be optimized/),
  ).toBeVisible();
  await page.unroute(detailRoute);
  await page.reload();
  await expect(page.getByText(/NPC catalog changed/)).toBeVisible();
  await selectNpc(page, 3237);
  await expect(page.getByText(/NPC catalog changed/)).toHaveCount(0);
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  await expect(page.getByLabel("Vampyre effect").first()).toContainText(
    "Tier 1 vampyre",
  );
});

test("an ordinary weapon locked on a Juvinate explains the missing ring", async ({
  page,
}) => {
  expect((await page.request.post("/test/seed-optimization")).ok()).toBe(true);
  await page.goto("/gear-next/");
  await selectNpc(page, 4427);
  await page.getByText("Equipment locks & exclusions", { exact: true }).click();
  await page.getByLabel("Physical item ID or empty").fill("1333");
  await page
    .getByRole("button", { name: "Set equipment lock", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  await expect(
    page.getByLabel("Equipment and target constraints"),
  ).toContainText(/Efaritay/);
});
