import { expect, test } from "@playwright/test";

for (const spellId of ["iban_blast", "ice_burst", "blood_barrage"]) {
  test(`Magic fixed spell selection includes and retains ${spellId}`, async ({
    page,
  }) => {
    await page.request.post("/test/seed-optimization");
    await page.goto("/gear-next/");
    await page.getByRole("button", { name: "magic", exact: true }).click();
    // The summary also shows a selection count after the title.
    await page
      .locator("summary")
      .filter({ hasText: /^Combat Options/ })
      .click();
    await page
      .getByRole("checkbox", {
        name: "Optimize attack type, stance and spell with equipment",
      })
      .uncheck();
    const spell = page.getByRole("combobox", {
      name: "Spell",
      exact: true,
    });
    await spell.selectOption(spellId);
    await expect(spell).toHaveValue(spellId);
    await page.reload();
    await expect(
      page.getByRole("combobox", { name: "Spell", exact: true }),
    ).toHaveValue(spellId);
  });
}
