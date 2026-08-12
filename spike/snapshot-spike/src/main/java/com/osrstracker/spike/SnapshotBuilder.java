package com.osrstracker.spike;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import net.runelite.api.Client;
import net.runelite.api.HashTable;
import net.runelite.api.Item;
import net.runelite.api.ItemContainer;
import net.runelite.api.Player;
import net.runelite.api.Quest;
import net.runelite.api.QuestState;
import net.runelite.api.Skill;
import net.runelite.api.VarPlayer;
import net.runelite.api.Varbits;
import net.runelite.api.gameval.InventoryID;

import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.time.Instant;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;

/**
 * Builds one snapshot document. Two halves, deliberately:
 *
 * <ul>
 *   <li>the schema half — a best-effort attempt at {@code contracts/sync_payload.schema.json},
 *       so the Python side can simply validate it;</li>
 *   <li>{@code raw} — everything the schema half had to guess at or throw away. This is what
 *       {@code docs/CONTRACT_RECONCILIATION.md} gets written from: quest identity, the
 *       varbit-to-unlock-key mapping, diary/CA shape, and whether a <em>complete</em> bank scan
 *       is detectable at all (plan step 8.5 task 3).</li>
 * </ul>
 *
 * Must run on the client thread — {@link Quest#getState(Client)} and every varbit read do.
 */
final class SnapshotBuilder
{
	/** The provisional contract's only version (§12.2). */
	private static final int PAYLOAD_VERSION = 1;

	private SnapshotBuilder()
	{
	}

	static JsonObject build(Client client, BankWatch bankWatch, ContainerCache containers)
	{
		final Instant now = Instant.now();
		final JsonObject root = new JsonObject();
		final JsonObject raw = new JsonObject();

		root.addProperty("payload_version", PAYLOAD_VERSION);
		root.addProperty("observed_at", rfc3339(now));

		final Player local = client.getLocalPlayer();
		final JsonObject player = new JsonObject();
		player.addProperty("username", local == null ? null : local.getName());
		player.addProperty("display_name", local == null ? null : local.getName());
		player.addProperty("combat_level", local == null ? null : local.getCombatLevel());
		player.addProperty("quest_points", client.getVarpValue(VarPlayer.QUEST_POINTS));
		root.add("player", player);

		root.add("skills", skills(client));
		root.add("quests", quests(client, raw));
		root.add("unlocks", unlocks(client, raw));

		final JsonArray observedItems = new JsonArray();
		final JsonArray containerScans = new JsonArray();
		collectContainer(client, containers, InventoryID.INV, "inventory", observedItems, containerScans, raw);
		collectContainer(client, containers, InventoryID.WORN, "equipment", observedItems, containerScans, raw);
		collectContainer(client, containers, InventoryID.BANK, "bank", observedItems, containerScans, raw);
		root.add("observed_items", observedItems);
		root.add("container_scans", containerScans);
		raw.add("item_containers_present", presentContainers(client));
		raw.add("bank_widget_edges", bankWidgetEdges(bankWatch));
		raw.add("container_events", containerEvents(containers));

		// No practice_events: the spike does no detection (plan step 8.5 task 1). Step 12c owns it.

		raw.addProperty("client_game_state", client.getGameState().toString());
		root.add("raw", raw);
		return root;
	}

	private static JsonArray skills(Client client)
	{
		final JsonArray out = new JsonArray();
		for (Skill skill : Skill.values())
		{
			final JsonObject entry = new JsonObject();
			entry.addProperty("skill", skill.name().toLowerCase(Locale.ROOT));
			entry.addProperty("level", client.getRealSkillLevel(skill));
			// G5: the client reports 0 for an untrained skill, never -1, so nothing normalizes
			// to null here. Whether "0 xp" should transmit as 0 or be omitted is a
			// reconciliation question, not something to decide silently — see the README.
			entry.addProperty("xp", client.getSkillExperience(skill));
			out.add(entry);
		}
		return out;
	}

	/**
	 * Quest identity is the first thing step 8.5 exists to settle. The schema wants a
	 * {@code content_key}; RuneLite has an enum with a display name and a numeric id. This emits
	 * a slug of the enum constant and records all three forms in {@code raw} so the choice is
	 * made from evidence.
	 */
	private static JsonArray quests(Client client, JsonObject raw)
	{
		final JsonArray out = new JsonArray();
		final JsonArray rawQuests = new JsonArray();
		for (Quest quest : Quest.values())
		{
			final QuestState state = quest.getState(client);

			final JsonObject entry = new JsonObject();
			entry.addProperty("quest_id", slug(quest.name()));
			entry.addProperty("status", questStatus(state));
			out.add(entry);

			final JsonObject rawEntry = new JsonObject();
			rawEntry.addProperty("enum", quest.name());
			rawEntry.addProperty("id", quest.getId());
			rawEntry.addProperty("display_name", quest.getName());
			rawEntry.addProperty("state", state == null ? null : state.name());
			rawQuests.add(rawEntry);
		}
		raw.add("quests", rawQuests);
		return out;
	}

