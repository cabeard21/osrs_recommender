import type { CrystalHalberdCharging } from "../api/contracts";

const defaults: CrystalHalberdCharging = {
  method: "auto",
  coin_recharge_cost_gp: 750000,
  shard_value_gp: null,
};

export function CrystalHalberdFields({
  policy,
  onChange,
}: {
  policy?: CrystalHalberdCharging;
  onChange: (policy: CrystalHalberdCharging) => void;
}) {
  const value = policy ?? defaults;
  return (
    <details className="control-help">
      <summary>Crystal halberd charging</summary>
      <label>
        Recharge method
        <select
          value={value.method}
          onChange={(event) =>
            onChange({
              ...value,
              method: event.target.value as CrystalHalberdCharging["method"],
            })
          }
        >
          <option value="auto">Cheapest eligible valued route</option>
          <option value="coins">Coins</option>
          <option value="shards">Crystal shards</option>
        </select>
      </label>
      <label>
        Coin cost per 2,500 charges
        <select
          value={value.coin_recharge_cost_gp}
          onChange={(event) =>
            onChange({
              ...value,
              coin_recharge_cost_gp: Number(
                event.target.value,
              ) as CrystalHalberdCharging["coin_recharge_cost_gp"],
            })
          }
        >
          {[750000, 600000, 450000, 300000, 150000].map((cost) => (
            <option value={cost} key={cost}>
              {cost.toLocaleString()} GP
            </option>
          ))}
        </select>
      </label>
      <label>
        Crystal shard value (GP per shard)
        <input
          type="number"
          min="0"
          step="any"
          placeholder="Unknown"
          value={value.shard_value_gp ?? ""}
          onChange={(event) =>
            onChange({
              ...value,
              shard_value_gp: event.target.value.trim()
                ? Number(event.target.value)
                : null,
            })
          }
        />
      </label>
      <p>
        Unknown recharge history uses the first coin tier. Shards need an
        explicit valuation. Remaining charges are unknown.
      </p>
    </details>
  );
}
