import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { emptyEquipment, slots } from "../api/contracts";
import { mobileBankTag } from "../api/bankTags";
import { BankTagExport } from "../components/BankTagExport";

const equipment = {
  ...emptyEquipment(),
  head: 10828,
  weapon: 4151,
  ring: 2550,
};
const code = "1,3,10828,1,0,4151,0,2,2550,2,4";

it("ignores clipboard feedback from a closed dialog", async () => {
  const user = userEvent.setup();
  let finish!: () => void;
  vi.spyOn(navigator.clipboard, "writeText").mockImplementation(
    () =>
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
  );
  render(<BankTagExport equipment={equipment} name="Loadout" />);
  await user.click(
    screen.getByRole("button", { name: "Export mobile bank tag" }),
  );
  await user.click(screen.getByRole("button", { name: "Copy code" }));
  await user.click(
    screen.getByRole("button", { name: "Close Export mobile bank tag" }),
  );
  await user.click(
    screen.getByRole("button", { name: "Export mobile bank tag" }),
  );
  await act(async () => finish());
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("serializes exact equipped IDs and preserves gaps without changing equipment", () => {
  expect(mobileBankTag(Object.freeze(equipment))).toBe(code);
  expect(mobileBankTag({ ...emptyEquipment(), weapon: 11905, ammo: 892 })).toBe(
    "1,2,892,2,1,11905,0,2",
  );
  expect(
    mobileBankTag(
      Object.fromEntries(
        slots.map((slot, i) => [slot, i + 1]),
      ) as typeof equipment,
    ),
  ).toBe(
    "1,11,1,1,0,2,0,1,3,1,1,4,2,1,5,0,2,6,1,2,7,2,2,8,1,3,9,0,4,10,1,4,11,2,4",
  );
});

it("rejects empty equipment and malformed IDs rather than emitting partial tags", () => {
  expect(mobileBankTag(emptyEquipment())).toBeNull();
  for (const id of [
    0,
    -1,
    1.5,
    NaN,
    Infinity,
    Number.MAX_SAFE_INTEGER + 1,
    "4151",
    undefined,
  ]) {
    expect(
      mobileBankTag({ ...equipment, weapon: id } as typeof equipment),
    ).toBeNull();
  }
});

it("shows a selectable code, copies it and restores focus when closed", async () => {
  const user = userEvent.setup();
  const copy = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
  render(<BankTagExport equipment={equipment} name="Ranged configuration" />);
  const button = screen.getByRole("button", { name: "Export mobile bank tag" });
  await user.click(button);
  expect(screen.getByRole("dialog")).toHaveTextContent("Ranged configuration");
  expect(screen.getByLabelText("Bank tag code")).toHaveValue(code);
  expect(screen.getByLabelText("Bank tag code")).toHaveAttribute("readonly");
  await user.click(screen.getByRole("button", { name: "Copy code" }));
  expect(copy).toHaveBeenCalledWith(code);
  expect(screen.getByRole("status")).toHaveTextContent("Bank tag code copied.");
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(button).toHaveFocus();
});

it("handles denied clipboard access and resets when the equipment changes", async () => {
  const user = userEvent.setup();
  vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(
    new Error("Denied"),
  );
  const { rerender } = render(
    <BankTagExport equipment={equipment} name="Loadout" />,
  );
  await user.click(
    screen.getByRole("button", { name: "Export mobile bank tag" }),
  );
  await user.click(screen.getByRole("button", { name: "Copy code" }));
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Select and copy the code",
  );
  expect(screen.getByLabelText("Bank tag code")).toHaveValue(code);
  rerender(
    <BankTagExport
      equipment={{ ...equipment, weapon: 11905 }}
      name="Loadout"
    />,
  );
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: "Export mobile bank tag" }),
  );
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: "Close Export mobile bank tag" }),
  );
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("disables empty exports and handles a missing clipboard", async () => {
  const user = userEvent.setup();
  const { rerender } = render(
    <BankTagExport equipment={emptyEquipment()} name="Empty" />,
  );
  expect(screen.getByRole("button")).toBeDisabled();
  rerender(<BankTagExport equipment={equipment} name="Loadout" />);
  await user.click(
    screen.getByRole("button", { name: "Export mobile bank tag" }),
  );
  vi.spyOn(navigator, "clipboard", "get").mockReturnValue(
    undefined as unknown as Clipboard,
  );
  await user.click(screen.getByRole("button", { name: "Copy code" }));
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Select and copy the code",
  );
});
