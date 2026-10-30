const icons = import.meta.glob("../assets/stats/*.png", {
  eager: true,
  import: "default",
}) as Record<string, string>;
const groups = {
  Attack: ["stab", "slash", "crush", "ranged", "magic"],
  Defence: [
    "defence_stab",
    "defence_slash",
    "defence_crush",
    "defence_ranged",
    "defence_magic",
  ],
  Other: ["melee_strength", "ranged_strength", "magic_damage", "prayer"],
};
export function EquipmentBonuses({
  bonuses,
  baseline,
  title = "Equipment bonuses",
  changedOnly = false,
}: {
  bonuses?: Record<string, number>;
  baseline?: Record<string, number>;
  title?: string;
  changedOnly?: boolean;
}) {
  return (
    <section className="bonus-panel" aria-label={title}>
      <h3>{title}</h3>
      {Object.entries(groups).map(([group, allKeys]) => {
        const keys = allKeys.filter(
          (key) => !changedOnly || bonuses?.[key] !== baseline?.[key],
        );
        if (!keys.length) return null;
        return (
          <div key={group}>
            <h4>{group}</h4>
            <dl className="bonus-grid">
              {keys.map((key) => {
                const value = bonuses?.[key];
                const before = baseline?.[key];
                const icon = key.startsWith("defence")
                  ? "defence"
                  : key.includes("strength")
                    ? "strength"
                    : key === "magic_damage"
                      ? "magic"
                      : ["ranged", "magic", "prayer"].includes(key)
                        ? key
                        : "attack";
                const format = (v: number) =>
                  `${v > 0 ? "+" : ""}${Number(v.toFixed(2))}${key === "magic_damage" ? "%" : ""}`;
                return (
                  <div key={key}>
                    <dt>
                      <img
                        src={icons[`../assets/stats/${icon}.png`]}
                        alt=""
                        onError={(e) => {
                          e.currentTarget.style.display = "none";
                        }}
                      />
                      {key.replace("defence_", "").replaceAll("_", " ")}
                    </dt>
                    <dd>
                      {baseline && (
                        <span className="muted">
                          {before === undefined ? "—" : format(before)} →{" "}
                        </span>
                      )}
                      {value === undefined ? "—" : format(value)}
                      {baseline &&
                        before !== undefined &&
                        value !== undefined && (
                          <small
                            className={
                              value > before
                                ? "green"
                                : value < before
                                  ? "negative"
                                  : "muted"
                            }
                          >
                            {" "}
                            ({format(value - before)})
                          </small>
                        )}
                    </dd>
                  </div>
                );
              })}
            </dl>
          </div>
        );
      })}
    </section>
  );
}
