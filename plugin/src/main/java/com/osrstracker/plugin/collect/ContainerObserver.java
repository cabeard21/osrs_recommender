package com.osrstracker.plugin.collect;

import com.osrstracker.plugin.AccountSnapshot;
import net.runelite.api.Item;
import net.runelite.api.ItemContainer;
import net.runelite.api.gameval.InventoryID;

import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Observed items and the container scans that make them mean something (§6.5, §7.1).
 *
 * <p>This class is where docs/CONTRACT_RECONCILIATION.md's fourth ruling lives, so the mechanics
 * are worth restating: {@code client.getItemContainer(93|94|95)} returns null and
 * {@code getItemContainers()} enumerates zero entries in 1.12.35. The only working source is the
 * {@code ItemContainerChanged} event, and it fires <b>on change</b>.
 *
 * <p>That gives §6.5 its three cases honestly:
 *
 * <table>
 *   <tr><td>An event fired</td><td>scan emitted at the event's time; items are whatever it
 *   carried, empty included</td></tr>
 *   <tr><td>The bank interface was closed</td><td>scan emitted — the player saw the whole bank,
 *   which is what makes an empty bank distinguishable from an unopened one</td></tr>
 *   <tr><td>Neither</td><td><b>no scan</b>, so the app reads {@code unknown}</td></tr>
 * </table>
 *
 * <p>The third row is the one worth defending. Emitting a scan the client never witnessed turns
 * "we have never looked" into "you own nothing", which is D8's bug one layer out and silently
 * disables the whole unknown-state design. A missing scan costs a prompt; a fabricated one
 * costs correctness.
 */
public final class ContainerObserver
{
	/** §6.5's three containers, mapped to their contract names. */
	private static final Map<Integer, String> TRACKED = new LinkedHashMap<Integer, String>()
	{
		{
			put(InventoryID.INV, "inventory");
			put(InventoryID.WORN, "equipment");
			put(InventoryID.BANK, "bank");
		}
	};

	/** One container as some event saw it. */
	private static final class Observation
	{
		private final Map<Integer, Integer> totals;
		private final Instant observedAt;

		private Observation(Map<Integer, Integer> totals, Instant observedAt)
		{
			this.totals = totals;
			this.observedAt = observedAt;
		}
	}

	private final Map<Integer, Observation> observations = new LinkedHashMap<>();

	/** When the bank interface was last closed — evidence the whole bank was on screen. */
	private Instant bankClosedAt;

	/** Called from {@code ItemContainerChanged}. Ignores containers the contract has no name for. */
	public void onContainerChanged(int containerId, ItemContainer container, Instant at)
	{
		if (container == null || !TRACKED.containsKey(containerId))
		{
			return;
		}
		observations.put(containerId, new Observation(aggregate(container.getItems()), at));
	}

	/** Called when the bank interface closes. */
	public void onBankClosed(Instant at)
	{
		bankClosedAt = at;
	}

	/** Login resets the session's evidence — a new account has not been looked at yet. */
	public void reset()
	{
		observations.clear();
		bankClosedAt = null;
	}

	public List<AccountSnapshot.ObservedItem> items()
	{
		final List<AccountSnapshot.ObservedItem> items = new ArrayList<>();
		for (Map.Entry<Integer, String> tracked : TRACKED.entrySet())
		{
			final Observation observation = observations.get(tracked.getKey());
			if (observation == null)
			{
				continue;
			}
			for (Map.Entry<Integer, Integer> total : observation.totals.entrySet())
			{
				items.add(new AccountSnapshot.ObservedItem(
					total.getKey(), total.getValue(), tracked.getValue()));
			}
		}
		return items;
	}

	public List<AccountSnapshot.ContainerScan> scans()
	{
		final List<AccountSnapshot.ContainerScan> scans = new ArrayList<>();
		for (Map.Entry<Integer, String> tracked : TRACKED.entrySet())
		{
			final Instant scannedAt = scannedAt(tracked.getKey());
			if (scannedAt == null)
			{
				continue;
			}
			// §4.5: when the container was seen, never when the payload was assembled.
			scans.add(new AccountSnapshot.ContainerScan(tracked.getValue(), scannedAt));
		}
		return scans;
	}

	/** @return null when this container has never been witnessed this session. */
	private Instant scannedAt(int containerId)
	{
		final Observation observation = observations.get(containerId);
		if (containerId != InventoryID.BANK)
		{
			return observation == null ? null : observation.observedAt;
		}

		// The bank's own rule (plan step 12b task 2): a close edge is a sighting of the whole
		// bank even when no change event followed, which is exactly the empty-bank case.
		if (observation == null)
		{
			return bankClosedAt;
		}
		if (bankClosedAt == null)
		{
			return observation.observedAt;
		}
		return bankClosedAt.isAfter(observation.observedAt) ? bankClosedAt : observation.observedAt;
	}

	/** Sums duplicate stacks and drops the empty slots the schema's {@code minimum: 1} rejects. */
	private static Map<Integer, Integer> aggregate(Item[] items)
	{
		final Map<Integer, Integer> totals = new LinkedHashMap<>();
		for (Item item : items)
		{
			if (item.getId() <= 0 || item.getQuantity() <= 0)
			{
				continue;
			}
			totals.merge(item.getId(), item.getQuantity(), Integer::sum);
		}
		return totals;
	}
}
