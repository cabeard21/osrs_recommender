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
  selected,
  onSelect,
  prefix = "",
}: {
  equipment: Equipment;
  shared?: number[];
  selected: Slot | null;
  onSelect: (slot: Slot) => void;
  prefix?: string;
}) {
  const { itemById } = useGear();
  return (
    <div className="equipment-grid" aria-label={`${prefix} equipment slots`}>
      {slots.map((slot) => {
        const item = itemById(equipment[slot]),
          isShared = shared.includes(equipment[slot] ?? -1);
        return (
          <button
            key={slot}
            className={`equipment-slot slot-${slot} ${selected === slot ? "selected" : ""}`}
            aria-label={`${prefix}${slot} ${isShared ? "Shared" : item ? "Fixture" : "Empty"} ${item?.name ?? "Empty slot"}`}
            aria-pressed={selected === slot}
            onClick={() => onSelect(slot)}
          >
            <span className="slot-label">
              {slot}{" "}
              <span className={isShared ? "green" : "blue"}>
                {isShared ? "Shared" : item ? "Fixture" : "Empty"}
              </span>
            </span>{" "}
            <span className="item-content">
              <span className="sprite">
                <ItemSprite id={equipment[slot]} />
              </span>
              <span>{item?.name ?? "Empty slot"}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