	/** §6.4/A5: {@code in_progress} is not a positive state. Absent state is transmissible. */
	private static String questStatus(QuestState state)
	{
		if (state == null)
		{
			return "unknown";
		}
		switch (state)
		{
			case FINISHED:
				return "complete";
			case IN_PROGRESS:
				return "in_progress";
			case NOT_STARTED:
				return "not_started";
			default:
				return "unknown";
		}
	}

	/**
	 * A12: spellbook, diaries and combat achievements ride as {@code unlock} rows under reserved
	 * prefixes. The diary and CA varbits are read reflectively off {@link Varbits} rather than
	 * hand-listed — a spike should report what the API actually exposes, not what its author
	 * remembered.
	 */
	private static JsonArray unlocks(Client client, JsonObject raw)
	{
		final JsonArray out = new JsonArray();
		final JsonObject rawVarbits = new JsonObject();

		final int spellbook = client.getVarbitValue(Varbits.SPELLBOOK);
		rawVarbits.addProperty("SPELLBOOK", spellbook);
		final String book = spellbookKey(spellbook);
		if (book != null)
		{
			// NOTE for reconciliation: this observes the *active* spellbook, which is not the
			// same fact as "Ancients are unlocked". The schema's `unlock` semantics want the
			// latter. Recorded here so the diff catches it rather than the app believing it.
			out.add(unlock("spellbook_" + book, "unlocked"));
		}

		for (Map.Entry<String, Integer> varbit : constantsWithPrefix("DIARY_").entrySet())
		{
			final int value = client.getVarbitValue(varbit.getValue());
			rawVarbits.addProperty(varbit.getKey(), value);
			out.add(unlock(slug(varbit.getKey()), value > 0 ? "unlocked" : "locked"));
		}

		for (Map.Entry<String, Integer> varbit : constantsWithPrefix("COMBAT_ACHIEVEMENT_TIER_").entrySet())
		{
			final int value = client.getVarbitValue(varbit.getValue());
			rawVarbits.addProperty(varbit.getKey(), value);
			final String tier = varbit.getKey().substring("COMBAT_ACHIEVEMENT_TIER_".length());
			out.add(unlock("ca_" + slug(tier), value > 0 ? "unlocked" : "locked"));
		}

		raw.add("varbits", rawVarbits);
		return out;
	}

	private static JsonObject unlock(String key, String state)
	{
		final JsonObject entry = new JsonObject();
		entry.addProperty("key", key);
		entry.addProperty("state", state);
		return entry;
	}

	private static String spellbookKey(int value)
	{
		switch (value)
		{
			case 0:
				return "standard";
			case 1:
				return "ancient";
			case 2:
				return "lunar";
			case 3:
				return "arceuus";
			default:
				return null;
		}
	}

	private static Map<String, Integer> constantsWithPrefix(String prefix)
	{
		final Map<String, Integer> out = new LinkedHashMap<>();
		for (Field field : Varbits.class.getDeclaredFields())
		{
			if (!Modifier.isStatic(field.getModifiers()) || field.getType() != int.class)
			{
				continue;
			}
			if (!field.getName().startsWith(prefix))
			{
				continue;
			}
			try
			{
				out.put(field.getName(), field.getInt(null));
			}
			catch (IllegalAccessException ignored)
			{
				// A public constant on a public class; unreachable in practice.
			}
		}
		return out;
	}

	/**
	 * One container, sourced from the {@code ItemContainerChanged} cache and falling back to the
	 * (so far always-null) direct lookup. A container never observed emits <b>no</b> scan row:
	 * §6.5's "never looked" must stay distinguishable from "looked, found nothing".
	 */
	private static void collectContainer(Client client, ContainerCache containers, int inventoryId,
		String container, JsonArray observedItems, JsonArray containerScans, JsonObject raw)
	{
		final JsonObject diagnostics = new JsonObject();
		diagnostics.addProperty("requested_id", inventoryId);

		final ContainerCache.Observation observed = containers.get(inventoryId);
		final Item[] items;
		final Instant seenAt;
		if (observed != null)
		{
			diagnostics.addProperty("resolved_by", "item_container_changed_event");
			diagnostics.addProperty("size", observed.size);
			items = observed.items;
			seenAt = observed.observedAt;
		}
		else
		{
			final ItemContainer direct = findContainer(client, inventoryId);
			diagnostics.addProperty("resolved_by", direct == null ? "none" : resolutionPath(client, inventoryId));
			if (direct == null)
			{
				diagnostics.addProperty("scan_emitted", false);
				raw.add(container, diagnostics);
				return;
			}
			diagnostics.addProperty("size", direct.size());
			items = direct.getItems();
			// No event time available, so the best available answer is "now" — recorded as such
			// rather than passed off as an observation time (§4.5).
			seenAt = Instant.now();
			diagnostics.addProperty("scan_time_is_capture_time", true);
		}

		diagnostics.addProperty("placeholders_skipped", addItems(items, container, observedItems));
		diagnostics.addProperty("scan_emitted", true);
		raw.add(container, diagnostics);

		final JsonObject scan = new JsonObject();
		scan.addProperty("container", container);
		// §4.5: stamped when the contents were seen, not when the hotkey was pressed.
		scan.addProperty("scanned_at", rfc3339(seenAt));
		containerScans.add(scan);
	}

