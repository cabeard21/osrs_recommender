import { useEffect, useId, useRef, useState } from "react";
import { sameValue } from "../api/runtime";
import { getTarget, searchTargets } from "../api/targetCatalog";
import type { CombatTarget, Role, TargetSelection } from "../api/contracts";

interface Entry {
  key: string;
  name: string;
  variant: string;
  npc_id: number;
  combat_level: number;
  support_status: string;
  reasons: string[];
}
interface Detail extends Entry {
  catalog_revision: string;
  target: CombatTarget | null;
  wiki_url: string;
}
export function NpcTargetPicker({
  selection,
  target,
  inputs = {},
  onChange,
}: {
  selection?: TargetSelection;
  target?: CombatTarget;
  inputs?: Record<string, string>;
  onChange: (patch: Partial<Role>) => void;
}) {
  const latestChange = useRef(onChange);
  latestChange.current = onChange;
  useEffect(
    () => () => {
      serial.current++;
    },
    [],
  );
  const id = useId(),
    serial = useRef(0);
  const [query, setQuery] = useState(""),
    [offset, setOffset] = useState(0);
  const [items, setItems] = useState<Entry[]>([]),
    [total, setTotal] = useState(0);
  const [detail, setDetail] = useState<Detail | null>(null),
    [editing, setEditing] = useState(false);
  const [error, setError] = useState(""),
    [loading, setLoading] = useState(false),
    [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setItems([]);
    setError("");
    if (!query.trim()) {
      setLoading(false);
      return () => controller.abort();
    }
    setLoading(true);
    const timer = setTimeout(() => {
      searchTargets<Entry>(query.trim(), offset, 20, controller.signal)
        .then((page) => {
          if (active) {
            setItems(page.items);
            setTotal(page.total);
          }
        })
        .catch(() => {
          if (active)
            setError("NPC catalog unavailable. Retry or use a custom target.");
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    }, 200);
    return () => {
      active = false;
      controller.abort();
      clearTimeout(timer);
    };
  }, [query, offset, retry]);
  useEffect(() => {
    serial.current++;
    setDetail(null);
    setEditing(false);
  }, [selection?.key]);
  useEffect(() => {
    if (!selection) return;
    let active = true;
    getTarget<Detail>(selection.key)
      .then((row) => {
        if (active) setDetail(row);
      })
      .catch(() => {
        if (active)
          setError("Cannot load this NPC. Retry or reselect the target.");
      });
    return () => {
      active = false;
    };
  }, [selection?.key, retry]);
  const choose = async (key: string) => {
    const request = ++serial.current;
    setLoading(true);
    setError("");
    try {
      const row = await getTarget<Detail>(key);
      if (request !== serial.current) return;
      setDetail(row);
      setEditing(false);
      latestChange.current({
        combatTarget: row.target ? structuredClone(row.target) : undefined,
        targetSelection: {
          key: row.key,
          catalog_revision: row.catalog_revision,
        },
        targetInputs: {},
      });
      setQuery("");
      setItems([]);
    } catch {
      if (request === serial.current)
        setError("Cannot load this NPC. Retry or choose another target.");
    } finally {
      if (request === serial.current) setLoading(false);
    }
  };
  const base = detail?.target;
  const modified = base && target && !sameValue(base, target);
  return (
    <div className="npc-picker">
      <label htmlFor={id}>Search NPCs</label>
      <input
        id={id}
        type="search"
        value={query}
        maxLength={100}
        placeholder="NPC name, variant, or ID"
        onChange={(event) => {
          serial.current++;
          setQuery(event.target.value);
          setOffset(0);
        }}
      />
      {loading && query && <p role="status">Searching NPCs…</p>}
      {error && (
        <p role="alert">
          {error}{" "}
          <button type="button" onClick={() => setRetry(retry + 1)}>
            Retry
          </button>
        </p>
      )}
      {!loading && query && !items.length && !error && <p>No NPCs found.</p>}
      <ul aria-label="NPC search results">
        {items.map((entry) => (
          <li key={entry.key}>
            <button type="button" onClick={() => void choose(entry.key)}>
              {entry.name} · {entry.variant || "Standard"} · Level{" "}
              {entry.combat_level} · {entry.support_status.replaceAll("_", " ")}
            </button>
          </li>
        ))}
      </ul>
      {!!items.length && (
        <div>
          {offset > 0 && (
            <button
              type="button"
              onClick={() => setOffset(Math.max(0, offset - 20))}
            >
              Previous NPCs
            </button>
          )}
          {offset + items.length < total && (
            <button type="button" onClick={() => setOffset(offset + 20)}>
              More NPCs
            </button>
          )}
        </div>
      )}
      {detail && (
        <div className="raised">
          <strong>
            {detail.name} · {detail.variant || "Standard"}
          </strong>
          <p>
            {detail.support_status.replaceAll("_", " ")}{" "}
            {modified && "· Modified"}
          </p>
          {detail.support_status !== "supported" && (
            <p role="alert">
              {detail.name} cannot be optimized. Choose a supported NPC target.
            </p>
          )}
          {detail.reasons.map((reason) => (
            <p key={reason}>{reason}</p>
          ))}
          <a href={detail.wiki_url} target="_blank" rel="noreferrer">
            NPC source
          </a>
          {selection &&
            detail.catalog_revision !== selection.catalog_revision && (
              <p role="alert">
                NPC catalog changed. Reselect this NPC before optimizing.
              </p>
            )}
          {base && target && (
            <>
              <p>NPC stats</p>
              <dl>
                {Object.entries({
                  Defence: target.defence_level,
                  Magic: target.magic_level,
                  "flat armour": target.flat_armour ?? 0,
                  ...target.bonuses,
                  light: target.ranged_light,
                  standard: target.ranged_standard,
                  heavy: target.ranged_heavy,
                  weakness: target.weakness_element,
                  "weakness percent": target.weakness_percent,
                })
                  .filter(([, value]) => value !== undefined && value !== null)
                  .map(([label, value]) => (
                    <div key={label}>
                      <dt>{label}</dt>
                      <dd>{String(value)}</dd>
                    </div>
                  ))}
              </dl>
              <p>
                Flat armour applies to each accurate melee or ranged hitsplat.
                Negative values increase damage; magic ignores it. Catalog
                armour cannot be overridden.
              </p>
              <button
                type="button"
                aria-expanded={editing}
                onClick={() => setEditing(!editing)}
              >
                Edit stats
              </button>
              <button
                type="button"
                onClick={() => {
                  latestChange.current({
                    combatTarget: structuredClone(base),
                    targetSelection: {
                      key: detail.key,
                      catalog_revision: detail.catalog_revision,
                    },
                    targetInputs: {},
                  });
                  setEditing(false);
                }}
              >
                Reset to NPC stats
              </button>
              {editing && (
                <fieldset>
                  <legend>NPC stat overrides</legend>
                  {[
                    "defence_level",
                    "magic_level",
                    "ranged_light",
                    "ranged_standard",
                    "ranged_heavy",
                    "weakness_percent",
                    ...["stab", "slash", "crush", "ranged", "magic"].map(
                      (key) => `bonuses.${key}`,
                    ),
                  ].map((key) => (
                    <label key={key}>
                      {key.replaceAll("_", " ")}
                      <input
                        type="number"
                        value={
                          inputs[key] ??
                          String(
                            key.startsWith("bonuses.")
                              ? (target.bonuses[key.slice(8)] ?? 0)
                              : (target[key] ?? ""),
                          )
                        }
                        onChange={(event) => {
                          const n =
                            event.target.value === ""
                              ? NaN
                              : Number(event.target.value);
                          latestChange.current({
                            targetInputs: {
                              ...inputs,
                              [key]: event.target.value,
                            },
                            combatTarget: !Number.isFinite(n)
                              ? target
                              : key.startsWith("bonuses.")
                                ? {
                                    ...target,
                                    bonuses: {
                                      ...target.bonuses,
                                      [key.slice(8)]: n,
                                    },
                                  }
                                : { ...target, [key]: n },
                          });
                        }}
                      />
                    </label>
                  ))}
                  <label>
                    Elemental weakness
                    <select
                      value={String(target.weakness_element ?? "")}
                      onChange={(event) =>
                        latestChange.current({
                          combatTarget: {
                            ...target,
                            weakness_element: event.target.value || null,
                          },
                        })
                      }
                    >
                      <option value="">None</option>
                      {["air", "water", "earth", "fire"].map((element) => (
                        <option key={element}>{element}</option>
                      ))}
                    </select>
                  </label>
                </fieldset>
              )}
            </>
          )}
        </div>
      )}
      {selection && (
        <button
          type="button"
          onClick={() => {
            serial.current++;
            setDetail(null);
            latestChange.current({
              targetSelection: undefined,
              combatTarget: {
                name: "Custom ordinary-attack target",
                defence_level: 1,
                magic_level: 1,
                bonuses: {},
              },
              targetInputs: {},
            });
          }}
        >
          Custom target
        </button>
      )}
    </div>
  );
}
