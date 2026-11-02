import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { GearContext } from "../api/contracts";
import { RoleFields } from "../components/RoleFields";
import { contextFixture } from "../fixtures/client";
import { newDraft } from "../state/scenario";

test.each([false, true])(
  "fixed magic selection exposes Ancient spells in live mode %s",
  async (liveMode) => {
    const spells = ["rush", "burst", "blitz", "barrage"].flatMap((tier) =>
      ["smoke", "shadow", "blood", "ice"].map((family) => `${family}_${tier}`),
    );
    const draft = newDraft();
    const role = {
      ...draft.roles[0],
      style: "magic" as const,
      autoDiscipline: false,
      combatOptionOptimization: false,
    };
    const onChange = vi.fn();
    const context = {
      ...contextFixture,
      live: { capabilities: { spells: spells.map((id) => ({ id })) } },
    } as unknown as GearContext;
    render(
      <RoleFields
        role={role}
        index={0}
        mode="single"
        draft={{ ...draft, roles: [role] }}
        context={context}
        liveMode={liveMode}
        targets={[]}
        onChange={onChange}
        onRemove={vi.fn()}
      />,
    );
    const select = screen.getByRole("combobox", { name: "Spell" });
    for (const spell of spells) {
      expect(
        screen.getByRole("option", { name: spell.replaceAll("_", " ") }),
      ).toBeInTheDocument();
    }
    await userEvent.selectOptions(select, "ice_barrage");
    expect(onChange).toHaveBeenCalledWith({ spell: "ice_barrage" });
  },
);
