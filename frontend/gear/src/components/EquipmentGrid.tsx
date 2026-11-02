import { useEffect, useState } from "react";
import {
  CircleDot,
  Crosshair,
  Flag,
  Footprints,
  Gem,
  Hand,
  HardHat,
  ImageOff,
  PersonStanding,
  Shield,
  Shirt,
  Sword,
  type LucideIcon,
} from "lucide-react";
import type { Equipment, Item, Slot } from "../api/contracts";
import { slots } from "../api/contracts";
import { useGear } from "../state/GearProvider";
function acquisitionStatus(
  id: number | null,
  item: Item | undefined,
  purchaseIds: number[],
) {
  if (!id) return "Empty";
  if (purchaseIds.includes(id)) return "Buy";
  return item?.owned ? "Owned" : "Unconfirmed";
}
const statusColor: Record<string, string> = { Buy: "gold", Owned: "green" };
const SLOT_ICONS: Record<Slot, LucideIcon> = {
  head: HardHat,
  cape: Flag,
  neck: Gem,
  ammo: Crosshair,
  weapon: Sword,
  body: Shirt,
  shield: Shield,
  legs: PersonStanding,
  hands: Hand,
  feet: Footprints,
  ring: CircleDot,
};
export function ItemSprite({ id, slot }: { id: number | null; slot?: Slot }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [id]);
  if (id && !failed)
    return (
      <img
        src={`/gear-sprites/${id}.png`}
        alt=""
        onError={() => setFailed(true)}
        width="36"
        height="36"
      />
    );
  if (id) return <ImageOff size={27} aria-hidden="true" />;
  const SlotIcon = slot ? SLOT_ICONS[slot] : Shield;
  return <SlotIcon className="slot-icon" size={27} aria-hidden="true" />;
}
export function EquipmentGrid({
  equipment,
  shared = [],
  differences = [],
  differenceLabel = "Different",
  selected,
  onSelect,
  prefix = "",
  optimized = false,
  purchaseIds = [],
  roleId,
}: {
  equipment: Equipment;
  shared?: number[];
  differences?: Slot[];
  differenceLabel?: string;
  selected: Slot | null;
  onSelect: (slot: Slot) => void;
  prefix?: string;
  optimized?: boolean;
  purchaseIds?: number[];
  roleId?: string;
}) {
  const { itemById, state, liveMode, current } = useGear();
  const roleLocks = current.draft.roles.find((r) => r.id === roleId)?.locks;
  const isLocked = (slot: Slot) =>
    [roleLocks?.[slot], current.draft.globalLocks?.[slot]].some(
      (lock) => lock !== undefined && lock === equipment[slot],
    );
  return (
    <div
      className="equipment-grid"
      role="group"
      aria-label={`${prefix} equipment slots`}
    >
      {slots.map((slot) => {
        const item = itemById(equipment[slot]),
          isShared = shared.includes(equipment[slot] ?? -1);
        const observation =
          liveMode && !optimized
            ? state.context?.live?.current_equipment.slots[slot]
            : undefined;
        const status = acquisitionStatus(equipment[slot], item, purchaseIds);
        const label =
          liveMode && optimized
            ? [status, isShared && "Shared", isLocked(slot) && "Locked"]
                .filter(Boolean)
                .join(" · ")
            : liveMode
              ? (observation?.status ?? "unknown")
              : isShared
                ? "Shared"
                : item
                  ? "Fixture"
                  : "Empty";
        const name =
          item?.name ??
          (equipment[slot]
            ? `Item #${equipment[slot]} · metadata unavailable`
            : liveMode && !optimized && label !== "empty"
              ? `${label} equipment`
              : "Empty slot");
        return (
          <button
            key={slot}
            className={`equipment-slot slot-${slot} ${selected === slot ? "selected" : ""}`}
            aria-label={`${prefix}${slot} ${label}${differences.includes(slot) ? ` · ${differenceLabel}` : ""} ${name}${item?.facts?.support_status === "community_assumed" ? " Community-assumed" : item?.facts?.support_status === "verified" ? " Verified" : ""}`}
            aria-pressed={selected === slot}
            onClick={() => onSelect(slot)}
          >
            <span className="slot-label">
              {slot}{" "}
              <span
                className={
                  (optimized && statusColor[status]) ||
                  (isShared
                    ? "green"
                    : status === "Empty" && optimized
                      ? "muted"
                      : "blue")
                }
              >
                {label}
              </span>
              {differences.includes(slot) && (
                <span className="blue"> · {differenceLabel}</span>
              )}
            </span>{" "}
            <span className="item-content">
              <span className="sprite">
                <ItemSprite id={equipment[slot]} slot={slot} />
              </span>
              <span>
                {name}
                {item?.facts?.support_status === "community_assumed" && (
                  <small className="gold"> Community-assumed</small>
                )}
                {item?.facts?.support_status === "verified" && (
                  <small className="muted"> Verified</small>
                )}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
