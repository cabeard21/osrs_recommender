package com.osrstracker.spike;

import net.runelite.api.Item;
import net.runelite.api.ItemContainer;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Container contents captured from {@code ItemContainerChanged} events, with the time each was
 * seen.
 *
 * <p>Two captures showed why this is necessary. {@code client.getItemContainer(93|94|95)}
 * returned null for inventory, equipment and bank on a LOGGED_IN client whose bank had just been
 * closed, and {@code client.getItemContainers()} — the whole hash table — enumerated <b>zero</b>
 * entries. Whatever that lookup reads is not populated from a plugin's vantage point in
 * 1.12.35. The event carries the container and its id directly, so it sidesteps the lookup
 * entirely.
 *
 * <p>It also gives a better §4.5 answer than the bank widget's close edge did: the recorded
 * instant is when the contents were actually observed, not when a window happened to shut.
 */
final class ContainerCache
{
	/** One container as seen at one instant. */
	static final class Observation
	{
		final Item[] items;
		final int size;
		final Instant observedAt;

		Observation(Item[] items, int size, Instant observedAt)
		{
			this.items = items;
			this.size = size;
			this.observedAt = observedAt;
		}
	}

	private final Map<Integer, Observation> byContainerId = new LinkedHashMap<>();

	void record(int containerId, ItemContainer container, Instant at)
	{
		if (container == null)
		{
			return;
		}
		byContainerId.put(containerId, new Observation(container.getItems(), container.size(), at));
	}

	Observation get(int containerId)
	{
		return byContainerId.get(containerId);
	}

	Map<Integer, Observation> all()
	{
		return byContainerId;
	}
}
