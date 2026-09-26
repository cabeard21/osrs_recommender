package com.osrstracker.plugin;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.osrstracker.plugin.contract.SyncPayloadFields;

import java.time.Instant;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.List;

/**
 * One sync payload, built in memory and serialized to the frozen §12.1 contract.
 *
 * <p>Every key comes from {@link SyncPayloadFields}, which is generated from
 * {@code contracts/sync_payload.schema.json} at build time — renaming a property in the schema
 * breaks compilation here rather than producing a payload the server rejects at runtime.
 *
 * <p>Step 12a builds only the identity half; {@link Builder}'s collections stay empty until
 * Step 12b's collectors fill them. An empty collection is omitted rather than serialized as
 * {@code []}, because §6.5 draws a hard line between "observed, and there was nothing" and
 * "never observed" — an empty array claims the former.
 */
public final class AccountSnapshot
{
	/**
	 * §12.2. The server declares {@code SUPPORTED_PAYLOAD_VERSIONS = {1}}; anything else is a
	 * 409. Frozen against a real snapshot on 2026-08-11 — see docs/CONTRACT_RECONCILIATION.md.
	 */
	public static final int PAYLOAD_VERSION = 1;

	private final Instant observedAt;
	private final String username;
	private final String displayName;
	private final Integer combatLevel;
	private final Integer questPoints;
	private final List<Skill> skills;
	private final List<Quest> quests;
	private final List<Unlock> unlocks;
	private final List<ObservedItem> observedItems;
	private final List<ContainerScan> containerScans;

	private AccountSnapshot(Builder builder)
	{
		this.observedAt = builder.observedAt;
		this.username = builder.username;
		this.displayName = builder.displayName;
		this.combatLevel = builder.combatLevel;
		this.questPoints = builder.questPoints;
		this.skills = new ArrayList<>(builder.skills);
		this.quests = new ArrayList<>(builder.quests);
		this.unlocks = new ArrayList<>(builder.unlocks);
		this.observedItems = new ArrayList<>(builder.observedItems);
		this.containerScans = new ArrayList<>(builder.containerScans);
	}

	public String username()
	{
		return username;
	}

	public JsonObject toJson()
	{
		final JsonObject root = new JsonObject();
		root.addProperty(SyncPayloadFields.PAYLOAD_VERSION, PAYLOAD_VERSION);
		root.addProperty(SyncPayloadFields.OBSERVED_AT, timestamp(observedAt));

		final JsonObject player = new JsonObject();
		player.addProperty(SyncPayloadFields.Player.USERNAME, username);
		if (displayName != null)
		{
			player.addProperty(SyncPayloadFields.Player.DISPLAY_NAME, displayName);
		}
		if (combatLevel != null)
		{
			player.addProperty(SyncPayloadFields.Player.COMBAT_LEVEL, combatLevel);
		}
		if (questPoints != null)
		{
			player.addProperty(SyncPayloadFields.Player.QUEST_POINTS, questPoints);
		}
		root.add(SyncPayloadFields.PLAYER, player);

		addIfPresent(root, SyncPayloadFields.SKILLS, skills);
		addIfPresent(root, SyncPayloadFields.QUESTS, quests);
		addIfPresent(root, SyncPayloadFields.UNLOCKS, unlocks);
		addIfPresent(root, SyncPayloadFields.OBSERVED_ITEMS, observedItems);
		addIfPresent(root, SyncPayloadFields.CONTAINER_SCANS, containerScans);
		return root;
	}

	private static void addIfPresent(JsonObject root, String key, List<? extends Entry> entries)
	{
		if (entries.isEmpty())
		{
			// §6.5: `[]` asserts "observed, empty". Silence asserts nothing. Only the collectors
			// know which is true, so an unpopulated section is omitted entirely.
			return;
		}
		final JsonArray array = new JsonArray();
		for (Entry entry : entries)
		{
			array.add(entry.toJson());
		}
		root.add(key, array);
	}

	/** RFC 3339 with an explicit offset, seconds precision — the contract's {@code timestamp}. */
	static String timestamp(Instant instant)
	{
		return DateTimeFormatter.ISO_INSTANT.format(instant.truncatedTo(ChronoUnit.SECONDS));
	}

	/** Anything that serializes to one element of a contract array. */
	interface Entry
	{
		JsonObject toJson();
	}

	public static final class Skill implements Entry
	{
		private final String skill;
		private final int level;
		private final Integer xp;

