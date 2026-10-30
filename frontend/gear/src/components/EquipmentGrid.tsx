import { useEffect, useState } from "react";
import { Shield } from "lucide-react";
import type { Equipment, Slot } from "../api/contracts";
import { slots } from "../api/contracts";
import { useGear } from "../state/GearProvider";
export function ItemSprite({ id }: { id: number | null }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [id]);
  return id && !failed ? (
    <img
      src={`/gear-sprites/${id}.png`}
      alt=""
      onError={() => setFailed(true)}
      width="36"
      height="36"
    />
  ) : (
    <Shield size={27} aria-hidden="true" />
  );
}
export function EquipmentGrid({
  equipment,
  shared = [],
  differences = [],
  selected,
  onSelect,
  prefix = "",
  optimized = false,
}: {
  equipment: Equipment;
  shared?: number[];
  differences?: Slot[];
  selected: Slot | null;
  onSelect: (slot: Slot) => void;
  prefix?: string;
  optimized?: boolean;
}) {
  const { itemById, state, liveMode } = useGear();
  return (
    <div className="equipment-grid" aria-label={`${prefix} equipment slots`}>
      {slots.map((slot) => {
        const item = itemById(equipment[slot]),
          isShared = shared.includes(equipment[slot] ?? -1);
        const observation =
          liveMode && !optimized
            ? state.context?.live?.current_equipment.slots[slot]
            : undefined;
        const label =
          liveMode && optimized
            ? isShared
              ? "Shared"
              : equipment[slot]
                ? "selected"
                : "empty"
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
            : liveMode && label !== "empty"
              ? `${label} equipment`
              : "Empty slot");
        return (
          <button
            key={slot}
            className={`equipment-slot slot-${slot} ${selected === slot ? "selected" : ""}`}
            aria-label={`${prefix}${slot} ${label}${differences.includes(slot) ? " · Different" : ""} ${name}${item?.facts?.support_status === "community_assumed" ? " Community-assumed" : item?.facts?.support_status === "verified" ? " Verified" : ""}`}
            aria-pressed={selected === slot}
            onClick={() => onSelect(slot)}
          >
            <span className="slot-label">
              {slot}{" "}
              <span className={isShared ? "green" : "blue"}>{label}</span>
              {differences.includes(slot) && (
                <span className="blue"> · Different</span>
              )}
            </span>{" "}
            <span className="item-content">
              <span className="sprite">
                <ItemSprite id={equipment[slot]} />
              </span>
              <span>
                {name}
                {item?.facts?.support_status === "community_assumed" && (
                  <small className="gold"> Community-assumed</small>
                )}
                {item?.facts?.support_status === "verified" && (
                  <small className="green"> Verified</small>
                )}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
