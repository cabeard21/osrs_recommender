import { expect, test } from "@playwright/test";

test("exports displayed equipment with copy feedback and a selectable fallback", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: async (text: string) => {
          document.documentElement.dataset.copiedBankTag = text;
        },
      },
    });
  });
  await page.request.post("/test/seed-optimization");
  await page.goto("/gear-next/");
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
  const role = data.scenario.roles[0].id;
  const equipment: Record<string, number> =
    data.result.selected_solution.loadouts[role].equipment;
  const positions: [string, number, number][] = [
    ["head", 1, 0],
    ["cape", 0, 1],
    ["neck", 1, 1],
    ["ammo", 2, 1],
    ["weapon", 0, 2],
    ["body", 1, 2],
    ["shield", 2, 2],
    ["legs", 1, 3],
    ["hands", 0, 4],
    ["feet", 1, 4],
    ["ring", 2, 4],
  ];
  const entries = positions.filter(([slot]) => equipment[slot] != null);
  const expected = [
    1,
    entries.length,
    ...entries.flatMap(([slot, x, y]) => [equipment[slot], x, y]),
  ].join(",");
  const action = page.getByRole("button", { name: "Export mobile bank tag" });
  await action.click();
  const dialog = page.getByRole("dialog", { name: "Export mobile bank tag" });
  const code = dialog.getByRole("textbox", { name: "Bank tag code" });
  await expect(code).toHaveValue(expected);
  await expect(code).toHaveAttribute("readonly", "");
  await dialog.getByRole("button", { name: "Copy code" }).click();
  await expect(page.locator("html")).toHaveAttribute(
    "data-copied-bank-tag",
    expected,
  );
  await expect(dialog.getByRole("status")).toContainText(/copied/i);
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(action).toBeFocused();

  await page.evaluate(() => {
    navigator.clipboard.writeText = async () => {
      throw new Error("Clipboard permission denied");
    };
  });
  await action.click();
  await dialog.getByRole("button", { name: "Copy code" }).click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  await expect(code).toHaveValue(expected);
  await code.focus();
  await page.keyboard.press("ControlOrMeta+A");
  expect(
    await code.evaluate((element: HTMLTextAreaElement) =>
      element.value.slice(element.selectionStart, element.selectionEnd),
    ),
  ).toBe(expected);
  expect(errors).toEqual([]);
});
