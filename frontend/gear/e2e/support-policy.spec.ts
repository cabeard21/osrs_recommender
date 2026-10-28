import { expect, test } from "@playwright/test";

test("equipment support policy defaults to community and roundtrips strict selection", async ({
  page,
}) => {
  await page.goto("/gear-next/?mode=fixture");
  const policy = page.getByRole("combobox", {
    name: "Equipment support policy",
  });
  await expect(policy).toHaveValue("community_best_effort");
  await page.getByRole("button", { name: "Run fixture optimization" }).click();
  await expect(
    page.getByRole("region", { name: "Equipment support policy result" }),
  ).toContainText("Community best effort");
  await policy.selectOption("verified_only");
  await page.getByRole("button", { name: "Run fixture optimization" }).click();
  await expect(
    page.getByRole("region", { name: "Equipment support policy result" }),
  ).toContainText("Verified only");
  await page.reload();
  await expect(policy).toHaveValue("verified_only");
});