	/**
	 * The bank interface's open/close edges. No longer the scan anchor — the event cache carries
	 * a truer observation time — but kept as evidence for the reconciliation doc's question of
	 * whether a <em>complete</em> bank scan is detectable at all.
	 */
	private static JsonObject bankWidgetEdges(BankWatch bankWatch)
	{
		final JsonObject edges = new JsonObject();
		edges.addProperty("ever_opened_this_session", bankWatch.everOpened());
		edges.addProperty("last_opened_at", bankWatch.openedAt() == null ? null : rfc3339(bankWatch.openedAt()));
		edges.addProperty("last_closed_at", bankWatch.closedAt() == null ? null : rfc3339(bankWatch.closedAt()));
		return edges;
	}

	/**
	 * The first capture came back with every container null — inventory, equipment and bank
	 * alike, on a LOGGED_IN client whose bank had been opened and closed. The gameval ids are
	 * right (INV=93, WORN=94, BANK=95, identical to the deprecated enum's), so the id-keyed
	 * lookup itself is what failed. {@link Client#getItemContainers()} is an iterable hash table
	 * of everything the client currently holds, so fall back to scanning it rather than
	 * concluding the account owns nothing.
	 */
	private static ItemContainer findContainer(Client client, int inventoryId)
	{
		final ItemContainer direct = client.getItemContainer(inventoryId);
		if (direct != null)
		{
			return direct;
		}

		final HashTable<ItemContainer> table = client.getItemContainers();
		if (table == null)
		{
			return null;
		}
		for (ItemContainer candidate : table)
		{
			if (candidate.getId() == inventoryId || candidate.getHash() == inventoryId)
			{
				return candidate;
			}
		}
		return null;
	}

	/** Which path produced the container — the finding itself, recorded per container. */
	private static String resolutionPath(Client client, int inventoryId)
	{
		if (client.getItemContainer(inventoryId) != null)
		{
			return "direct";
		}
		return findContainer(client, inventoryId) != null ? "hash_table_scan" : "none";
	}

	/**
	 * Every container id that ever fired an {@code ItemContainerChanged}, whether or not the
	 * snapshot maps it. The third capture saw <b>only</b> id 95 (bank) on an account whose
	 * inventory and equipment were empty in game — evidence that an empty container may never
	 * fire at all, which would mean events alone cannot witness "looked, found nothing" (§6.5).
	 */
	private static JsonArray containerEvents(ContainerCache containers)
	{
		final JsonArray out = new JsonArray();
		for (Map.Entry<Integer, ContainerCache.Observation> entry : containers.all().entrySet())
		{
			final JsonObject event = new JsonObject();
			event.addProperty("id", entry.getKey());
			event.addProperty("observed_at", rfc3339(entry.getValue().observedAt));
			event.addProperty("size", entry.getValue().size);
			out.add(event);
		}
		return out;
	}

	/** Every container the client currently holds. Evidence, not guesswork, for the next diff. */
	private static JsonArray presentContainers(Client client)
	{
		final JsonArray out = new JsonArray();
		final HashTable<ItemContainer> table = client.getItemContainers();
		if (table == null)
		{
			return out;
		}
		for (ItemContainer container : table)
		{
			final JsonObject entry = new JsonObject();
			entry.addProperty("id", container.getId());
			entry.addProperty("hash", container.getHash());
			entry.addProperty("size", container.size());
			out.add(entry);
		}
		return out;
	}

	/** @return how many placeholder/empty slots were skipped — schema requires quantity ≥ 1. */
	private static int addItems(Item[] items, String containerName, JsonArray observedItems)
	{
		final Map<Integer, Integer> totals = new LinkedHashMap<>();
		int skipped = 0;
		for (Item item : items)
		{
			if (item.getId() <= 0 || item.getQuantity() <= 0)
			{
				skipped++;
				continue;
			}
			totals.merge(item.getId(), item.getQuantity(), Integer::sum);
		}
		for (Map.Entry<Integer, Integer> entry : totals.entrySet())
		{
			final JsonObject observed = new JsonObject();
			observed.addProperty("item_id", entry.getKey());
			observed.addProperty("quantity", entry.getValue());
			observed.addProperty("container", containerName);
			observedItems.add(observed);
		}
		return skipped;
	}

	/** The schema's timestamp: an RFC 3339 instant with an explicit offset, seconds precision. */
	private static String rfc3339(Instant instant)
	{
		return DateTimeFormatter.ISO_INSTANT.format(instant.truncatedTo(ChronoUnit.SECONDS));
	}

	private static String slug(String constantName)
	{
		return constantName.toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9]+", "_").replaceAll("^_+|_+$", "");
	}
}
