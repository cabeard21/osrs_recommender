import { EquipmentBonuses } from "./EquipmentBonuses";
import type { Trial, WildernessPolicy } from "../api/contracts";
import { PurchaseListCopy } from "./PurchaseListCopy";
import { PurchaseRows } from "./PurchaseRows";
import { UntradeablesToObtain } from "./UntradeablesToObtain";
import { WildernessRiskDetails, riskAmount } from "./WildernessRiskDetails";

type LiveTrial = Extract<Trial, { source: "live" }>;
const number = (value: number, digits = 2) => value.toFixed(digits);
const signed = (value: number, digits = 2) =>
  `${value > 0 ? "+" : ""}${number(value, digits)}`;
const gp = (value: number) => `${value.toLocaleString()} GP`;

export function TrialComparison({
  trial,
  onRevert,
  onLock,
  itemName,
  wilderness,
}: {
  trial: LiveTrial;
  onRevert: () => void;
  onLock: () => void;
  itemName: (id: number) => string;
  wilderness?: WildernessPolicy;
}) {
  const { baseline, proposed, deltas } = trial.live;
  const first = baseline.performance;
  const second = proposed.performance;
  const valid =
    baseline.status === "valid" &&
    proposed.status === "valid" &&
    first &&
    second &&
    deltas;
  const name = (id: number | null) => (id === null ? "Empty" : itemName(id));
  const rows = valid
    ? [
        ["DPS", number(first.dps!), number(second.dps!), signed(deltas.dps)],
        [
          "Max hit",
          number(first.max_hit!, 0),
          number(second.max_hit!, 0),
          signed(deltas.max_hit, 0),
        ],
        [
          "Accuracy",
          `${number(first.accuracy! * 100, 1)}%`,
          `${number(second.accuracy! * 100, 1)}%`,
          `${signed(deltas.accuracy * 100, 1)} pp`,
        ],
        [
          "Attack interval",
          `${number(first.attack_interval!, 1)} s`,
          `${number(second.attack_interval!, 1)} s`,
          `${signed(deltas.attack_interval, 1)} s`,
        ],
        [
          "Additional GP required",
          gp(baseline.purchase_cost_gp!),
          gp(proposed.purchase_cost_gp!),
          `${deltas.purchase_cost_gp > 0 ? "+" : ""}${gp(deltas.purchase_cost_gp)}`,
        ],
        ...(baseline.wilderness_risk && proposed.wilderness_risk
          ? [
              [
                "Wilderness gear loss",
                riskAmount(baseline.wilderness_risk.loss_gp),
                riskAmount(proposed.wilderness_risk.loss_gp),
                baseline.wilderness_risk.loss_gp !== null &&
                proposed.wilderness_risk.loss_gp !== null
                  ? gp(
                      proposed.wilderness_risk.loss_gp -
                        baseline.wilderness_risk.loss_gp,
                    )
                  : "Unavailable",
              ],
            ]
          : []),
      ]
    : [];
  return (
    <section className="trial" aria-label="Manual trial">
      <h3>Manual trial</h3>
      <p>Original recommendation and draft equipment remain unchanged.</p>
      {valid ? (
        <>
          <table
            aria-label="Manual trial comparison"
            style={{
              width: "100%",
              tableLayout: "fixed",
              fontSize: 12,
              overflowWrap: "anywhere",
            }}
          >
            <thead>
              <tr>
                <th>Metric</th>
                <th>Selected configuration</th>
                <th>With candidate</th>
                <th>Change</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(([label, a, b, delta]) => (
                <tr key={label}>
                  <th scope="row">{label}</th>
                  <td>{a}</td>
                  <td>{b}</td>
                  <td
                    className={
                      Number.parseFloat(delta) === 0
                        ? "muted"
                        : Number.parseFloat(delta) > 0 ===
                            (label !== "Attack interval" &&
                              label !== "Additional GP required")
                          ? "green"
                          : "negative"
                    }
                  >
                    {delta}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <EquipmentBonuses
            bonuses={second.bonuses}
            baseline={first.bonuses}
            title="Configuration bonus changes"
            changedOnly
          />
          <h4>Equipment changes</h4>
          {deltas.equipment_changes.length === 0 && (
            <p>No equipment changes.</p>
          )}
          {deltas.equipment_changes.map((change) => (
            <p key={change.slot}>
              {change.slot}: {name(change.baseline_item_id)} →{" "}
              {name(change.proposed_item_id)}
            </p>
          ))}
        </>
      ) : (
        <p className="notice">
          Trial performance unavailable. Resolve the configuration constraints
          or unsupported equipment below.
        </p>
      )}
      {(
        [
          ["Original", baseline],
          ["Trial", proposed],
        ] as const
      ).map(([label, evaluation]) =>
        evaluation.reasons.map((reason, index) => (
          <p className="notice" key={`${label}-${index}`}>
            {label}: {reason.message}
          </p>
        )),
      )}
      {proposed.preparations?.map((p) => (
        <p className="notice" key={p.usable_item_id}>
          {p.message}
        </p>
      ))}
      {wilderness && proposed.wilderness_risk && (
        <>
          <h4>Trial Wilderness risk</h4>
          <WildernessRiskDetails
            risk={proposed.wilderness_risk}
            policy={wilderness}
            itemName={itemName}
          />
        </>
      )}
      <h4>Trial acquisition requirements</h4>
      <p>
        {proposed.purchase_cost_gp === null
          ? "Total acquisition cost unavailable."
          : `${gp(proposed.purchase_cost_gp)} additional purchases`}
      </p>
      <PurchaseRows purchases={proposed.purchases} itemName={itemName} />
      <UntradeablesToObtain
        ids={proposed.unowned_untradeable_item_ids}
        itemName={itemName}
      />
      {proposed.assumed_item_ids.length > 0 && (
        <p className="notice">
          Hypothetically acquired IDs: {proposed.assumed_item_ids.join(", ")}.
          Ownership is unchanged.
        </p>
      )}
      <PurchaseListCopy
        key={JSON.stringify(proposed.purchases)}
        purchases={proposed.purchases}
        itemName={itemName}
      />
      <div className="button-row">
        <button onClick={onRevert}>Clear preview</button>
        <button disabled={!valid} onClick={onLock}>
          Lock trial alternative in draft
        </button>
      </div>
      <details className="fact-json">
        <summary>Trial evaluation provenance</summary>
        <p>Account: {trial.live.snapshot_id}</p>
        <p>Catalog: {trial.live.catalog_version}</p>
        <p>Model: {trial.live.model_version}</p>
        <p>Prices: {trial.live.price_revision}</p>
        <p>Scenario: {trial.live.scenario_fingerprint}</p>
        <p>Evaluated: {trial.live.evaluated_at}</p>
      </details>
    </section>
  );
}
