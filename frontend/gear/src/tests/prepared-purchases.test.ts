import { expect, test } from "vitest";
import { purchaseItemIds } from "../api/preparedPurchases";
import type { Item, PhysicalItem, Preparation } from "../api/contracts";

const preparation: Preparation = {
  source_item_id: null,
  usable_item_id: 28585,
  market_item_id: 28583,
  charging_required: true,
  charges: "unknown",
  activation_reserve: [],
  message: "Charging required",
};
const item: Item = {
  id: 28585,
  name: "Warped sceptre",
  slot: "weapon",
  owned: false,
  price: 92542,
  requirement: "",
  facts: {
    item_id: 28585,
    preparation,
  } as PhysicalItem,
};

test("prepared purchases identify the market form and deduplicate shared preparation", () => {
  expect([
    ...purchaseItemIds([28585], [preparation, preparation], [item]),
  ]).toEqual([28583]);
});

test("a reviewed market route cannot also purchase the charged usable form", () => {
  expect(purchaseItemIds([28585], [preparation], [item]).has(28585)).toBe(
    false,
  );
  expect(purchaseItemIds([28585], undefined, [item]).has(28585)).toBe(false);
});

test("ordinary purchases still require the selected physical item", () => {
  expect([...purchaseItemIds([4151], undefined, [])]).toEqual([4151]);
});

test.each([
  { ...preparation, market_item_id: 1 },
  { ...preparation, usable_item_id: 1 },
  { ...preparation, source_item_id: 1 },
  { ...preparation, market_item_id: -1 },
])("rejects preparation outside selected item facts: %j", (value) => {
  expect(() => purchaseItemIds([28585], [value], [item])).toThrow(
    /preparation/i,
  );
});

test("loadout metadata alone cannot authorize a new purchase identity", () => {
  expect(() =>
    purchaseItemIds([28585], [preparation], [{ ...item, facts: undefined }]),
  ).toThrow(/preparation/i);
});
