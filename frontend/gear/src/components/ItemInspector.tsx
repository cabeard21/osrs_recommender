import { Fragment, useEffect, useState } from "react";
import { emptyEquipment, type Item } from "../api/contracts";
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
        .getItem(id)
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
        <dt>Concrete ID</dt>
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
        Live requests use authoritative Python validation.
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
  const [selected, setSelected] = useState<number | null>(null);
  const id =
    selected ?? (optimized ? optimized[slot] : observation?.item_id) ?? null;
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
  const physicalSlot = slot === "ammo" ? "ammunition" : slot;
  const excluded = new Set(current.draft.exclusions);
  const contextual =
    current.result?.live?.result.alternatives?.[physicalSlot] ?? [];
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
  function preview(replacement: number | null) {
    if (optimized && canPreview)
      void previewTrial({ ...optimized, [slot]: replacement });
  }
  useEffect(() => {
    setSelected(null);
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
        .getItem(id)
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
  }, [id, client, state.context?.snapshotId]);
  useEffect(() => {
    let active = true;
    setPage({ items: [], total: 0, nextOffset: null });
    setBrowseError("");
    const timer = setTimeout(() => {
      client
        .browseItems?.(slot, query, offset)
        .then((value) => {
          if (active) setPage(value);
        })
        .catch((e) => {
          if (active) setBrowseError(e.message);
        });
    }, 200);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [slot, query, offset, client, state.context?.snapshotId]);
  const facts = item?.id === id ? item.facts : undefined;
  return (
    <Dialog
      contextual
      title="Item inspector"
      onClose={() =>
        dispatch({ type: "ui", mode: state.mode, patch: { slot: null } })
      }
    >
      <span className="eyebrow blue">
        {slot} // authoritative physical catalog
      </span>
      <p className="notice">
        {selected !== null
          ? "Catalog inspection · observed equipment is unchanged."
          : optimized
            ? "Selected Python optimization result · submitted scenario retained."
            : `Equipment observation: ${observation?.status ?? "unknown"}`}
      </p>
      {multi && (
        <>
          <p className="notice">
            Exact multi-role manual evaluation is unavailable. Inspect facts or
            edit draft constraints and rerun the joint optimizer; single-role
            alternatives do not measure joint contributions.
          </p>
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
      {(state.context?.live?.current_equipment.unmapped_item_ids.length ?? 0) >
        0 && (
        <div>
          <p>Equipped IDs with missing metadata (slot unknown):</p>
          {state.context?.live?.current_equipment.unmapped_item_ids.map(
            (unknownId) => (
              <button key={unknownId} onClick={() => setSelected(unknownId)}>
                Inspect unmapped #{unknownId}
              </button>
            ),
          )}
        </div>
      )}
      {id === null && (
        <p>
          {optimized
            ? "Selected result leaves this slot empty."
            : observation?.status === "empty"
              ? "No item observed in this slot at the equipment scan."
              : "Equipment information is incomplete. No item identity can be assigned to this slot."}
        </p>
      )}
      {observation?.status === "ambiguous" && (
        <div>
          <p>
            Conflicting observations. Inspect a candidate without assigning it:
          </p>
          {observation.candidate_item_ids.map((candidate) => (
            <button key={candidate} onClick={() => setSelected(candidate)}>
              Inspect #{candidate}
            </button>
          ))}
        </div>
      )}
      <div className="inspector-item">
        <ItemSprite id={id} />
        <h3>
          {item?.id === id ? item.name : id ? `Item #${id}` : "Unassigned slot"}
        </h3>
      </div>
      {loading && <p role="status">Loading item metadata…</p>}
      {error && <p role="alert">{error}</p>}
      {facts && (
        <>
          <div className="button-row">
            <button
              disabled={
                !canLock ||
                facts.slot !== physicalSlot ||
                (id !== null && excluded.has(id))
              }
              onClick={() => lockItem(id)}
            >
              Lock {slot} to #{id}
            </button>
            <button
              disabled={id === null || excluded.has(id)}
              onClick={excludeItem}
            >
              {isLocked ? "Unlock and exclude" : "Exclude item"} in draft
            </button>
            {optimized && !multi && (
              <button
                disabled={
                  !canPreview ||
                  facts.slot !== physicalSlot ||
                  (id !== null && excluded.has(id))
                }
                onClick={() => preview(id)}
              >
                Preview selected alternative
              </button>
            )}
          </div>
          <dl>
            <dt>Concrete ID</dt>
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
          {facts.limitations.length ? (
            facts.limitations.map((l) => <p key={l}>{l}</p>)
          ) : (
            <p>No unsupported effects listed.</p>
          )}
          <p>Catalog: {facts.catalog_version}</p>
        </>
      )}
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
                  {row.item_id !== null && (
                    <button
                      aria-label={`Inspect ${name}`}
                      onClick={() => setSelected(row.item_id)}
                    >
                      Inspect
                    </button>
                  )}
                  <button
                    disabled={!canPreview}
                    onClick={() => preview(row.item_id)}
                  >
                    Preview {name}
                  </button>
                </article>
              );
            })}
          <button disabled={!canPreview} onClick={() => preview(null)}>
            Preview empty slot
          </button>
          {current.outdated && (
            <p className="notice">
              Result outdated. Re-run before previewing alternatives.
            </p>
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
          )}
        </section>
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
      <p>{page.total} matching items · inspection only</p>
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
            <button
              aria-label={`Inspect ${row.name}`}
              onClick={() => setSelected(row.id)}
            >
              Inspect
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
