import { expect, test } from "@playwright/test";

test("Magic fixed spell selection includes and retains Iban Blast", async ({
  page,
}) => {
  await page.request.post("/test/seed-optimization");
  await page.goto("/gear-next/");
  await page.getByRole("button", { name: "magic", exact: true }).click();
  await page.getByText("Combat Options", { exact: true }).click();
  await page
    .getByRole("checkbox", {
      name: "Optimize attack type, stance and spell with equipment",
    })
    .uncheck();
  const spell = page.getByRole("combobox", {
    name: "Standard spell",
    exact: true,
  });
  await spell.selectOption("iban_blast");
  await expect(spell).toHaveValue("iban_blast");
  await page.reload();
  await expect(
    page.getByRole("combobox", { name: "Standard spell", exact: true }),
  ).toHaveValue("iban_blast");
});
