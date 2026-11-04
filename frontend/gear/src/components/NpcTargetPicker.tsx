import { useEffect, useId, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import {
  NPC_OVERRIDE_LABELS,
  npcEntryLabel,
  npcStatLines,
  readRecentNpcs,
  rememberNpc,
  sortNpcEntries,
} from "./npcEntries";
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
  const [recent, setRecent] = useState(readRecentNpcs);
  const searchRef = useRef<HTMLInputElement>(null),
    listRef = useRef<HTMLUListElement>(null);
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
      rememberNpc(row);
      setRecent(readRecentNpcs());
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
  const results = sortNpcEntries(items);
  const recentTargets = recent.filter((row) => row.key !== selection?.key);
  const resultButtons = () =>
    Array.from(
      listRef.current?.querySelectorAll<HTMLButtonElement>("button") ?? [],
    );
  const onSearchKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" && results.length) {
      event.preventDefault();
      resultButtons()[0]?.focus();
    } else if (event.key === "Enter" && results.length) {
      event.preventDefault();
      void choose(results[0].key);
    }
  };
  const onResultKey = (
    event: KeyboardEvent<HTMLButtonElement>,
    index: number,
  ) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const next = index + (event.key === "ArrowDown" ? 1 : -1);
    if (next < 0) searchRef.current?.focus();
    else resultButtons()[Math.min(next, results.length - 1)]?.focus();
  };
  return (
    <div className="npc-picker">
      <label htmlFor={id}>Search NPCs</label>
      <input
        id={id}
        type="search"
        value={query}
        maxLength={100}
        placeholder="NPC name, variant, or ID"
        ref={searchRef}
        onKeyDown={onSearchKey}
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
      {!query.trim() && recentTargets.length > 0 && (
        <div
          className="option-shortcuts"
          role="group"
          aria-label="Recent targets"
        >
          {recentTargets.map((row) => (
            <button
              type="button"
              key={row.key}
              aria-label={`Recent target ${npcEntryLabel(row)}`}
              onClick={() => void choose(row.key)}
            >
              {npcEntryLabel(row)}
            </button>
          ))}
        </div>
      )}
      <ul aria-label="NPC search results" className="npc-results" ref={listRef}>
        {results.map((entry, index) => (
          <li key={entry.key}>
            <button
              type="button"
              onClick={() => void choose(entry.key)}
              onKeyDown={(event) => onResultKey(event, index)}
            >
              {npcEntryLabel(entry)}
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
        <div className="raised npc-detail">
          <div className="npc-detail-head">
            <strong>
              {npcEntryLabel(detail)}
              {modified && " · Modified"}
            </strong>
            <a href={detail.wiki_url} target="_blank" rel="noreferrer">
              NPC source
            </a>
          </div>
          {detail.support_status !== "supported" && (
            <p role="alert">
              {detail.name} cannot be optimized. Choose a supported NPC target.
            </p>
          )}
          {detail.reasons.map((reason) => (
            <p key={reason}>{reason}</p>
          ))}
          {selection &&
            detail.catalog_revision !== selection.catalog_revision && (
              <p role="alert">
                NPC catalog changed. Reselect this NPC before optimizing.
              </p>
            )}
          {base && target && (
            <>
              <div className="npc-stats">
                {npcStatLines(target).map((line) => (
                  <p key={line}>{line}</p>
                ))}
              </div>
              <dl className="npc-flat-armour">
                <div>
                  <dt>Flat armour</dt>
                  <dd>{target.flat_armour ?? 0}</dd>
                </div>
              </dl>
              <p className="npc-note">
                Flat armour applies to each accurate melee or ranged hitsplat.
                Negative values increase damage; magic ignores it. Catalog
                armour cannot be overridden.
              </p>
              <div className="npc-actions">
                <button
                  type="button"
                  aria-expanded={editing}
                  onClick={() => setEditing(!editing)}
                >
                  Edit stats
                </button>
                {(modified || editing) && (
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
                )}
              </div>
              {editing && (
                <fieldset className="npc-overrides">
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
                      {NPC_OVERRIDE_LABELS[key] ?? key.replaceAll("_", " ")}
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
          Clear NPC and use custom stats
        </button>
      )}
    </div>
  );
}
