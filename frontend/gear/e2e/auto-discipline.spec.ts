import { expect, test } from "@playwright/test";

for (const priority of ["default", "prayer_bonus"]) {
  test(`Single Auto browses permitted disciplines with ${priority}`, async ({
    page,
  }) => {
    await page.request.post("/test/seed-optimization");
    await page.goto("/gear-next/");
    if (priority !== "default") {
      await page
        .locator("summary")
        .filter({ hasText: /^Advanced settings/ })
        .click();
      await page
        .getByRole("combobox", { name: "Tradeoff metric", exact: true })
        .selectOption(priority);
    }
    const auto = page.getByRole("button", { name: "Auto", exact: true });
    await expect(auto).toHaveAttribute("aria-pressed", "false");
    await auto.click();
    await page.getByRole("checkbox", { name: "magic", exact: true }).uncheck();
    const response = page.waitForResponse(
      (r) =>
        new URL(r.url()).pathname === "/ui-api/gear/optimizations" &&
        r.request().method() === "POST",
    );
    await page
      .getByRole("button", { name: "Run optimization", exact: true })
      .click();
    const reply = await response;
    expect(reply.status(), await reply.text()).toBe(200);
    const data = await reply.json();
    expect(data.scenario.roles[0].allowed_disciplines).toEqual([
      "melee",
      "ranged",
    ]);
    expect(
      data.result.discipline_comparison.map(
        (r: { discipline: string }) => r.discipline,
      ),
    ).toEqual(["melee", "ranged"]);
    await expect(page.getByLabel("Combat discipline comparison")).toBeVisible();
    await expect(page.getByText(/Auto selected melee/)).toBeVisible();
    await expect(
      page.getByRole("tab", { name: "Auto overall" }),
    ).toHaveAttribute("aria-selected", "true");
    await page.getByRole("tab", { name: "Ranged", exact: true }).click();
    await expect(page.getByText("Viewing ranged loadouts")).toBeVisible();
    await expect(
      page.getByRole("tab", { name: "Magic", exact: true }),
    ).toHaveCount(0);
    await page.getByRole("tab", { name: "Melee", exact: true }).click();
    await expect(page.getByText("Viewing melee loadouts")).toBeVisible();
    if (priority !== "default") {
      await expect(
        page.getByRole("table", { name: "DPS and metric tradeoffs" }),
      ).toBeVisible();
      await page
        .getByRole("button", { name: "Select tradeoff 1", exact: true })
        .click();
      await expect(
        page.getByRole("tab", { name: "Melee", exact: true }),
      ).toHaveAttribute("aria-selected", "true");
    }
    await page.getByRole("button", { name: /^weapon .*Rune scimitar/ }).click();
    await expect(
      page.getByRole("heading", { name: "Rune scimitar", exact: true }),
    ).toBeVisible();
  });
}