		public Skill(String skill, int level, Integer xp)
		{
			this.skill = skill;
			this.level = level;
			this.xp = xp;
		}

		@Override
		public JsonObject toJson()
		{
			final JsonObject json = new JsonObject();
			json.addProperty(SyncPayloadFields.Skill.SKILL, skill);
			json.addProperty(SyncPayloadFields.Skill.LEVEL, level);
			// G5: null means unranked, never 0. The client never reports -1 (see the
			// reconciliation doc), so nothing normalizes here — but the null stays expressible.
			json.addProperty(SyncPayloadFields.Skill.XP, xp);
			return json;
		}
	}

	public static final class Quest implements Entry
	{
		private final String questId;
		private final String status;

		public Quest(String questId, String status)
		{
			this.questId = questId;
			this.status = status;
		}

		@Override
		public JsonObject toJson()
		{
			final JsonObject json = new JsonObject();
			json.addProperty(SyncPayloadFields.Quest.QUEST_ID, questId);
			json.addProperty(SyncPayloadFields.Quest.STATUS, status);
			return json;
		}
	}

	public static final class Unlock implements Entry
	{
		private final String key;
		private final String state;

		public Unlock(String key, String state)
		{
			this.key = key;
			this.state = state;
		}

		@Override
		public JsonObject toJson()
		{
			final JsonObject json = new JsonObject();
			json.addProperty(SyncPayloadFields.Unlock.KEY, key);
			json.addProperty(SyncPayloadFields.Unlock.STATE, state);
			return json;
		}
	}

	public static final class ObservedItem implements Entry
	{
		private final int itemId;
		private final int quantity;
		private final String container;

		public ObservedItem(int itemId, int quantity, String container)
		{
			this.itemId = itemId;
			this.quantity = quantity;
			this.container = container;
		}

		@Override
		public JsonObject toJson()
		{
			final JsonObject json = new JsonObject();
			json.addProperty(SyncPayloadFields.ObservedItem.ITEM_ID, itemId);
			json.addProperty(SyncPayloadFields.ObservedItem.QUANTITY, quantity);
			json.addProperty(SyncPayloadFields.ObservedItem.CONTAINER, container);
			return json;
		}
	}

	public static final class ContainerScan implements Entry
	{
		private final String container;
		private final Instant scannedAt;

		public ContainerScan(String container, Instant scannedAt)
		{
			this.container = container;
			this.scannedAt = scannedAt;
		}

		@Override
		public JsonObject toJson()
		{
			final JsonObject json = new JsonObject();
			json.addProperty(SyncPayloadFields.ContainerScan.CONTAINER, container);
			// §4.5: when the container was seen, never when the payload was assembled.
			json.addProperty(SyncPayloadFields.ContainerScan.SCANNED_AT, timestamp(scannedAt));
			return json;
		}
	}

	public static Builder builder(String username, Instant observedAt)
	{
		return new Builder(username, observedAt);
	}

	public static final class Builder
	{
		private final String username;
		private final Instant observedAt;
		private String displayName;
		private Integer combatLevel;
		private Integer questPoints;
		private final List<Skill> skills = new ArrayList<>();
		private final List<Quest> quests = new ArrayList<>();
		private final List<Unlock> unlocks = new ArrayList<>();
		private final List<ObservedItem> observedItems = new ArrayList<>();
		private final List<ContainerScan> containerScans = new ArrayList<>();

		private Builder(String username, Instant observedAt)
		{
			this.username = username;
			this.observedAt = observedAt;
		}

		public Builder displayName(String value)
		{
			this.displayName = value;
			return this;
		}

		public Builder combatLevel(Integer value)
		{
			this.combatLevel = value;
			return this;
		}

		public Builder questPoints(Integer value)
		{
			this.questPoints = value;
			return this;
		}

		public Builder skill(Skill value)
		{
			skills.add(value);
			return this;
		}

		public Builder quest(Quest value)
		{
			quests.add(value);
			return this;
		}

		public Builder unlock(Unlock value)
		{
			unlocks.add(value);
			return this;
		}

		public Builder item(ObservedItem value)
		{
			observedItems.add(value);
			return this;
		}

		public Builder containerScan(ContainerScan value)
		{
			containerScans.add(value);
			return this;
		}

		public AccountSnapshot build()
		{
			return new AccountSnapshot(this);
		}
	}
}
