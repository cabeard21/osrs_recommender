import { useEffect, useRef, useState } from "react";
import type { CombatOption } from "../api/contracts";

interface Point {
  ammo_id: number;
  cape_id: number | null;
  ammo_name: string;
  cape_name: string;
  dps: number | null;
  recovery_rate: number | null;
  arrows_lost_per_hour: number | null;
  gp_per_hour: number | null;
  gp_per_damage: number | null;
  frontier: boolean;
  current: boolean;
  reasons: (string | { message: string })[];
  price: Record<string, unknown> | null;
}
interface Identity {
  snapshot_id: string;
  catalog_version: string;
  price_revision: string;
  model_version?: string;
  assumptions_fingerprint?: string;
  scenario_fingerprint?: string;
}
const label = (p: Point) => `${p.ammo_name} / ${p.cape_name}`;
const number = (n: number | null, digits = 2) =>
  n === null
    ? "Unknown"
    : n.toLocaleString(undefined, { maximumFractionDigits: digits });
const colors = ["#c3a16d", "#59b8c9", "#bd94e0", "#8cc477"];

export function AmmoComparison({
  scenario,
  loadout,
  combatOption,
  identity,
  outdated = false,
}: {
  scenario: Record<string, unknown>;
  loadout: Record<string, number>;
  combatOption?: CombatOption;
  identity: Identity;
  outdated?: boolean;
}) {
  const key = JSON.stringify({
    scenario,
    loadout,
    combatOption,
    identity,
    outdated,
  });
  const [result, setResult] = useState<{
    key: string;
    points: Point[];
    limitations: string[];
  } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => {
    setResult(null);
    setError("");
    setBusy(false);
    setSelected(null);
    return () => controller.current?.abort();
  }, [key]);
  async function compare() {
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/ui-api/gear/ammo-comparisons", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        signal: request.signal,
        body: JSON.stringify({
          scenario,
          loadout,
          combat_option:
            combatOption?.attack_type === "ranged"
              ? { ...combatOption, attack_type: "standard" }
              : combatOption,
        }),
      });
      const body = await response.json();
      if (!response.ok)
        throw new Error(body.error?.message ?? "Arrow comparison failed");
      if (
        Object.entries(identity).some(([field, value]) => body[field] !== value)
      )
        throw new Error(
          "Comparison sources changed. Re-run optimization before comparing arrows.",
        );
      if (!Array.isArray(body.points))
        throw new Error("Invalid arrow comparison response");
      if (!request.signal.aborted)
        setResult({
          key,
          points: body.points,
          limitations: body.limitations ?? [],
        });
    } catch (e) {
      if (!request.signal.aborted)
        setError(e instanceof Error ? e.message : "Arrow comparison failed");
    } finally {
      if (!request.signal.aborted) setBusy(false);
    }
  }
  const points = !outdated && result?.key === key ? result.points : [];
  const plotted = points.filter(
    (p) => p.dps !== null && p.gp_per_hour !== null,
  );
  const maxCost = Math.max(1, ...plotted.map((p) => p.gp_per_hour!));
  const actualMaxDps = Math.max(0, ...points.map((p) => p.dps ?? 0));
  const maxDps = Math.max(1, actualMaxDps);
  const capes = [...new Set(points.map((p) => p.cape_id))];
  const frontier = plotted.filter((p) => p.frontier);
  const cheapest = Math.min(...frontier.map((p) => p.gp_per_hour!));
  const fastest = Math.max(...frontier.map((p) => p.dps!));
  return (
    <section className="panel" aria-label="Arrow running cost">
      <h2>Arrow running cost</h2>
      <p>
        Continuous combat; no ground pickup; arrow cost only. Gear purchases
        remain separate.
      </p>
      <button type="button" onClick={compare} disabled={busy || outdated}>
        {busy ? "Comparing arrows…" : "Compare arrows"}
      </button>
      {outdated && <p>Re-run optimization to compare this setup.</p>}
      {error && <p role="alert">{error}</p>}
      {!outdated &&
        result?.key === key &&
        result.limitations.map((message) => <p key={message}>{message}</p>)}
      {points.length > 0 && (
        <>
          <p role="status">
            {selected === null
              ? "Select a combination to preview."
              : `Preview: ${label(points[selected])}`}
          </p>
          {plotted.length > 0 && (
            <svg
              viewBox="0 0 600 240"
              role="group"
              aria-label="DPS versus ammunition GP per hour"
              style={{ width: "100%" }}
            >
              <path d="M55 15V200H580" fill="none" stroke="currentColor" />
              <text x="300" y="235" fill="currentColor" textAnchor="middle">
                Ammunition GP/hour →
              </text>
              <text x="5" y="16" fill="currentColor">
                DPS
              </text>
              <text x="55" y="218" fill="currentColor">
                0
              </text>
              <text x="580" y="218" textAnchor="end" fill="currentColor">
                {number(maxCost, 0)}
              </text>
              <text x="45" y="30" textAnchor="end" fill="currentColor">
                {number(maxDps)}
              </text>
              {plotted.map((p) => (
                <circle
                  key={`${p.ammo_id}-${p.cape_id}`}
                  role="button"
                  tabIndex={0}
                  aria-label={`Plot ${label(p)}`}
                  onClick={() => setSelected(points.indexOf(p))}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setSelected(points.indexOf(p));
                    }
                  }}
                  cx={55 + (515 * p.gp_per_hour!) / maxCost}
                  cy={195 - (165 * p.dps!) / maxDps}
                  r={p.current ? 7 : 5}
                  fill={colors[capes.indexOf(p.cape_id) % colors.length]}
                  stroke={
                    selected === points.indexOf(p)
                      ? "white"
                      : p.frontier
                        ? "currentColor"
                        : "none"
                  }
                  strokeWidth="2"
                >
                  <title>
                    {label(p)}: {number(p.dps)} DPS, {number(p.gp_per_hour)}{" "}
                    GP/hour{p.current ? "; current setup" : ""}
                  </title>
                </circle>
              ))}
            </svg>
          )}
          <p>
            {capes.map((id) => (
              <span
                key={id ?? "none"}
                style={{
                  color: colors[capes.indexOf(id) % colors.length],
                  marginRight: 12,
                }}
              >
                {points.find((p) => p.cape_id === id)?.cape_name}
              </span>
            ))}
          </p>
          <div style={{ overflowX: "auto" }}>
            <table aria-label="Arrow running cost comparison">
              <thead>
                <tr>
                  {[
                    "Arrow / backpack",
                    "DPS",
                    "DPS loss",
                    "Recovery",
                    "Arrows lost/hour",
                    "GP/hour",
                    "GP/damage",
                    "Details",
                  ].map((h) => (
                    <th key={h}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {points.map((p, i) => (
                  <tr
                    key={`${p.ammo_id}-${p.cape_id}`}
                    aria-selected={selected === i}
                    style={{
                      background: selected === i ? "#253040" : undefined,
                    }}
                  >
                    <th scope="row">
                      <button
                        type="button"
                        aria-label={`Preview ${label(p)}`}
                        onClick={() => setSelected(i)}
                      >
                        {label(p)}
                      </button>
                      {p.current && <span> · Current setup</span>}
                    </th>
                    <td>{number(p.dps)}</td>
                    <td>
                      {p.dps === null
                        ? "Unknown"
                        : `${number(actualMaxDps === 0 ? 0 : 100 * (1 - p.dps / actualMaxDps))}%`}
                    </td>
                    <td>
                      {p.recovery_rate === null
                        ? "Unknown"
                        : `${number(p.recovery_rate * 100)}%`}
                    </td>
                    <td>{number(p.arrows_lost_per_hour)}</td>
                    <td>{number(p.gp_per_hour)}</td>
                    <td>{number(p.gp_per_damage)}</td>
                    <td>
                      {p.frontier && "Frontier · "}
                      {p.frontier &&
                        p.gp_per_hour === cheapest &&
                        "Cheapest · "}
                      {p.frontier && p.dps === fastest && "Highest DPS · "}
                      {p.reasons
                        .map((r) => (typeof r === "string" ? r : r.message))
                        .join(" ")}
                      {p.price && (
                        <small>
                          Unit price:{" "}
                          {typeof p.price.amount_gp === "number"
                            ? `${number(p.price.amount_gp)} GP`
                            : "Unknown"}
                          {p.price.layer ? ` · ${String(p.price.layer)}` : ""}
                          {p.price.confidence
                            ? ` · ${String(p.price.confidence)} confidence`
                            : ""}
                          {p.price.selected_trade_at
                            ? ` · Trade: ${String(p.price.selected_trade_at)}`
                            : ""}
                        </small>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
