import { EquipmentBonuses } from "./EquipmentBonuses";
import { Fragment, useEffect, useState } from "react";
import { emptyEquipment, type Item, type Slot } from "../api/contracts";
import { useGear } from "../state/GearProvider";
import { Dialog } from "./Dialog";
import { ItemSprite } from "./EquipmentGrid";
import { PerformanceSummary } from "./PerformanceSummary";
import { TrialComparison } from "./TrialComparison";
function retainInspectorFocus() {
  document.activeElement
    ?.closest("dialog")
    ?.querySelector<HTMLButtonElement>(
      'button[aria-label="Close Item inspector"]',
    )
    ?.focus();
}
export function ItemInspector() {
  const { liveMode, current, state } = useGear();
  return liveMode ? (
    <LiveItemInspector
      key={`${state.mode}:${current.slot}:${current.activeRole}:${current.solutionId}:${current.result?.fingerprint}`}
    />
  ) : (
    <FixtureItemInspector />
  );
}
function FixtureItemInspector() {
  const {
      state,
      current,
      dispatch,
      edit,
      client,
      itemById,
      previewTrial,
      revertTrial,
      cancelTrial,
    } = useGear(),
    slot = current.slot!;
  const solution = current.result?.solutions.find(
    (s) => s.id === current.solutionId,
  );
  const equipment =
    solution?.loadouts.find((l) => l.roleId === current.activeRole)
      ?.equipment ??
    state.context?.equipment ??
    emptyEquipment();
  const id = equipment[slot];
  const [details, setDetails] = useState<Item | null>(null);
  const item = details?.id === id ? details : itemById(id);
  const [alternatives, setAlternatives] = useState<Item[]>([]),
    [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    setDetails(null);
    setError(null);
    if (id !== null)
      client
        .getItem(
          id,
          current.result?.scenario?.request.support_policy ??
            current.draft.supportPolicy ??
            "community_best_effort",
        )
        .then((item) => {
          if (active) setDetails(item);
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    return () => {
      active = false;
    };
  }, [id, client]);
  useEffect(() => {
    let active = true;
    setAlternatives([]);
    if (current.result)
      client
        .alternatives(slot, current.result.scenario)
        .then((items) => {
          if (active) setAlternatives(items);
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    return () => {
      active = false;
    };
  }, [slot, client, current.result]);
  const close = () =>
    dispatch({ type: "ui", mode: state.mode, patch: { slot: null } });
  function lock(exclude = false) {
    retainInspectorFocus();
    const roles = current.draft.roles.map((r) => {
      if (r.id !== current.activeRole) return r;
      const locks = { ...r.locks };
      if (exclude) delete locks[slot];
      else locks[slot] = id;
      return { ...r, locks };
    });
    edit({
      ...current.draft,
      roles,
      exclusions:
        exclude && id
          ? [...new Set([...current.draft.exclusions, id])]
          : current.draft.exclusions.filter((i) => i !== id),
    });
  }
  const locked = current.draft.roles.some((r) =>
    Object.values(r.locks).includes(id),
  );
  function preview(replacement: number | null) {
    if (!current.result || !solution) return;
    void previewTrial({ ...equipment, [slot]: replacement });
  }
  return (
    <Dialog contextual title="Item inspector" onClose={close}>
      <span className="eyebrow blue">{slot} // contextual inspection</span>
      <div className="inspector-item">
        <ItemSprite id={id} />
        <h3>{item?.name ?? "Empty slot"}</h3>
      </div>
      <p className="notice">
        Fixture item facts · no live ownership or price verification.
      </p>
      <dl>
        <dt>Item ID</dt>
        <dd>{id ?? "None"}</dd>
        <dt>Ownership example</dt>
        <dd>
          {item
            ? item.owned
              ? "Observed owned (fixture)"
              : "Unowned (fixture)"
            : "Empty"}
        </dd>
        <dt>Quote example</dt>
        <dd>
          {item?.price == null
            ? "Unavailable / untradeable"
            : `${item.price.toLocaleString()} GP`}
        </dd>
        <dt>Last observed</dt>
        <dd>{state.context?.observedAt}</dd>
      </dl>
      <p>{item?.requirement ?? "Empty slots can be locked explicitly."}</p>
      <div className="button-row">
        <button onClick={() => lock()}>
          Lock {id === null ? "empty slot" : "item"} in draft
        </button>
        <button
          disabled={
            id === null ||
            (locked &&
              current.draft.roles.some(
                (r) =>
                  r.id !== current.activeRole &&
                  Object.values(r.locks).includes(id),
              ))
          }
          onClick={() => lock(true)}
        >
          {locked ? "Unlock and exclude" : "Exclude item"} in draft
        </button>
      </div>
      <p>
        Fixture draft controls and authored comparisons demonstrate refinement.
        Live requests are fully validated.
      </p>
      <h3>Equipment alternatives</h3>
      {!current.result && (
        <p>Run a fixture optimization to preview alternatives.</p>
      )}
      {alternatives
        .filter((a) => a.id !== id)
        .map((a) => (
          <article className="alternative" key={a.id}>
            <ItemSprite id={a.id} />
            <span>
              {a.name}
              <small>{a.owned ? "Fixture owned" : "Fixture purchase"}</small>
            </span>
            <button
              disabled={
                current.outdated || current.pending || current.trialPending
              }
              onClick={() => void preview(a.id)}
            >
              Preview comparison
            </button>
          </article>
        ))}
      {current.result && (
        <button
          disabled={current.outdated || current.pending || current.trialPending}
          onClick={() => void preview(null)}
        >
          Preview empty slot
        </button>
      )}
      {current.outdated && (
        <p className="notice">
          Result outdated. Re-run before previewing alternatives.
        </p>
      )}
      {current.trialPending && (
        <>
          <p role="status">Loading fixture comparison…</p>
          <button
            onClick={() => {
              retainInspectorFocus();
              cancelTrial();
            }}
          >
            Cancel evaluation
          </button>
        </>
      )}
      {error && <p role="alert">{error}</p>}
      {current.trialError && <p role="alert">{current.trialError}</p>}
      {current.trial?.source === "fixture" && (
        <section className="trial">
          <h3>Manual trial · fixture preview</h3>
          <p>Original result and draft equipment remain unchanged.</p>
          <p>
            Baseline {current.trial.baseline.dps.toFixed(2)} DPS → trial{" "}
            {current.trial.proposed.dps.toFixed(2)} DPS. Authored illustration
            only.
          </p>
          <PerformanceSummary
            metrics={current.trial.proposed}
            title="Trial telemetry"
          />
          <button
            onClick={() => {
              retainInspectorFocus();
              revertTrial();
            }}
          >
            Revert trial
          </button>
        </section>
      )}
    </Dialog>
  );
}

function LiveItemInspector() {
  const {
    state,
    current,
    client,
    dispatch,
    edit,
    run,
    previewTrial,
    revertTrial,
    cancelTrial,
    itemById,
  } = useGear();
  const slot = current.slot!;
  const observation = state.context?.live?.current_equipment.slots[slot];
  const multi = state.mode === "multi";
  const solution = current.result?.solutions.find(
    (row) => row.id === current.solutionId,
  );
  const optimized = solution?.loadouts.find(
    (role) => role.roleId === current.activeRole,
  )?.equipment;
  const [lockScope, setLockScope] = useState<"role" | "global">("role");
  const draftRoleExists = current.draft.roles.some(
    (role) => role.id === current.activeRole,
  );
  const canLock = lockScope === "global" || draftRoleExists;
  const [selected, setSelected] = useState<number | null | undefined>(
    undefined,
  );
  const originalId = optimized?.[slot] ?? null;
  const id = selected !== undefined ? selected : originalId;
  const [item, setItem] = useState<Item | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState<{
    items: Item[];
    total: number;
    nextOffset: number | null;
  }>({ items: [], total: 0, nextOffset: null });
  const [offset, setOffset] = useState(0);
  const [browseError, setBrowseError] = useState("");
  const [isBrowsing, setIsBrowsing] = useState(!!client.browseItems);
  const physicalSlot = slot === "ammo" ? "ammunition" : slot;
  const excluded = new Set(current.draft.exclusions);
  const branch = current.result?.live?.result.discipline_results?.find((row) =>
    current.solutionId.startsWith(`discipline-${row.discipline}-`),
  );
  const contextual =
    (branch?.alternatives ?? current.result?.live?.result.alternatives)?.[
      physicalSlot
    ] ?? [];
  const canPreview =
    !multi && !!optimized && !current.outdated && !current.pending;
  const namedItem = (itemId: number) =>
    itemById(itemId)?.name ?? `Item #${itemId}`;
  const isLocked =
    id !== null &&
    (Object.values(current.draft.globalLocks ?? {}).includes(id) ||
      current.draft.roles.some((role) =>
        Object.values(role.locks).includes(id),
      ));
  function lockItem(itemId: number | null) {
    if (!canLock) return;
    retainInspectorFocus();
    edit({
      ...current.draft,
      ...(lockScope === "global"
        ? {
            globalLocks: { ...current.draft.globalLocks, [slot]: itemId },
          }
        : {}),
      roles: current.draft.roles.map((role) =>
        lockScope === "role" && role.id === current.activeRole
          ? { ...role, locks: { ...role.locks, [slot]: itemId } }
          : role,
      ),
    });
  }
  const scopedLock =
    lockScope === "global"
      ? current.draft.globalLocks?.[slot]
      : current.draft.roles.find((role) => role.id === current.activeRole)
          ?.locks[slot];
  const isSlotLocked = scopedLock !== undefined && scopedLock === id;
  function unlockSlot() {
    retainInspectorFocus();
    const withoutSlot = <T,>(locks: Partial<Record<Slot, T>>) =>
      Object.fromEntries(
        Object.entries(locks).filter(([key]) => key !== slot),
      ) as Partial<Record<Slot, T>>;
    edit({
      ...current.draft,
      ...(lockScope === "global"
        ? { globalLocks: withoutSlot(current.draft.globalLocks ?? {}) }
        : {}),
      roles: current.draft.roles.map((role) =>
        lockScope === "role" && role.id === current.activeRole
          ? { ...role, locks: withoutSlot(role.locks) }
          : role,
      ),
    });
  }
  function excludeItem() {
    if (id === null) return;
    retainInspectorFocus();
    edit({
      ...current.draft,
      globalLocks: Object.fromEntries(
        Object.entries(current.draft.globalLocks ?? {}).filter(
          ([, value]) => value !== id,
        ),
      ),
      roles: current.draft.roles.map((role) => ({
        ...role,
        locks: Object.fromEntries(
          Object.entries(role.locks).filter(([, value]) => value !== id),
        ),
      })),
      exclusions: [...new Set([...current.draft.exclusions, id])],
    });
  }
  function chooseCandidate(candidate: number | null) {
    document.activeElement?.closest("dialog")?.scrollTo?.({ top: 0 });
    setSelected(candidate);
    // previewTrial replaces any current trial itself. Reverting first would
    // advance the trial generation and make the reducer reject this request.
    if (optimized && canPreview)
      void previewTrial({ ...optimized, [slot]: candidate });
    else revertTrial();
  }
  function preview(replacement: number | null) {
    document.activeElement?.closest("dialog")?.scrollTo?.({ top: 0 });
    setSelected(replacement);
    if (optimized && canPreview)
      void previewTrial({ ...optimized, [slot]: replacement });
  }
  useEffect(() => {
    setSelected(undefined);
    setQuery("");
    setOffset(0);
  }, [
    slot,
    current.result?.fingerprint,
    current.solutionId,
    current.activeRole,
  ]);
  useEffect(() => {
    let active = true;
    setItem(null);
    setError("");
    setLoading(id !== null);
    if (id !== null)
      client
        .getItem(
          id,
          current.result?.scenario?.request.support_policy ??
            current.draft.supportPolicy ??
            "community_best_effort",
        )
        .then((value) => {
          if (active) setItem(value);
        })
        .catch((e) => {
          if (active) setError(e.message);
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    return () => {
      active = false;
    };
  }, [
    id,
    client,
    state.context?.snapshotId,
    current.result?.scenario?.request.support_policy,
    current.draft.supportPolicy,
  ]);
  useEffect(() => {
    let active = true;
    setBrowseError("");
    setIsBrowsing(!!client.browseItems);
    const timer = setTimeout(() => {
      client
        .browseItems?.(
          slot,
          query,
          offset,
          current.result?.scenario?.request.support_policy ??
            current.draft.supportPolicy ??
            "community_best_effort",
        )
        .then((value) => {
          if (active) setPage(value);
        })
        .catch((e) => {
          if (!active) return;
          setPage({ items: [], total: 0, nextOffset: null });
          setBrowseError(e.message);
        })
        .finally(() => {
          if (active) setIsBrowsing(false);
        });
    }, 200);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [
    slot,
    query,
    offset,
    client,
    state.context?.snapshotId,
    current.result?.scenario?.request.support_policy,
    current.draft.supportPolicy,
  ]);
  const facts = item?.id === id ? item.facts : undefined;
  const hiddenExclusions = page.items.filter((row) =>
    excluded.has(row.id),
  ).length;
  const hiddenNote = hiddenExclusions
    ? ` · ${hiddenExclusions} excluded item${hiddenExclusions === 1 ? "" : "s"} hidden on this page`
    : "";
  return (
    <Dialog
      contextual
      title="Item inspector"
      onClose={() =>
        dispatch({ type: "ui", mode: state.mode, patch: { slot: null } })
      }
    >
      <span className="eyebrow blue">{slot}</span>
      <p className="notice">
        {selected !== undefined
          ? "Candidate preview · selected configuration is unchanged."
          : optimized
            ? "Showing the optimized result for your submitted settings."
            : `Equipment observation: ${observation?.status ?? "unknown"}`}
      </p>
      {multi && (
        <>
          <label>
            Lock scope
            <select
              value={lockScope}
              onChange={(event) =>
                setLockScope(event.target.value as "role" | "global")
              }
            >
              <option value="role">Selected role</option>
              <option value="global">All roles (global)</option>
            </select>
          </label>
          {!draftRoleExists && (
            <p className="notice">
              This submitted role no longer exists in the draft. Choose global
              scope or configure a current role.
            </p>
          )}
        </>
      )}
      <div className="inspector-item">
        <ItemSprite id={id} />
        <h3>
          {item?.id === id ? item.name : id ? `Item #${id}` : "Unassigned slot"}
        </h3>
      </div>
      {isSlotLocked && (
        <div className="lock-status">
          <p role="status" className="green">
            Locked in draft
          </p>
          <button onClick={unlockSlot}>Unlock {slot}</button>
        </div>
      )}
      {loading && <p role="status">Loading item metadata…</p>}
      {error && <p role="alert">{error}</p>}
      {facts && (
        <div className="button-row">
          <button
            disabled={
              !canLock ||
              isSlotLocked ||
              facts.slot !== physicalSlot ||
              (id !== null && excluded.has(id))
            }
            onClick={() => lockItem(id)}
          >
            Lock {slot} to{" "}
            {id === null ? "empty" : (item?.name ?? namedItem(id))}
          </button>
          <button
            disabled={id === null || excluded.has(id)}
            onClick={excludeItem}
          >
            {isLocked ? "Unlock and exclude" : "Exclude item"} in draft
          </button>
        </div>
      )}
      <section
        className="candidate-comparison"
        aria-label="Candidate comparison"
      >
        {originalId !== id && (
          <p className="eyebrow">
            {solution?.loadouts.find(
              (role) => role.roleId === current.activeRole,
            )?.name ?? "Selected configuration"}{" "}
            · {slot}
          </p>
        )}
        {originalId !== id && (
          <div className="candidate-heading">
            <span>
              <ItemSprite id={originalId} />
              {originalId === null ? "Empty" : namedItem(originalId)}
            </span>
            <span aria-hidden="true">→</span>
            <span>
              <ItemSprite id={id} />
              {id === null ? "Empty" : (item?.name ?? namedItem(id))}
            </span>
          </div>
        )}
        {selected !== undefined && !current.trial && (
          <button
            onClick={() => {
              setSelected(undefined);
              revertTrial();
            }}
          >
            Clear preview
          </button>
        )}
        {facts && selected !== undefined && (multi || !current.trial) && (
          <EquipmentBonuses
            bonuses={facts.equipment.bonuses}
            baseline={itemById(originalId)?.facts?.equipment.bonuses}
            title={multi ? "Item bonuses only" : "Item bonuses"}
          />
        )}
        {facts?.equipment.elemental_spell_bonus && (
          <p aria-label="Elemental amulet bonus">
            +{facts.equipment.elemental_spell_bonus.base_max_hit_bonus} base max
            hit for {facts.equipment.elemental_spell_bonus.elements.join(", ")}{" "}
            spells before damage and weakness bonuses. Air includes wind spells.
          </p>
        )}
        {multi && (
          <p className="notice">
            Item differences only. Lock a candidate and rerun to evaluate the
            joint configuration.
          </p>
        )}
        {current.outdated && (
          <div className="notice">
            <p>Result outdated. Re-run before previewing alternatives.</p>
            <button disabled={current.pending} onClick={() => void run()}>
              Re-run optimization
            </button>
          </div>
        )}
        {current.trialPending && (
          <p role="status">
            Evaluating manual trial…{" "}
            <button
              onClick={() => {
                retainInspectorFocus();
                cancelTrial();
              }}
            >
              Cancel evaluation
            </button>
          </p>
        )}
        {current.trialError && <p role="alert">{current.trialError}</p>}
        {current.trial?.source === "live" && (
          <TrialComparison
            trial={current.trial}
            onRevert={() => {
              retainInspectorFocus();
              setSelected(undefined);
              revertTrial();
            }}
            onLock={() => lockItem(current.trial!.equipment[slot])}
            itemName={(itemId) =>
              current.trial?.source === "live"
                ? (current.trial.live.items.find(
                    (row) => row.item_id === itemId,
                  )?.name ?? namedItem(itemId))
                : namedItem(itemId)
            }
          />
        )}{" "}
      </section>
      {optimized && !multi && (
        <section aria-label="Contextual alternatives">
          <h3>Contextual alternatives</h3>
          <p>
            Validated against the accepted result's surrounding equipment and
            submitted constraints.
          </p>
          {contextual
            .filter((row) => row.item_id !== null && !excluded.has(row.item_id))
            .map((row) => {
              const name =
                row.item_id === null ? "empty slot" : namedItem(row.item_id);
              return (
                <article className="alternative" key={row.item_id ?? "empty"}>
                  <ItemSprite id={row.item_id} />
                  <span>{name}</span>
                  <button onClick={() => chooseCandidate(row.item_id)}>
                    Try {name}
                  </button>
                </article>
              );
            })}
          <button disabled={!canPreview} onClick={() => preview(null)}>
            Preview empty slot
          </button>
        </section>
      )}
      {facts && (
        <>
          {selected === undefined && (multi || !current.trial) && (
            <details className="item-metadata">
              <summary>{multi ? "Item bonuses only" : "Item bonuses"}</summary>
              <EquipmentBonuses
                bonuses={facts.equipment.bonuses}
                title={multi ? "Item bonuses only" : "Item bonuses"}
              />
            </details>
          )}
          <details className="item-metadata">
            <summary>Item facts, requirements and provenance</summary>{" "}
            <dl>
              <dt>Item ID</dt>
              <dd>{facts.item_id}</dd>
              <dt>Equipment slot</dt>
              <dd>{facts.slot}</dd>
              <dt>Ownership</dt>
              <dd>
                {facts.ownership.meaning} ({facts.ownership.status}) · quantity{" "}
                {facts.ownership.quantity}
              </dd>
              <dt>Acquisition</dt>
              <dd>{facts.acquisition}</dd>
              <dt>Selected quote</dt>
              <dd>
                {facts.price.amount_gp === null
                  ? "Price unavailable"
                  : `${facts.price.amount_gp.toLocaleString()} GP`}{" "}
                · {facts.price.layer}
              </dd>
              <dt>Price source / provider</dt>
              <dd>
                {facts.price.source ?? "Unavailable"} /{" "}
                {facts.price.provider ?? "Unavailable"}
              </dd>
              <dt>Selected trade</dt>
              <dd>{facts.price.selected_trade_at ?? "No trade timestamp"}</dd>
              <dt>Fetched</dt>
              <dd>{facts.price.fetched_at ?? "No cached price"}</dd>
              <dt>Confidence / policy</dt>
              <dd>
                {facts.price.confidence ?? "Unavailable"} /{" "}
                {facts.price.policy ?? "Unavailable"}
              </dd>
            </dl>
            <p>{facts.price.selection_reason}</p>
            <h3>Ownership observations</h3>
            <p>
              Previously observed sightings describe the last accepted scans.
              Historical ownership beyond those sightings is unknown.
            </p>
            {facts.ownership.sightings.length === 0 && (
              <p>
                No accepted positive sightings. Latest observations do not
                establish historical ownership.
              </p>
            )}
            {facts.ownership.sightings.map((s) => (
              <p key={s.container}>
                Observed {s.container}: {s.quantity} · {s.observed_at} ·{" "}
                {s.source}
              </p>
            ))}
            {Object.entries(facts.ownership.container_scans).map(
              ([container, scan]) => (
                <p key={container}>
                  {container} last scanned: {scan.scanned_at}
                </p>
              ),
            )}
            <h3>Equipment support</h3>
            <p>
              {facts.support_status === "community_assumed"
                ? "Community-assumed"
                : facts.support_status === "verified"
                  ? "Verified"
                  : "Unreviewed"}
            </p>
            {facts.support_assumptions?.map((assumption) => (
              <p key={assumption}>{assumption}</p>
            ))}
            <h3>Requirements</h3>
            <p>{item?.requirement}</p>
            <pre className="fact-json">
              {JSON.stringify(
                facts.wear.requirements ??
                  facts.equipment.requires ??
                  "No reviewed requirement tree",
                null,
                2,
              )}
            </pre>
            <h3>Equipment statistics</h3>
            <p>
              Attack speed: {facts.equipment.attack_speed} ticks ·{" "}
              {facts.equipment.two_handed
                ? "Two-handed"
                : "One-handed / non-weapon"}
            </p>
            <p>
              Attack styles:{" "}
              {facts.equipment.attack_styles.join(", ") || "None listed"}
            </p>
            <dl>
              {Object.entries(facts.equipment.bonuses).map(([key, value]) => (
                <Fragment key={key}>
                  <dt>{key.replaceAll("_", " ")}</dt>
                  <dd>{value}</dd>
                </Fragment>
              ))}
            </dl>
            {facts.acquisition_descriptions.map((d) => (
              <p key={d}>{d}</p>
            ))}
            <h3>Unsupported effects</h3>
            {facts.effect_status === "generic_unreviewed" && (
              <p>
                Generic unreviewed marker: ordinary-equipment classification is
                missing.
              </p>
            )}
            {facts.effect_status === "unsupported_mechanic" && (
              <p>
                Known unsupported mechanic: ordinary DPS is incomplete for this
                equipment.
              </p>
            )}
            {facts.limitations.length ? (
              facts.limitations.map((l) => <p key={l}>{l}</p>)
            ) : (
              <p>No unsupported effects listed.</p>
            )}
            <p>Catalog: {facts.catalog_version}</p>
          </details>
        </>
      )}
      <h3>Browse physical items</h3>
      <button disabled={!canLock} onClick={() => lockItem(null)}>
        Lock {slot} empty
      </button>
      <label>
        Search name or numeric ID
        <input
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOffset(0);
          }}
        />
      </label>
      {browseError && <p role="alert">{browseError}</p>}
      <p role="status">
        {isBrowsing
          ? "Searching items…"
          : `${page.total} matching items · inspection only${hiddenNote}`}
      </p>
      {page.items
        .filter((row) => !excluded.has(row.id))
        .map((row) => (
          <article className="alternative" key={row.id}>
            <ItemSprite id={row.id} />
            <span>
              {row.name}
              <small>
                #{row.id} · {row.requirement}
              </small>
            </span>
            <button onClick={() => chooseCandidate(row.id)}>
              {multi ? "Inspect" : "Try"} {row.name}
            </button>
          </article>
        ))}
      <div className="button-row">
        <button
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - 20))}
        >
          Previous items
        </button>
        <button
          disabled={page.nextOffset === null}
          onClick={() => setOffset(page.nextOffset!)}
        >
          Next items
        </button>
      </div>
    </Dialog>
  );
}
