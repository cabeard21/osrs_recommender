import { expect, test } from "@playwright/test";

for (const [priority, , styles] of [
  ["stab_magic_defence_roll", "Stab & magic defence roll", ["stab", "magic"]],
  [
    "stab_ranged_defence_roll",
    "Stab & ranged defence roll",
    ["stab", "ranged"],
  ],
  [
    "stab_magic_ranged_defence_roll",
    "Stab & magic & ranged defence roll",
    ["stab", "magic", "ranged"],
  ],
  [
    "slash_magic_defence_roll",
    "Slash & magic defence roll",
    ["slash", "magic"],
  ],
  [
    "slash_ranged_defence_roll",
    "Slash & ranged defence roll",
    ["slash", "ranged"],
  ],
  [
    "slash_magic_ranged_defence_roll",
    "Slash & magic & ranged defence roll",
    ["slash", "magic", "ranged"],
  ],
  [
    "crush_magic_defence_roll",
    "Crush & magic defence roll",
    ["crush", "magic"],
  ],
  [
    "crush_ranged_defence_roll",
    "Crush & ranged defence roll",
    ["crush", "ranged"],
  ],
  [
    "crush_magic_ranged_defence_roll",
    "Crush & magic & ranged defence roll",
    ["crush", "magic", "ranged"],
  ],
  ["melee_defence_roll", "Melee defence roll", ["stab", "slash", "crush"]],
  [
    "melee_magic_defence_roll",
    "Melee & magic defence roll",
    ["stab", "slash", "crush", "magic"],
  ],
  [
    "melee_ranged_defence_roll",
    "Melee & ranged defence roll",
    ["stab", "slash", "crush", "ranged"],
  ],
] as const) {
  test(`${priority} restores a complete boosted objective configuration`, async ({
    page,
  }) => {
    await page.request.post("/test/seed-optimization");
    await page.goto("/gear-next/");
    await page
      .locator("summary")
      .filter({ hasText: /^Advanced settings/ })
      .click();
    for (const style of styles)
      await page.getByRole("checkbox", { name: style, exact: true }).check();
    await page
      .getByRole("checkbox", { name: "Optimize potions", exact: true })
      .check();
    await page
      .getByRole("checkbox", { name: "Defence potion", exact: true })
      .check();
    const pending = page.waitForResponse(
      (r) =>
        new URL(r.url()).pathname === "/ui-api/gear/optimizations" &&
        r.request().method() === "POST",
    );
    await page
      .getByRole("button", { name: "Run optimization", exact: true })
      .click();
    const response = await pending;
    expect(response.status(), await response.text()).toBe(200);
    const body = await response.json();
    const definition = body.result.objective_definitions[0];
    expect(new Set(definition.styles)).toEqual(new Set(styles));
    const region = page.getByRole("region", { name: "Objective tradeoffs" });
    await expect(region).toBeVisible();
    await region
      .getByRole("button", { name: "Highest " + definition.label, exact: true })
      .click();
    await expect(
      page.getByRole("table", { name: "All objective tradeoffs" }),
    ).toBeVisible();
    await expect(
      page.getByLabel("Selected combat configuration"),
    ).toBeVisible();
    expect(body.run_id).toBeTruthy();
    const manifest = await page.request.get(
      "/ui-api/gear/optimization-runs/" + body.run_id,
    );
    expect(manifest.status()).toBe(200);
  });
}
